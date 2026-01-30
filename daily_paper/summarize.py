from __future__ import annotations

import re
from dataclasses import dataclass

from .config import DailyPaperConfig
from .fetch import FeedEntry
from .openai_client import OpenAIClient, get_client
from .utils import compact_text, log_verbose

ITEM_SYSTEM_PROMPT = (
    "You are a careful news summarizer.\n"
    "Write EXACTLY ONE sentence, plain language, <= 20 words.\n"
    "Neutral and factual: no sensational adjectives, no loaded framing, no speculation, no motive attribution.\n"
    "Grounding: use ONLY facts present in the provided title/summary/text. Do not add new details.\n"
    "Prefer: what happened + the immediate significance (if supported).\n"
    "If evidence is unclear, say 'Details are unclear.' (and keep within the word limit).\n"
)

SELECTION_SYSTEM_PROMPT = (
    "You are a neutral news editor selecting the five most important items for a topic.\n"
    "Choose items with broad public significance, reliable sourcing, and minimal duplication.\n"
    "Return ONLY a comma-separated list of item numbers (e.g., '2, 5, 1, 7, 3').\n"
    "If fewer than five items exist, return all available numbers.\n"
)

TOPIC_SYSTEM_PROMPT = (
    "You write neutral, multi-source topic summaries.\n"
    "Length: 3–6 sentences, <= 100 words.\n"
    "Do NOT paraphrase headlines; synthesize themes and implications.\n"
    "Grounding: Prefer the provided items. If you must use external context, "
    "limit it to 1–2 short clauses and clearly mark it as 'Background:' and keep it high-level and factual. "
    "Never introduce new breaking facts beyond the provided items.\n"
    "If evidence is unclear, say so briefly.\n"
    "Tone: calm, unsensational, no speculation; avoid attributing motives.\n"
)

@dataclass
class SummarizedItem:
    entry: FeedEntry
    summary: str


@dataclass
class TopicSummary:
    topic: str
    summary: str


def select_top_items(
    config: DailyPaperConfig,
    entries: list[FeedEntry],
    topic: str,
    limit: int = 5,
) -> list[FeedEntry]:
    """Select the most important items for a topic using a simple AI ranking prompt."""
    if len(entries) <= limit:
        return entries

    client = get_client(config.resolve_item_model(), config.temperature)
    log_verbose(config.verbose, f"Selecting top {limit} items for '{topic}'.")

    items_text = "\n".join(
        f"{idx}. {entry.title} ({entry.source}) — {compact_text([entry.summary], 220)}"
        for idx, entry in enumerate(entries, start=1)
    )
    user_prompt = (
        f"Topic: {topic}\n"
        "Pick the five most important items from the list.\n\n"
        f"Items:\n{items_text}"
    )
    selection = client.chat_completion(SELECTION_SYSTEM_PROMPT, user_prompt)
    indices = _parse_selection(selection, len(entries), limit)
    return [entries[idx - 1] for idx in indices]


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
    client = get_client(config.resolve_item_model(), config.temperature)
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
        "Do not invent facts.\n\n"
        f"Title: {entry.title}\n"
        f"Description: {description}\n"
        f"Source: {entry.source}\n"
    )
    return client.chat_completion(ITEM_SYSTEM_PROMPT, user_prompt)


def summarize_topic(
    config: DailyPaperConfig, topic: str, items: list[SummarizedItem]
) -> TopicSummary:
    # Use the stronger topic model for multi-item synthesis unless overridden.
    client = get_client(config.resolve_topic_model(), config.temperature)
    log_verbose(config.verbose, f"Generating topic summary for '{topic}'.")
    bullet_points = "\n".join(
        f"- {item.entry.title}: {compact_text([item.entry.summary], 280)}"
        for item in items
    )
    user_prompt = (
        f"Write a 3-6 sentence topic summary for {topic}. "
        "Use the items below.\n\n"
        f"Items:\n{bullet_points}"
    )
    summary = client.chat_completion(TOPIC_SYSTEM_PROMPT, user_prompt)
    return TopicSummary(topic=topic, summary=summary)
