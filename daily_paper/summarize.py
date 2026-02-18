from __future__ import annotations

import re
from dataclasses import dataclass
from .config import DailyPaperConfig
from .fetch import FeedEntry
from .openai_client import OpenAIClient, get_client
from .utils import compact_text, get_hostname, log_verbose, title_similarity

ITEM_SYSTEM_PROMPT = (
    "You are a careful news summarizer.\n"
    "Write a short micro-paragraph: 1–2 complete sentences, plain language, <= 32 words total.\n"
    "Sentence 1: state what happened.\n"
    "Sentence 2 (optional): add specific, non-obvious significance ONLY if explicitly supported by the provided text.\n"
    "If no specific significance is supported, output ONLY sentence 1.\n"
    "Do NOT restate sentence 1 in different words.\n"
    "Do NOT use tautological or generic significance lines (e.g., 'this changes leadership', 'this is important', 'this could have impacts').\n"
    "If the title indicates a roundup/comparison/list format (e.g., 'what you can buy', 'top', 'roundup', 'X under $Y'), summarize the article's overall framing, not a single example item.\n"
    "Neutral and factual: no sensational adjectives, no loaded framing, no speculation, no motive attribution.\n"
    "Grounding: use ONLY facts present in the provided title/summary/text. Do not add new details.\n"
    "If evidence is unclear, output exactly: Details are unclear.\n"
)

SELECTION_SYSTEM_PROMPT = (
    "You are a neutral news editor selecting the most important items for a topic.\n"
    "Primary goals, in order: (1) relevance/public significance, (2) source diversity, (3) deduplication.\n"
    "Treat each listed source label as the diversity unit.\n"
    "\n"
    "Duplicate policy (strict):\n"
    "- Treat translated, reworded, or URL-variant versions of the same event from the same source as duplicates.\n"
    "- If two items share the same source/domain and substantially the same event, select only one.\n"
    "- If dup_group_id is provided, select at most one item per dup_group_id.\n"
    "\n"
    "Selection constraints:\n"
    "- Avoid thin or administrative items unless they imply clear public impact.\n"
    "- If alternatives exist, avoid choosing more than two items from the same source/domain in the top five.\n"
    "\n"
    "Return ONLY a comma-separated list of item numbers (e.g., '2, 5, 1, 7, 3').\n"
    "If fewer items exist than requested, return all available numbers.\n"
)

TOPIC_SYSTEM_PROMPT = (
    "You write neutral, multi-source topic summaries for a daily paper.\n"
    "Write ONE short paragraph: 2–4 complete sentences, plain language, <= 50 words.\n"
    "\n"
    "Purpose: tie today's items into the broader story of this topic—what trend they reflect, "
    "why it matters, and how a reader should interpret it.\n"
    "\n"
    "Do NOT restate or paraphrase the individual items. "
    "Do NOT repeat item-level proper nouns, committee names, report titles, or exact figures already shown.\n"
    "\n"
    "Instead, synthesize: describe the theme, highlight the key tension/tradeoff or uncertainty, "
    "and give one practical lens (who is affected or what decisions it informs).\n"
    "\n"
    "Avoid generic statements like 'ongoing monitoring'; be specific about the kind of change "
    "(pace, direction, risk, adoption, constraints).\n"
    "\n"
    "Neutral and factual: no sensational framing, no speculation, no motive attribution.\n"
    "Grounding: use ONLY the provided items as evidence. Do not add external facts or forecasts.\n"
    "If the items lack enough detail to synthesize, write: 'Not enough accessible detail to synthesize today.'\n"
)

@dataclass
class SummarizedItem:
    entry: FeedEntry
    summary: str


@dataclass
class TopicSummary:
    topic: str
    summary: str


@dataclass(frozen=True)
class EntryMeta:
    domain: str
    summary_length: int
    is_low_info: bool
    is_admin: bool
    has_published: bool


ADMIN_KEYWORDS = (
    "newsletter",
    "podcast",
    "opinion",
    "sponsored",
    "advertisement",
    "press release",
    "webinar",
    "event",
    "roundup",
    "digest",
    "transcript",
)

