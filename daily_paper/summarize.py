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
    "Sentence 2 (optional): briefly state why it matters (only if supported by the provided text).\n"
    "If the 'why it matters' point is not supported, omit sentence 2.\n"
    "Avoid generic importance claims (e.g., 'a major shift') unless explicitly supported.\n"
    "Neutral and factual: no sensational adjectives, no loaded framing, no speculation, no motive attribution.\n"
    "Grounding: use ONLY facts present in the provided title/summary/text. Do not add new details.\n"
    "If evidence is unclear, output exactly: Details are unclear.\n"
)

SELECTION_SYSTEM_PROMPT = (
    "You are a neutral news editor selecting the most important items for a topic.\n"
    "Choose items with broad public significance, reliable sourcing, and minimal duplication.\n"
    "Avoid near-duplicate headlines and thin or administrative items unless they signal clear public impact.\n"
    "If alternatives exist, avoid picking more than two items from the same source/domain in the top five.\n"
    "Return ONLY a comma-separated list of item numbers (e.g., '2, 5, 1, 7, 3').\n"
    "If fewer items exist than requested, return all available numbers.\n"
)

TOPIC_SYSTEM_PROMPT = (
    "You write neutral, multi-source topic summaries for a daily paper.\n"
    "Output EXACTLY two lines in this format:\n"
    "Macro: <ONE sentence, <= 24 words>\n"
    "Watch: <ONE sentence or short phrase list, <= 18 words>\n"
    "\n"
    "Neutral and factual: no sensational framing, no speculation, no motive attribution.\n"
    "Grounding: use ONLY the provided items as evidence. Do not add external facts or forecasts.\n"
    "Do NOT repeat item-level proper nouns, committee names, report titles, or exact figures already shown.\n"
    "Synthesize themes and implications; the Watch line should point to the next indicator or update.\n"
    "If the items lack enough detail to synthesize, output:\n"
    "Macro: Not enough accessible detail to synthesize.\n"
    "Watch: Next release / official update."
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
    if len(entries) <= limit:
        return entries

    # Use a dedicated model for selection so ranking can be tuned independently.
    client = get_client(config, config.selection_model, config.temperature)
    log_verbose(config.verbose, f"Selecting top {limit} items for '{topic}'.")

    meta_by_link = {entry.link: _entry_meta(entry) for entry in entries}
    ranked_entries = sorted(
        entries,
        key=lambda entry: (_entry_score(meta_by_link[entry.link]), entry.title.lower()),
        reverse=True,
    )
    items_text = "\n".join(
        f"{idx}. {entry.title} ({entry.source}, {meta_by_link[entry.link].domain}) — "
        f"{compact_text([entry.summary], 220)}"
        for idx, entry in enumerate(ranked_entries, start=1)
    )
    user_prompt = (
        f"Topic: {topic}\n"
        f"Pick the {limit} most important items from the list.\n\n"
        f"Items:\n{items_text}"
    )
    selection = client.chat_completion(SELECTION_SYSTEM_PROMPT, user_prompt)
    indices = _parse_selection(selection, len(ranked_entries), limit)
    chosen = [ranked_entries[idx - 1] for idx in indices]
    return _apply_selection_constraints(chosen, ranked_entries, meta_by_link, limit)


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
    return client.chat_completion(ITEM_SYSTEM_PROMPT, user_prompt)


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
        f"Write the Macro/Watch summary for {topic}. Use only the items below.\n\n"
        f"Items:\n{bullet_points}"
    )
    summary = client.chat_completion(TOPIC_SYSTEM_PROMPT, user_prompt)
    return TopicSummary(topic=topic, summary=summary)


def _apply_selection_constraints(
    chosen: list[FeedEntry],
    ranked_entries: list[FeedEntry],
    meta_by_link: dict[str, EntryMeta],
    limit: int,
) -> list[FeedEntry]:
    candidate_pool = chosen + [entry for entry in ranked_entries if entry not in chosen]
    selected: list[FeedEntry] = []
    deferred: list[FeedEntry] = []
    for idx, entry in enumerate(candidate_pool):
        if len(selected) >= limit:
            break
        if _is_near_duplicate(entry, selected):
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
        selected.append(entry)
    if len(selected) < limit:
        for entry in candidate_pool:
            if len(selected) >= limit:
                break
            if entry in selected:
                continue
            if _is_near_duplicate(entry, selected):
                continue
            selected.append(entry)
    return selected


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
