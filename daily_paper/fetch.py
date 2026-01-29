from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable

import feedparser
import requests
from bs4 import BeautifulSoup

from .config import DailyPaperConfig, FeedSource, TopicConfig
from .utils import compact_text, log_verbose, normalize_url, parse_published

PAYWALL_MARKERS = (
    "subscribe",
    "subscription",
    "sign in to continue",
    "already a subscriber",
    "metered",
    "paywall",
    "register to continue",
)

# Some publishers block non-browser user agents and return 403/empty feeds.
# Use a mainstream UA and accept header to reduce false negatives.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
}


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

    log_verbose(config.verbose, "Starting feed fetch.")
    for topic in config.topics:
        log_verbose(
            config.verbose,
            f"Fetching feeds for '{topic.name}' ({len(topic.feeds)} sources).",
        )
        for feed in topic.feeds:
            stats.sources_checked += 1
            log_verbose(config.verbose, f"Parsing feed: {feed.name} ({feed.url})")
            parsed = parse_feed(feed, config)
            if parsed.bozo and not parsed.entries:
                log_verbose(config.verbose, f"Feed parse failed or empty: {feed.name}")
                continue
            added = 0
            skipped = 0
            duplicates = 0
            for entry in parsed.entries:
                link = entry.get("link")
                title = entry.get("title", "").strip()
                if not link or not title:
                    skipped += 1
                    continue
                normalized = normalize_url(link)
                if normalized in seen_urls:
                    duplicates += 1
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
                        log_verbose(config.verbose, f"Paywalled item skipped: {item.link}")
                        continue
                entries_by_topic[topic.name].append(item)
                added += 1
            log_verbose(
                config.verbose,
                f"Feed summary for {feed.name}: total={len(parsed.entries)}, "
                f"added={added}, duplicates={duplicates}, skipped={skipped}.",
            )
        log_verbose(
            config.verbose,
            f"Topic '{topic.name}' now has {len(entries_by_topic[topic.name])} items.",
        )
    log_verbose(
        config.verbose,
        f"Finished fetch. Sources checked: {stats.sources_checked}. "
        f"Paywalled excluded: {stats.paywalled}.",
    )
    return entries_by_topic, stats


def parse_feed(feed: FeedSource, config: DailyPaperConfig) -> feedparser.FeedParserDict:
    try:
        response = requests.get(feed.url, timeout=15, headers=DEFAULT_HEADERS)
    except requests.RequestException as exc:
        log_verbose(config.verbose, f"Feed request failed for {feed.name}: {exc}")
        return feedparser.parse(feed.url)

    if not response.ok or not response.content:
        log_verbose(
            config.verbose,
            f"Feed request returned status {response.status_code} for {feed.name}",
        )
        return feedparser.parse(feed.url)

    parsed = feedparser.parse(response.content)
    if parsed.entries or not parsed.bozo:
        return parsed

    log_verbose(config.verbose, f"Feed parse fallback for {feed.name}")
    return feedparser.parse(feed.url)


def fetch_full_text(entry: FeedEntry, config: DailyPaperConfig) -> tuple[str | None, bool]:
    try:
        response = requests.get(entry.link, timeout=15, headers=DEFAULT_HEADERS)
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