LOCAL_NEWS_TOPIC = "Local News"
LOCAL_NEWS_MIN_SCORE = 1.0
LOCAL_STRONG_POSITIVE_TERMS = (
    "polson",
    "lake county",
    "kalispell",
    "flathead",
    "ronan",
    "pablo",
    "bigfork",
    "columbia falls",
    "whitefish",
    "mission valley",
)
LOCAL_MEDIUM_POSITIVE_TERMS = (
    "montana",
    " mt ",
    " mt.",
)
LOCAL_OVERRIDE_TERMS = (
    "legislation",
    "legislature",
    "bill",
    "wildfire",
    "fire season",
    "weather",
    "school funding",
    "education funding",
    "health care policy",
    "healthcare policy",
    "medicaid",
)
OTHER_STATE_DATELINE_PATTERN = re.compile(
    r"\b([a-z][a-z\s\.-]+),\s*(?:"
    r"alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|"
    r"georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|"
    r"massachusetts|michigan|minnesota|mississippi|missouri|nebraska|nevada|new hampshire|"
    r"new jersey|new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|"
    r"pennsylvania|rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|"
    r"virginia|washington|west virginia|wisconsin|wyoming"
    r")\b",
    re.IGNORECASE,
)
MONTANA_ZIP_PATTERN = re.compile(r"\b59\d{3}\b")


def _entry_meta(entry: FeedEntry) -> EntryMeta:
    summary = compact_text([entry.summary], 280)
    summary_length = len(summary)
    combined = f"{entry.title} {summary}".lower()
    is_admin = any(keyword in combined for keyword in ADMIN_KEYWORDS)
    is_low_info = summary_length < 60
    return EntryMeta(
        domain=get_hostname(entry.link),
        summary_length=summary_length,
        is_low_info=is_low_info,
        is_admin=is_admin,
        has_published=bool(entry.published),
    )


def _entry_score(meta: EntryMeta) -> float:
    score = 0.0
    if meta.has_published:
        score += 1.0
    score += min(meta.summary_length, 220) / 220
    if meta.is_low_info:
        score -= 1.0
    if meta.is_admin:
        score -= 0.75
    return score


def select_top_items(
    config: DailyPaperConfig,
    entries: list[FeedEntry],
    topic: str,
    limit: int,
) -> list[FeedEntry]:
    """Select the most important items for a topic using a simple AI ranking prompt."""
    filtered_entries = entries
    if topic == LOCAL_NEWS_TOPIC:
        filtered_entries = _filter_local_news_entries(config, entries)

    meta_by_link = {entry.link: _entry_meta(entry) for entry in filtered_entries}
    ranked_entries = _rank_entries(topic, filtered_entries, meta_by_link)
    if len(filtered_entries) <= limit:
        return _apply_selection_constraints(
            chosen=ranked_entries,
            ranked_entries=ranked_entries,
            meta_by_link=meta_by_link,
            limit=limit,
            max_items_per_source=config.max_items_per_source,
        )

    # Use a dedicated model for selection so ranking can be tuned independently.
    client = get_client(config, config.selection_model, config.temperature)
    log_verbose(config.verbose, f"Selecting top {limit} items for '{topic}'.")

    items_text = "\n".join(
        f"{idx}. {entry.title} ({_selection_source_label(entry)}, {meta_by_link[entry.link].domain}) — "
        f"{compact_text([entry.summary], 220)}"
        for idx, entry in enumerate(ranked_entries, start=1)
    )
    source_limit_note = ""
    if config.max_items_per_source is not None:
        source_limit_note = (
            f"No more than {config.max_items_per_source} items may come from the same source label.\n"
        )
    user_prompt = (
        f"Topic: {topic}\n"
        f"Pick the {limit} most important items from the list.\n"
        f"{source_limit_note}\n"
        f"Items:\n{items_text}"
    )
    selection = client.chat_completion(SELECTION_SYSTEM_PROMPT, user_prompt)
    indices = _parse_selection(selection, len(ranked_entries), limit)
    chosen = [ranked_entries[idx - 1] for idx in indices]
    return _apply_selection_constraints(
        chosen,
        ranked_entries,
        meta_by_link,
        limit,
        max_items_per_source=config.max_items_per_source,
    )


def _selection_source_label(entry: FeedEntry) -> str:
    return entry.source_group


