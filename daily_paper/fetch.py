from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable

import feedparser
import requests
from bs4 import BeautifulSoup

from .config import DailyPaperConfig, FeedSource, TopicConfig
from .utils import compact_text, normalize_url, parse_published

PAYWALL_MARKERS = (
    "subscribe",
    "subscription",
    "sign in to continue",
    "already a subscriber",
    "metered",
    "paywall",
    "register to continue",
)


@dataclass
class FeedEntry:
    topic: str
    title: str
    link: str
    published: str
    source: str
    summary: str
    full_text: str | None = None


@dataclass
class FetchStats:
    sources_checked: int = 0
    paywalled: int = 0


class FetchError(RuntimeError):
    pass


def fetch_feeds(config: DailyPaperConfig) -> tuple[dict[str, list[FeedEntry]], FetchStats]:
    entries_by_topic: dict[str, list[FeedEntry]] = {topic.name: [] for topic in config.topics}
    seen_urls: set[str] = set()
    stats = FetchStats()

    for topic in config.topics:
        for feed in topic.feeds:
            stats.sources_checked += 1
            parsed = feedparser.parse(feed.url)
            if parsed.bozo and not parsed.entries:
                continue
            for entry in parsed.entries:
                link = entry.get("link")
                title = entry.get("title", "").strip()
                if not link or not title:
                    continue
                normalized = normalize_url(link)
                if normalized in seen_urls:
                    continue
                seen_urls.add(normalized)
                published = entry.get("published") or entry.get("updated")
                published_dt = parse_published(published)
                summary = entry.get("summary", "")
                item = FeedEntry(
                    topic=topic.name,
                    title=title,
                    link=normalized,
                    published=published_dt.isoformat() if published_dt else "",
                    source=entry.get("source", {}).get("title") or feed.name,
                    summary=summary,
                )
                if config.fetch_full_text:
                    item.full_text, paywalled = fetch_full_text(item, config)
                    if paywalled:
                        stats.paywalled += 1
                        continue
                entries_by_topic[topic.name].append(item)
    return entries_by_topic, stats


def fetch_full_text(entry: FeedEntry, config: DailyPaperConfig) -> tuple[str | None, bool]:
    try:
        response = requests.get(
            entry.link,
            timeout=15,
            headers={"User-Agent": "DailyPaperBot/1.0"},
        )
    except requests.RequestException:
        return None, False

    if response.status_code in {401, 402, 403, 451}:
        return None, True

    html = response.text
    lowered = html.lower()
    if any(marker in lowered for marker in PAYWALL_MARKERS):
        return None, True

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    article = soup.find("article") or soup.find("main") or soup.body
    if not article:
        return None, False

    paragraphs = [p.get_text(" ", strip=True) for p in article.find_all("p")]
    text = compact_text(paragraphs, config.max_full_text_chars)
    time.sleep(0.2)
    return text or None, False
