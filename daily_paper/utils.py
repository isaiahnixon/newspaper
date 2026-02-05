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
CONTENT_SIMILARITY_CHARS = 600


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    # Most publishers serve the same article over http/https.
    # Force a single scheme so those URLs collapse during dedupe.
    scheme = "https" if parsed.scheme in {"", "http", "https"} else parsed.scheme
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
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    return _token_sequence_similarity(left_norm, right_norm)


def text_similarity(left: str, right: str) -> float:
    """Similarity for longer fields like summaries or extracted content."""
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    return _token_sequence_similarity(left_norm, right_norm)


def weighted_story_similarity(
    title_left: str,
    title_right: str,
    summary_left: str,
    summary_right: str,
    content_left: str | None,
    content_right: str | None,
) -> float:
    """Combine available fields so missing text does not suppress strong title matches."""
    weighted_scores: list[tuple[float, float]] = []

    title_score = title_similarity(title_left, title_right)
    weighted_scores.append((title_score, 0.50))

    if summary_left.strip() and summary_right.strip():
        summary_score = text_similarity(summary_left, summary_right)
        weighted_scores.append((summary_score, 0.50))

    if content_left and content_right:
        content_score = text_similarity(
            content_left[:CONTENT_SIMILARITY_CHARS],
            content_right[:CONTENT_SIMILARITY_CHARS],
        )
        weighted_scores.append((content_score, 0.10))

    total_weight = sum(weight for _, weight in weighted_scores)
    if total_weight == 0:
        return 0.0
    weighted_total = sum(score * weight for score, weight in weighted_scores)
    return weighted_total / total_weight


def extract_comparison_metadata(text: str) -> set[str]:
    """Capture language-agnostic anchors helpful for translation-aware matching."""
    if not text:
        return set()
    metadata: set[str] = set()
    metadata.update(re.findall(r"\b\d+(?:[.,]\d+)?\b", text))
    metadata.update(re.findall(r"\b\d{4}-\d{1,2}-\d{1,2}\b", text))
    metadata.update(re.findall(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", text))
    metadata.update(re.findall(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*\b", text))
    return {item.strip().lower() for item in metadata if item.strip()}


def metadata_overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _is_tracking_param(key: str) -> bool:
    lowered = key.lower()
    return lowered.startswith(TRACKING_PREFIXES) or lowered in TRACKING_PARAMS


def _normalize_text(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _token_sequence_similarity(left_norm: str, right_norm: str) -> float:
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    overlap = len(left_tokens & right_tokens) / max(
        1, min(len(left_tokens), len(right_tokens))
    )
    ratio = difflib.SequenceMatcher(None, left_norm, right_norm).ratio()
    return max(overlap, ratio)


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