def _rank_entries(
    topic: str,
    entries: list[FeedEntry],
    meta_by_link: dict[str, EntryMeta],
) -> list[FeedEntry]:
    if topic == LOCAL_NEWS_TOPIC:
        local_scores = {entry.link: _local_news_relevance_score(entry) for entry in entries}
        return sorted(
            entries,
            key=lambda entry: (
                local_scores[entry.link],
                _entry_score(meta_by_link[entry.link]),
                entry.title.lower(),
            ),
            reverse=True,
        )
    return sorted(
        entries,
        key=lambda entry: (_entry_score(meta_by_link[entry.link]), entry.title.lower()),
        reverse=True,
    )

def _filter_local_news_entries(config: DailyPaperConfig, entries: list[FeedEntry]) -> list[FeedEntry]:
    scored_entries: list[tuple[float, FeedEntry]] = [
        (_local_news_relevance_score(entry), entry) for entry in entries
    ]
    kept = [
        (score, entry)
        for score, entry in scored_entries
        if score >= LOCAL_NEWS_MIN_SCORE
    ]
    log_verbose(
        config.verbose,
        f"Local News relevance filter kept {len(kept)}/{len(entries)} items "
        f"(threshold={LOCAL_NEWS_MIN_SCORE}).",
    )
    kept.sort(key=lambda item: (item[0], item[1].title.lower()), reverse=True)
    return [entry for _, entry in kept]


def _local_news_relevance_score(entry: FeedEntry) -> float:
    combined = f"{entry.title} {entry.summary}".lower()
    score = 0.0

    for term in LOCAL_STRONG_POSITIVE_TERMS:
        if term in combined:
            score += 3.0
    if any(term in combined for term in LOCAL_MEDIUM_POSITIVE_TERMS):
        score += 1.0
    if MONTANA_ZIP_PATTERN.search(combined):
        score += 1.0

    has_mt_context = "montana" in combined or " mt " in combined or " mt." in combined
    has_other_state_dateline = OTHER_STATE_DATELINE_PATTERN.search(combined) is not None
    if has_other_state_dateline and not has_mt_context:
        score -= 4.0

    has_statewide_impact = any(term in combined for term in LOCAL_OVERRIDE_TERMS)
    if has_mt_context and has_statewide_impact:
        score = max(score, LOCAL_NEWS_MIN_SCORE)
        score += 2.0

    return score


def _parse_selection(response: str, total: int, limit: int) -> list[int]:
    """Parse item numbers from the model response with safe fallbacks."""
    # Prefer a comma-separated list to avoid picking up stray numbers (e.g., "Top 5").
    candidates: list[int] = []
    tokens = [token.strip() for token in response.replace("\n", " ").split(",")]
    for token in tokens:
        if re.fullmatch(r"\d+", token):
            candidates.append(int(token))

    if not candidates:
        # If the model adds a prefix like "Top 5:", ignore everything before the last colon.
        trimmed = response.rsplit(":", maxsplit=1)[-1]
        candidates = [int(match) for match in re.findall(r"\b\d+\b", trimmed)]
    unique: list[int] = []
    for number in candidates:
        if 1 <= number <= total and number not in unique:
            unique.append(number)
        if len(unique) == limit:
            break

    if len(unique) < limit:
        # Fill remaining slots with the earliest items to ensure deterministic output.
        for number in range(1, total + 1):
            if number not in unique:
                unique.append(number)
            if len(unique) == limit:
                break
    return unique


def summarize_items(
    config: DailyPaperConfig,
    entries: list[FeedEntry],
    topic: str | None = None,
) -> list[SummarizedItem]:
    client = get_client(config, config.item_model, config.temperature)
    summarized: list[SummarizedItem] = []
    label = f"'{topic}'" if topic else "topic"
    log_verbose(config.verbose, f"Summarizing {len(entries)} items for {label}.")
    for entry in entries:
        log_verbose(config.verbose, f"Summarizing item: {entry.title}")
        summary = summarize_item(client, entry, config)
        summarized.append(SummarizedItem(entry=entry, summary=summary))
    return summarized


def summarize_item(client: OpenAIClient, entry: FeedEntry, config: DailyPaperConfig) -> str:
    description = compact_text([entry.summary, entry.full_text or ""], 1200)
    user_prompt = (
        "Summarize the following item in one neutral sentence. "
        "Follow the required structure. Do not invent facts.\n\n"
        f"Title: {entry.title}\n"
        f"Description: {description}\n"
        f"Source: {entry.source}\n"
    )
    return client.chat_completion(ITEM_SYSTEM_PROMPT, user_prompt, topic=entry.topic)


