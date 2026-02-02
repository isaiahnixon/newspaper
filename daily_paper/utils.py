from __future__ import annotations

import difflib
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = {
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
    "spm",
}


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    hostname = (parsed.hostname or "").lower()
    netloc = hostname
    if parsed.port and parsed.port not in {80, 443}:
        netloc = f"{hostname}:{parsed.port}"
    path = parsed.path or "/"
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_tracking_param(key)
    ]
    cleaned_query = urlencode(query_pairs)
    normalized = parsed._replace(
        scheme=scheme, netloc=netloc, path=path, query=cleaned_query, fragment=""
    )
    return urlunparse(normalized)


def get_hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def title_similarity(left: str, right: str) -> float:
    left_norm = _normalize_title(left)
    right_norm = _normalize_title(right)
    if not left_norm or not right_norm:
        return 0.0
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    overlap = len(left_tokens & right_tokens) / max(
        1, min(len(left_tokens), len(right_tokens))
    )
    ratio = difflib.SequenceMatcher(None, left_norm, right_norm).ratio()
    return max(overlap, ratio)


def _is_tracking_param(key: str) -> bool:
    lowered = key.lower()
    return lowered.startswith(TRACKING_PREFIXES) or lowered in TRACKING_PARAMS


def _normalize_title(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


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


def get_env(key: str) -> str | None:
    """Small wrapper to keep environment access in one place."""
    return os.getenv(key)


def env_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
