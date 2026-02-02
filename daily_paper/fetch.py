from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

import feedparser
import requests
from bs4 import BeautifulSoup

from .config import DailyPaperConfig, FeedSource
from .utils import (
    compact_text,
    get_hostname,
    is_within_hours,
    log_verbose,
    normalize_url,
    parse_published,
    title_similarity,
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
    feed_name: str
    summary: str
    full_text: str | None = None


@dataclass
class FetchStats:
    sources_checked: int = 0
    no_result_sources: list[str] = field(default_factory=list)


class FetchError(RuntimeError):
    pass


@dataclass
class SeenEntry:
    entry: FeedEntry
    canonical_url: str
    hostname: str
    published: datetime | None


def fetch_feeds(config: DailyPaperConfig) -> tuple[dict[str, list[FeedEntry]], FetchStats]:
    entries_by_topic: dict[str, list[FeedEntry]] = {topic.name: [] for topic in config.topics}
    seen_urls: set[str] = set()
    seen_entries: list[SeenEntry] = []
    stats = FetchStats()
    now = datetime.now(timezone.utc)
    # Keep enough seen entries to honor the largest per-topic lookback window.
    max_lookback_hours = max(topic.lookback_hours for topic in config.topics)

    log_verbose(config.verbose, "Starting feed fetch.")
    for topic in config.topics:
        topic_lookback_hours = topic.lookback_hours
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
                stats.no_result_sources.append(feed.name)
                continue
            added = 0
            skipped = 0
            duplicates = 0
            out_of_window = 0
            for entry in parsed.entries:
                link = entry.get("link")
                title = entry.get("title", "").strip()
                if not link or not title:
                    skipped += 1
                    continue
                normalized = normalize_url(link)
                published = entry.get("published") or entry.get("updated")
                published_dt = parse_published(published)
                # Only keep entries from the topic's window to keep the paper timely.
                if not is_within_hours(published_dt, now, topic_lookback_hours):
                    out_of_window += 1
                    continue
                summary = entry.get("summary", "")
                item = FeedEntry(
                    topic=topic.name,
                    title=title,
                    link=normalized,
                    published=published_dt.isoformat() if published_dt else "",
                    source=entry.get("source", {}).get("title") or feed.name,
                    feed_name=feed.name,
                    summary=summary,
                )
                if config.fetch_full_text:
                    item.full_text = fetch_full_text(item, config)
                action = _register_entry(
                    entries_by_topic=entries_by_topic,
                    seen_urls=seen_urls,
                    seen_entries=seen_entries,
                    item=item,
                    published_dt=published_dt,
                    now=now,
                    compare_window_hours=topic_lookback_hours,
                    prune_window_hours=max_lookback_hours,
                )
                if action == "skipped":
                    duplicates += 1
                    continue
                if action == "added":
                    added += 1
                elif action == "replaced":
                    added += 1
                    duplicates += 1
            if added == 0:
                stats.no_result_sources.append(feed.name)
            log_verbose(
                config.verbose,
                f"Feed summary for {feed.name}: total={len(parsed.entries)}, "
                f"added={added}, duplicates={duplicates}, skipped={skipped}, "
                f"out_of_window={out_of_window}.",
            )
        log_verbose(
            config.verbose,
            f"Topic '{topic.name}' now has {len(entries_by_topic[topic.name])} items.",
        )
    log_verbose(
        config.verbose,
        f"Finished fetch. Sources checked: {stats.sources_checked}.",
    )
    return entries_by_topic, stats


def _register_entry(
    entries_by_topic: dict[str, list[FeedEntry]],
    seen_urls: set[str],
    seen_entries: list[SeenEntry],
    item: FeedEntry,
    published_dt: datetime | None,
    now: datetime,
    compare_window_hours: int,
    prune_window_hours: int,
) -> str:
    _prune_seen_entries(seen_entries, now, prune_window_hours)
    hostname = get_hostname(item.link)
    if item.link in seen_urls:
        existing = _find_seen_by_url(seen_entries, item.link)
        if existing and _is_better_entry(item, existing.entry):
            _replace_entry(entries_by_topic, seen_urls, seen_entries, existing, item, published_dt)
            return "replaced"
        return "skipped"
    near_match = _find_near_duplicate(
        seen_entries,
        item,
        hostname,
        published_dt,
        compare_window_hours,
    )
    if near_match:
        if _is_better_entry(item, near_match.entry):
            _replace_entry(entries_by_topic, seen_urls, seen_entries, near_match, item, published_dt)
            return "replaced"
        return "skipped"
    seen_urls.add(item.link)
    seen_entries.append(
        SeenEntry(
            entry=item,
            canonical_url=item.link,
            hostname=hostname,
            published=published_dt,
        )
    )
    entries_by_topic[item.topic].append(item)
    return "added"


def _replace_entry(
    entries_by_topic: dict[str, list[FeedEntry]],
    seen_urls: set[str],
    seen_entries: list[SeenEntry],
    existing: SeenEntry,
    replacement: FeedEntry,
    published_dt: datetime | None,
) -> None:
    if existing.entry in entries_by_topic.get(existing.entry.topic, []):
        entries_by_topic[existing.entry.topic].remove(existing.entry)
    seen_urls.discard(existing.canonical_url)
    existing.entry = replacement
    existing.canonical_url = replacement.link
    existing.hostname = get_hostname(replacement.link)
    existing.published = published_dt
    seen_urls.add(replacement.link)
    entries_by_topic[replacement.topic].append(replacement)


def _find_seen_by_url(seen_entries: list[SeenEntry], url: str) -> SeenEntry | None:
    for seen in seen_entries:
        if seen.canonical_url == url:
            return seen
    return None


def _find_near_duplicate(
    seen_entries: list[SeenEntry],
    item: FeedEntry,
    hostname: str,
    published_dt: datetime | None,
    max_age_hours: int,
    threshold: float = 0.86,
) -> SeenEntry | None:
    for seen in seen_entries:
        if seen.hostname != hostname:
            continue
        if not _within_recent_window(published_dt, seen.published, max_age_hours):
            continue
        if title_similarity(item.title, seen.entry.title) >= threshold:
            return seen
    return None


def _within_recent_window(
    left: datetime | None, right: datetime | None, max_age_hours: int
) -> bool:
    if not left or not right:
        return True
    return abs(left - right) <= timedelta(hours=max_age_hours)


def _prune_seen_entries(
    seen_entries: list[SeenEntry], now: datetime, max_age_hours: int
) -> None:
    cutoff = now - timedelta(hours=max_age_hours)
    seen_entries[:] = [
        seen for seen in seen_entries if not seen.published or seen.published >= cutoff
    ]


def _is_better_entry(candidate: FeedEntry, existing: FeedEntry) -> bool:
    return _entry_quality_score(candidate) > _entry_quality_score(existing)


def _entry_quality_score(entry: FeedEntry) -> float:
    score = 0.0
    if entry.published:
        score += 2.0
    summary = compact_text([entry.summary], 240)
    score += min(len(summary), 240) / 240
    return score


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


def fetch_full_text(entry: FeedEntry, config: DailyPaperConfig) -> str | None:
    try:
        response = requests.get(entry.link, timeout=15, headers=DEFAULT_HEADERS)
    except requests.RequestException:
        return None

    # Best-effort extraction: keep failures quiet so feeds remain resilient.

    html = response.text

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    article = soup.find("article") or soup.find("main") or soup.body
    if not article:
        return None

    paragraphs = [p.get_text(" ", strip=True) for p in article.find_all("p")]
    text = compact_text(paragraphs, config.max_full_text_chars)
    time.sleep(0.2)
    return text or None
