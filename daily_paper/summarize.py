from __future__ import annotations

from dataclasses import dataclass

from .config import DailyPaperConfig
from .fetch import FeedEntry
from .openai_client import OpenAIClient, get_client
from .utils import compact_text, log_verbose

ITEM_SYSTEM_PROMPT = (
    "You are a careful news summarizer. Be neutral and factual. "
    "Avoid sensational adjectives, loaded framing, or speculation. "
    "If evidence is unclear, say so briefly. "
    "Write exactly one sentence in plain language, 20-35 words."
)

TOPIC_SYSTEM_PROMPT = (
    "You write neutral multi-source topic summaries. "
    "Use 3-6 sentences. Avoid speculation or sensational framing. "
    "Highlight what happened and why it matters, using plain language. "
    "If evidence is unclear, say so briefly."
)


@dataclass
class SummarizedItem:
    entry: FeedEntry
    summary: str


@dataclass
class TopicSummary:
    topic: str
    summary: str


def summarize_items(
    config: DailyPaperConfig,
    entries: list[FeedEntry],
    topic: str | None = None,
) -> list[SummarizedItem]:
    client = get_client(config.model, config.temperature)
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
    client = get_client(config.model, config.temperature)
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
