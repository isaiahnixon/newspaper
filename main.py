#!/usr/bin/env python3
"""Generate a text-only daily news briefing HTML page."""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None  # type: ignore[assignment]

import feedparser

DEFAULT_CONFIG_PATH = "./config.json"
DEFAULT_TIMEOUT = 10


@dataclass(frozen=True)
class FeedItem:
    title: str
    link: str
    published: str
    summary: str
    source_domain: str


@dataclass(frozen=True)
class TopicConfig:
    name: str
    feeds: list[str]
    max_items: int


@dataclass(frozen=True)
class Settings:
    site_dir: str
    archive_dir: str
    timezone: str | None
    blocked_domains: set[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a daily news briefing HTML page.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to config JSON")
    return parser.parse_args()


def load_config(path: str) -> tuple[list[TopicConfig], Settings]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    topics_data = data.get("topics")
    settings_data = data.get("settings")
    if not isinstance(topics_data, list) or not isinstance(settings_data, dict):
        raise ValueError("Config must include 'topics' list and 'settings' object")

    topics: list[TopicConfig] = []
    for raw_topic in topics_data:
        if not isinstance(raw_topic, dict):
            raise ValueError("Each topic must be an object")
        name = raw_topic.get("name")
        feeds = raw_topic.get("feeds")
        max_items = raw_topic.get("max_items")
        if not isinstance(name, str) or not isinstance(feeds, list) or not isinstance(max_items, int):
            raise ValueError("Topic requires 'name' (str), 'feeds' (list), 'max_items' (int)")
        topics.append(TopicConfig(name=name, feeds=[str(feed) for feed in feeds], max_items=max_items))

    blocked_domains_raw = settings_data.get("blocked_domains", [])
    if not isinstance(blocked_domains_raw, list):
        raise ValueError("'blocked_domains' must be a list")

    settings = Settings(
        site_dir=str(settings_data.get("site_dir", "./site")),
        archive_dir=str(settings_data.get("archive_dir", "./site/archive")),
        timezone=settings_data.get("timezone"),
        blocked_domains={str(domain).lower() for domain in blocked_domains_raw},
    )

    return topics, settings


def resolve_timezone(tz_name: str | None) -> datetime.tzinfo | None:
    if not tz_name or ZoneInfo is None:
        return None
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logging.warning("Invalid timezone %s; using local time.", tz_name)
        return None


def fetch_feed(url: str) -> feedparser.FeedParserDict | None:
    request = Request(url, headers={"User-Agent": "DailyBriefingBot/1.0"})
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
            content = response.read()
        return feedparser.parse(content)
    except URLError as exc:
        logging.warning("Failed to fetch feed %s: %s", url, exc)
        return None
    except Exception as exc:
        logging.warning("Unexpected error fetching feed %s: %s", url, exc)
        return None


def extract_domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def is_blocked(domain: str, blocked_domains: set[str]) -> bool:
    domain = domain.lower()
    for blocked in blocked_domains:
        if domain == blocked or domain.endswith(f".{blocked}"):
            return True
    return False


def looks_paywalled(summary: str) -> bool:
    summary_lower = summary.lower()
    return "subscribe" in summary_lower and "sign in" in summary_lower


def build_items(feed_data: feedparser.FeedParserDict) -> Iterable[FeedItem]:
    for entry in feed_data.entries:
        title = str(entry.get("title", "")).strip()
        link = str(entry.get("link", "")).strip()
        if not link:
            continue
        published = str(entry.get("published", "")).strip()
        summary = str(entry.get("summary", "")).strip()
        source_domain = extract_domain(link)
        yield FeedItem(title=title, link=link, published=published, summary=summary, source_domain=source_domain)


def summarize_item(item: FeedItem) -> str:
    text = item.summary or item.title
    if not text:
        text = "Untitled item"
    if len(text) <= 240:
        return text
    truncated = text[:240]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated.rstrip() + "…"


def escape(text: str) -> str:
    return html.escape(text, quote=True)


def archive_existing(site_dir: str, archive_dir: str, timestamp: datetime) -> None:
    index_path = os.path.join(site_dir, "index.html")
    if not os.path.exists(index_path):
        return
    os.makedirs(archive_dir, exist_ok=True)
    stamp = timestamp.strftime("%Y-%m-%d_%H-%M-%S")
    archive_path = os.path.join(archive_dir, f"index_{stamp}.html")
    shutil.move(index_path, archive_path)


def render_html(
    topics: list[TopicConfig],
    items_by_topic: dict[str, list[FeedItem]],
    generated_at: datetime,
) -> str:
    timestamp = generated_at.strftime("%Y-%m-%d %H:%M:%S")
    sections = []
    for topic in topics:
        items = items_by_topic.get(topic.name, [])
        if not items:
            body = "<p>No accessible coverage found today.</p>"
        else:
            bullets = []
            for item in items:
                summary = escape(summarize_item(item))
                title = escape(item.title or item.link)
                domain = escape(item.source_domain or "unknown")
                link = escape(item.link)
                date = escape(item.published)
                date_display = f" <span class=\"date\">{date}</span>" if date else ""
                bullets.append(
                    f"<li><a href=\"{link}\">{summary}</a>"
                    f" <span class=\"source\">({domain})</span>{date_display}</li>"
                )
            body = "<ul>" + "".join(bullets) + "</ul>"
        sections.append(f"<section><h2>{escape(topic.name)}</h2>{body}</section>")

    content = "".join(sections)
    return (
        "<!DOCTYPE html>"
        "<html lang=\"en\">"
        "<head>"
        "<meta charset=\"utf-8\">"
        "<meta http-equiv=\"Content-Security-Policy\" "
        "content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
        "form-action 'none'; img-src 'none'; script-src 'none'; font-src 'none'; "
        "connect-src 'none'\">"
        "<title>Daily Briefing</title>"
        "<style>"
        "body{font-family:Arial, sans-serif; margin:32px; color:#111; background:#fff;}"
        "h1{margin-bottom:4px;}"
        "h2{margin-top:24px;}"
        "ul{padding-left:20px;}"
        "li{margin:8px 0;}"
        "a{color:#0b5394; text-decoration:none;}"
        "a:hover{text-decoration:underline;}"
        ".meta{color:#555; font-size:0.9em;}"
        ".source{color:#555;}"
        ".date{color:#777; font-size:0.85em;}"
        "footer{margin-top:32px; font-size:0.9em; color:#555;}"
        "</style>"
        "</head>"
        "<body>"
        f"<header><h1>Daily Briefing</h1><div class=\"meta\">Generated {escape(timestamp)}</div></header>"
        f"{content}"
        "<footer>Text-only. No paywalled sources. Generated locally.</footer>"
        "</body></html>"
    )


def collect_items(topics: list[TopicConfig], settings: Settings) -> dict[str, list[FeedItem]]:
    items_by_topic: dict[str, list[FeedItem]] = {topic.name: [] for topic in topics}
    seen_links: set[str] = set()

    for topic in topics:
        for feed_url in topic.feeds:
            feed_data = fetch_feed(feed_url)
            if feed_data is None:
                continue
            for item in build_items(feed_data):
                if not item.link:
                    continue
                link_key = item.link.strip()
                if link_key in seen_links:
                    continue
                if is_blocked(item.source_domain, settings.blocked_domains):
                    continue
                if looks_paywalled(item.summary):
                    continue
                seen_links.add(link_key)
                items_by_topic[topic.name].append(item)
                if len(items_by_topic[topic.name]) >= topic.max_items:
                    break

    return items_by_topic


def write_site(site_dir: str, html_content: str) -> None:
    os.makedirs(site_dir, exist_ok=True)
    output_path = os.path.join(site_dir, "index.html")
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(html_content)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    try:
        topics, settings = load_config(args.config)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        logging.error("Config error: %s", exc)
        return 1

    tzinfo = resolve_timezone(settings.timezone)
    now = datetime.now(tz=tzinfo)

    archive_existing(settings.site_dir, settings.archive_dir, now)
    items_by_topic = collect_items(topics, settings)
    html_content = render_html(topics, items_by_topic, now)
    write_site(settings.site_dir, html_content)

    logging.info("Wrote %s", os.path.join(settings.site_dir, "index.html"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