def summarize_topic(
    config: DailyPaperConfig, topic: str, items: list[SummarizedItem]
) -> TopicSummary:
    # Use the configured topic model for multi-item synthesis.
    client = get_client(config, config.topic_model, config.temperature)
    log_verbose(config.verbose, f"Generating topic summary for '{topic}'.")
    bullet_points = "\n".join(
        f"- {item.entry.title}: {compact_text([item.entry.summary], 280)}"
        for item in items
    )
    user_prompt = (
        f"Write the macro summary for {topic}. Use only the items below.\n\n"
        f"Items:\n{bullet_points}"
    )
    # Retry topic summary generation if the model returns empty/whitespace output.
    max_attempts = config.topic_summary_max_retries
    for attempt in range(max_attempts):
        summary = client.chat_completion(TOPIC_SYSTEM_PROMPT, user_prompt, topic=topic)
        if summary.strip():  # Check if the summary is not empty or just whitespace
            log_verbose(
                config.verbose,
                f"Topic summary generated successfully on attempt {attempt + 1} for '{topic}'.",
            )
            return TopicSummary(topic=topic, summary=summary)
        log_verbose(
            config.verbose,
            f"Topic summary empty on attempt {attempt + 1} for '{topic}'. Retrying...",
        )
    log_verbose(
        config.verbose,
        f"Failed to generate a non-empty topic summary after {max_attempts} attempts for '{topic}'.",
    )
    return TopicSummary(topic=topic, summary="")


def _apply_selection_constraints(
    chosen: list[FeedEntry],
    ranked_entries: list[FeedEntry],
    meta_by_link: dict[str, EntryMeta],
    limit: int,
    max_items_per_source: int | None,
) -> list[FeedEntry]:
    candidate_pool = chosen + [entry for entry in ranked_entries if entry not in chosen]
    selected: list[FeedEntry] = []
    deferred: list[FeedEntry] = []
    for idx, entry in enumerate(candidate_pool):
        if len(selected) >= limit:
            break
        if _is_near_duplicate(entry, selected):
            continue
        if _hits_source_cap(entry, selected, max_items_per_source):
            deferred.append(entry)
            continue
        if _violates_diversity(entry, selected, candidate_pool[idx + 1 :], meta_by_link):
            deferred.append(entry)
            continue
        meta = meta_by_link[entry.link]
        if meta.is_low_info or meta.is_admin:
            deferred.append(entry)
            continue
        selected.append(entry)
    for entry in deferred:
        if len(selected) >= limit:
            break
        if _is_near_duplicate(entry, selected):
            continue
        if _hits_source_cap(entry, selected, max_items_per_source):
            continue
        selected.append(entry)
    if len(selected) < limit:
        for entry in candidate_pool:
            if len(selected) >= limit:
                break
            if entry in selected:
                continue
            if _is_near_duplicate(entry, selected):
                continue
            if _hits_source_cap(entry, selected, max_items_per_source):
                continue
            selected.append(entry)
    return selected


def _hits_source_cap(
    entry: FeedEntry,
    selected: list[FeedEntry],
    max_items_per_source: int | None,
) -> bool:
    if max_items_per_source is None:
        return False
    source_key = _selection_source_label(entry)
    return sum(1 for item in selected if _selection_source_label(item) == source_key) >= max_items_per_source


def _is_near_duplicate(entry: FeedEntry, selected: list[FeedEntry], threshold: float = 0.86) -> bool:
    entry_domain = get_hostname(entry.link)
    for existing in selected:
        if get_hostname(existing.link) != entry_domain:
            continue
        if title_similarity(entry.title, existing.title) >= threshold:
            return True
    return False


def _violates_diversity(
    entry: FeedEntry,
    selected: list[FeedEntry],
    remaining: list[FeedEntry],
    meta_by_link: dict[str, EntryMeta],
    cap: int = 2,
) -> bool:
    if len(selected) >= 5:
        return False
    domain = meta_by_link[entry.link].domain
    if sum(1 for item in selected if meta_by_link[item.link].domain == domain) < cap:
        return False
    return any(meta_by_link[item.link].domain != domain for item in remaining)
