from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Any

import feedparser
from feedparser import FeedParserDict  # Import FeedParserDict
import requests
from bs4 import BeautifulSoup

from .config import DailyPaperConfig, FeedSource
from .utils import (
    compact_text,
    extract_comparison_metadata,
    get_hostname,
    is_within_hours,
    log_verbose,
    metadata_overlap_ratio,
    normalize_url,
    parse_published,
    weighted_story_similarity,
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
    source_group: str
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
    metadata: set[str]


def fetch_feeds(config: DailyPaperConfig) -> tuple[dict[str, list[FeedEntry]], FetchStats]:
    seen_urls: set[str] = set()
    seen_entries: list[SeenEntry] = []
    stats = FetchStats()
    now = datetime.now(timezone.utc)
    active_topics = config.active_topics(now)
    entries_by_topic: dict[str, list[FeedEntry]] = {topic.name: [] for topic in active_topics}
    inactive_topic_names = [
        topic.name for topic in config.topics if topic.name not in entries_by_topic
    ]
    if inactive_topic_names:
        log_verbose(
            config.verbose,
            "Skipping topics for "
            f"{now.strftime('%A')} (UTC) due to frequency_days: "
            f"{', '.join(inactive_topic_names)}.",
        )
    if not active_topics:
        log_verbose(config.verbose, "No active topics scheduled for this run.")
        return entries_by_topic, stats
    # Keep enough seen entries to honor the largest per-topic lookback window.
    max_lookback_hours = max(topic.lookback_hours for topic in active_topics)

    log_verbose(config.verbose, "Starting feed fetch.")
    for topic in active_topics:
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
            max_feed_items = config.max_items_processed_per_source
            for idx, entry in enumerate(parsed.entries, start=1):
                if idx > max_feed_items:
                    break
                link = str(entry.get("link"))
                title = str(entry.get("title", "")).strip()
                if not link or not title:
                    skipped += 1
                    continue
                normalized = normalize_url(link)
                published = entry.get("published") or entry.get("updated")
                published_dt = parse_published(published)
                # Only keep entries from the topic's window to keep the paper timely.
                if not config.dry_run and not is_within_hours(published_dt, now, topic_lookback_hours):
                    out_of_window += 1
                    continue
                summary = str(entry.get("summary", ""))
                item = FeedEntry(
                    topic=topic.name,
                    title=title,
                    link=normalized,
                    published=published_dt.isoformat() if published_dt else "",
                    source=entry.get("source", {}).get("title") or feed.name,
                    feed_name=feed.name,
                    source_group=feed.source_group or feed.name,
                    summary=summary,
                )
                if config.fetch_full_text:
                    item.full_text = fetch_full_text(item, config)
                action = _register_entry(
                    config=config,
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
                f"processed={min(len(parsed.entries), max_feed_items)}, "
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
    config: DailyPaperConfig,
    entries_by_topic: dict[str, list[FeedEntry]],
    seen_urls: set[str],
    seen_entries: list[SeenEntry],
    item: FeedEntry,
    published_dt: datetime | None,
    now: datetime,
    compare_window_hours: int,
    prune_window_hours: int,
) -> str:
    if config.dry_run:
        # In dry-run mode, skip deduplication and just add the item.
        entries_by_topic[item.topic].append(item)
        log_verbose(config.verbose, f"[dry run] Added item '{item.title}' to topic '{item.topic}'.")
        return "added"

    _prune_seen_entries(seen_entries, now, prune_window_hours)
    hostname = get_hostname(item.link)
    metadata = _build_story_metadata(item)
    existing_by_url = _find_seen_by_url(seen_entries, item.link)
    # Canonical URL dedupe has highest confidence and happens before fuzzy matching.
    if existing_by_url:
        if _is_better_entry(item, existing_by_url.entry):
            _replace_entry(
                entries_by_topic,
                seen_urls,
                seen_entries,
                existing_by_url,
                item,
                published_dt,
                metadata,
            )
            return "replaced"
        return "skipped"
    if item.link in seen_urls:
        return "skipped"
    near_match = _find_near_duplicate(
        seen_entries,
        item,
        hostname,
        published_dt,
        compare_window_hours,
        metadata,
    )
    if near_match:
        if _is_better_entry(item, near_match.entry):
            _replace_entry(
                entries_by_topic,
                seen_urls,
                seen_entries,
                near_match,
                item,
                published_dt,
                metadata,
            )
            return "replaced"
        return "skipped"
    seen_urls.add(item.link)
    seen_entries.append(
        SeenEntry(
            entry=item,
            canonical_url=item.link,
            hostname=hostname,
            published=published_dt,
            metadata=metadata,
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
    metadata: set[str],
) -> None:
    if existing.entry in entries_by_topic.get(existing.entry.topic, []):
        entries_by_topic[existing.entry.topic].remove(existing.entry)
    seen_urls.discard(existing.canonical_url)
    existing.entry = replacement
    existing.canonical_url = replacement.link
    existing.hostname = get_hostname(replacement.link)
    existing.published = published_dt
    existing.metadata = metadata
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
    metadata: set[str],
    weighted_threshold: float = 0.82,
    translation_metadata_threshold: float = 0.65,
    translation_time_window_minutes: int = 180,
) -> SeenEntry | None:
    for seen in seen_entries:
        if seen.hostname != hostname:
            continue
        if not _within_recent_window(published_dt, seen.published, max_age_hours):
            continue
        weighted_similarity = weighted_story_similarity(
            item.title,
            seen.entry.title,
            item.summary,
            seen.entry.summary,
            item.full_text,
            seen.entry.full_text,
        )
        if weighted_similarity >= weighted_threshold:
            return seen
        if _is_translation_duplicate(
            current_published=published_dt,
            seen_published=seen.published,
            current_metadata=metadata,
            seen_metadata=seen.metadata,
            metadata_threshold=translation_metadata_threshold,
            max_minutes=translation_time_window_minutes,
        ):
            return seen
    return None


def _is_translation_duplicate(
    current_published: datetime | None,
    seen_published: datetime | None,
    current_metadata: set[str],
    seen_metadata: set[str],
    metadata_threshold: float,
    max_minutes: int,
) -> bool:
    """Detect likely translated reposts from the same source.

    Translation copies can have different wording, so this fallback relies on
    close publish time plus shared language-agnostic metadata such as
    entities, numbers, and date expressions.
    """
    if not _within_recent_minutes(current_published, seen_published, max_minutes):
        return False
    return metadata_overlap_ratio(current_metadata, seen_metadata) >= metadata_threshold


def _build_story_metadata(item: FeedEntry) -> set[str]:
    metadata_parts = [item.title, item.summary]
    if item.full_text:
        metadata_parts.append(item.full_text[:600])
    return extract_comparison_metadata("\n".join(part for part in metadata_parts if part))


def _within_recent_minutes(
    left: datetime | None, right: datetime | None, max_minutes: int
) -> bool:
    if not left or not right:
        return True
    return abs(left - right) <= timedelta(minutes=max_minutes)


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
    if config.dry_run:
        log_verbose(config.verbose, f"[dry run] Skipping feed request for {feed.name}.")
        # Return a dummy FeedParserDict with some placeholder entries.
        # This ensures the rest of the pipeline has some data to process.
        dummy_entries = [
            FeedParserDict({
                "title": f"[dry run] {feed.name} Item 1",
                "link": f"https://example.com/dry-run/{feed.name}/item1",
                "published": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                "summary": f"[dry run] Summary for {feed.name} item 1.",
                "source": {"title": feed.name},
            }),
            FeedParserDict({
                "title": f"[dry run] {feed.name} Item 2",
                "link": f"https://example.com/dry-run/{feed.name}/item2",
                "published": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
                "summary": f"[dry run] Summary for {feed.name} item 2.",
                "source": {"title": feed.name},
            }),
        ]
        return FeedParserDict({"entries": dummy_entries, "bozo": False})

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
    if config.dry_run:
        log_verbose(config.verbose, f"[dry run] Skipping full text fetch for {entry.title}.")
        return f"[dry run] Full text for {entry.title} (skipped in dry run)."

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
