from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

UTM_PREFIXES = ("utm_", "ref", "source")


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith(UTM_PREFIXES)
    ]
    cleaned_query = urlencode(query_pairs)
    normalized = parsed._replace(query=cleaned_query, fragment="")
    return urlunparse(normalized)


def format_published(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.strftime("%Y-%m-%d")


def parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def is_within_hours(published: datetime | None, now: datetime, max_age_hours: int) -> bool:
    """Return True when the published datetime is within the max age window."""
    if not published:
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return published >= now - timedelta(hours=max_age_hours)


def compact_text(parts: Iterable[str], max_chars: int) -> str:
    combined = "\n".join(part.strip() for part in parts if part).strip()
    combined = re.sub(r"\s+", " ", combined)
    if len(combined) <= max_chars:
        return combined
    return combined[: max_chars - 1].rstrip() + "…"


def log_verbose(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[daily_paper] {message}", flush=True)
