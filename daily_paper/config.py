from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import yaml


CONFIG_PATH = Path("daily_paper.yaml")

WEEKDAY_INDEX_BY_NAME = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}


@dataclass(frozen=True)
class FeedSource:
    name: str
    url: str
    source_group: str | None = None


@dataclass(frozen=True)
class TopicConfig:
    name: str
    lookback_hours: int
    feeds: tuple[FeedSource, ...]
    items_per_topic: int
    frequency_days: tuple[int, ...] | None = None

    def runs_on_weekday(self, weekday: int) -> bool:
        if self.frequency_days is None:
            return True
        return weekday in self.frequency_days


@dataclass(frozen=True)
class DailyPaperConfig:
    # Publish the latest edition directly to the repository root.
    output_dir: Path
    output_file: str
    # Keep historical editions in a dedicated root-level archive folder.
    archive_dir: Path
    fetch_full_text: bool
    max_full_text_chars: int
    items_per_topic: int
    max_items_processed_per_source: int
    # Explicitly set models so the config is the single source of truth.
    item_model: str
    selection_model: str
    topic_model: str
    topic_summary_max_retries: int
    temperature: float | None
    # Use dry_run to avoid network calls while testing prompts safely.
    dry_run: bool
    verbose: bool
    # OpenAI request behavior: keep in config so it's easy to audit and tune.
    openai_timeout_secs: float
    openai_max_retries: int
    openai_retry_backoff_secs: float
    openai_retry_on_timeout: bool
    max_items_per_source: int | None
    topics: tuple[TopicConfig, ...]

    @property
    def output_path(self) -> Path:
        return self.output_dir / self.output_file

    def iter_feeds(self) -> Iterable[FeedSource]:
        for topic in self.topics:
            yield from topic.feeds

    def get_topic_config(self, name: str) -> TopicConfig:
        for topic in self.topics:
            if topic.name == name:
                return topic
        raise KeyError(f"Unknown topic: {name}")

    def active_topics(self, now: datetime | None = None) -> tuple[TopicConfig, ...]:
        current_time = now or datetime.now(timezone.utc)
        weekday = current_time.weekday()
        return tuple(topic for topic in self.topics if topic.runs_on_weekday(weekday))


def load_config(path: Path = CONFIG_PATH) -> DailyPaperConfig:
    """Load configuration from YAML and fail fast on missing or invalid values."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("Config file must contain a YAML mapping at the top level.")

    # Require every key so missing values are surfaced immediately.
    required_keys = {
        "output_dir",
        "output_file",
        "archive_dir",
        "fetch_full_text",
        "max_full_text_chars",
        "items_per_topic",
        "item_model",
        "selection_model",
        "topic_model",
        "topic_summary_max_retries",
        "temperature",
        "dry_run",
        "verbose",
        "openai_timeout_secs",
        "openai_max_retries",
        "openai_retry_backoff_secs",
        "openai_retry_on_timeout",
        "topics",
    }
    missing = sorted(key for key in required_keys if key not in data)
    if missing:
        raise ValueError(f"Missing required config keys: {', '.join(missing)}")

    output_dir = _require_path(data, "output_dir")
    output_file = _require_str(data, "output_file")
    archive_dir = _require_path(data, "archive_dir")
    fetch_full_text = _require_bool(data, "fetch_full_text")
    max_full_text_chars = _require_int(data, "max_full_text_chars")
    items_per_topic = _require_int(data, "items_per_topic")
    max_items_processed_per_source = _require_optional_int(
        data,
        "max_items_processed_per_source",
        50,
    )
    item_model = _require_str(data, "item_model")
    selection_model = _require_str(data, "selection_model")
    topic_model = _require_str(data, "topic_model")
    topic_summary_max_retries = _require_int(data, "topic_summary_max_retries")
    if topic_summary_max_retries < 1:
        raise ValueError("Config key 'topic_summary_max_retries' must be at least 1.")
    temperature = _require_optional_float(data, "temperature")
    dry_run = _require_bool(data, "dry_run")
    verbose = _require_bool(data, "verbose")
    openai_timeout_secs = _require_float(data, "openai_timeout_secs")
    openai_max_retries = _require_int(data, "openai_max_retries")
    openai_retry_backoff_secs = _require_float(data, "openai_retry_backoff_secs")
    openai_retry_on_timeout = _require_bool(data, "openai_retry_on_timeout")
    max_items_per_source = _require_optional_int_or_none(data, "max_items_per_source")
    topics = _require_topics(data.get("topics"), items_per_topic)

    return DailyPaperConfig(
        output_dir=output_dir,
        output_file=output_file,
        archive_dir=archive_dir,
        fetch_full_text=fetch_full_text,
        max_full_text_chars=max_full_text_chars,
        items_per_topic=items_per_topic,
        max_items_processed_per_source=max_items_processed_per_source,
        item_model=item_model,
        selection_model=selection_model,
        topic_model=topic_model,
        topic_summary_max_retries=topic_summary_max_retries,
        temperature=temperature,
        dry_run=dry_run,
        verbose=verbose,
        openai_timeout_secs=openai_timeout_secs,
        openai_max_retries=openai_max_retries,
        openai_retry_backoff_secs=openai_retry_backoff_secs,
        openai_retry_on_timeout=openai_retry_on_timeout,
        max_items_per_source=max_items_per_source,
        topics=topics,
    )


def _require_path(data: Mapping[str, object], key: str) -> Path:
    value = _require_str(data, key)
    return Path(value)


def _require_str(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Config key '{key}' must be a non-empty string.")
    return value


def _require_bool(data: Mapping[str, object], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Config key '{key}' must be a boolean.")
    return value


def _require_int(data: Mapping[str, object], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Config key '{key}' must be an integer.")
    return value


def _require_float(data: Mapping[str, object], key: str) -> float:
    value = data.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Config key '{key}' must be a number.")
    return float(value)


def _require_optional_float(data: Mapping[str, object], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Config key '{key}' must be a number or null.")
    return float(value)


def _require_topics(
    value: object,
    default_items_per_topic: int,
) -> tuple[TopicConfig, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("Config key 'topics' must be a list of topics.")

    topics: list[TopicConfig] = []
    for idx, raw_topic in enumerate(value, start=1):
        if not isinstance(raw_topic, Mapping):
            raise ValueError(f"Topic entry {idx} must be a mapping.")
        name = raw_topic.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Each topic must include a non-empty 'name'.")
        lookback_hours = _require_int(raw_topic, "lookback_hours")
        items_per_topic = _require_optional_int(
            raw_topic,
            "items_per_topic",
            default_items_per_topic,
        )
        frequency_days = _require_optional_frequency_days(raw_topic, name)
        feeds = _require_feeds(raw_topic.get("feeds"), name)
        topics.append(
            TopicConfig(
                name=name,
                lookback_hours=lookback_hours,
                feeds=feeds,
                items_per_topic=items_per_topic,
                frequency_days=frequency_days,
            )
        )
    return tuple(topics)


def _require_optional_frequency_days(
    data: Mapping[str, object],
    topic_name: str,
) -> tuple[int, ...] | None:
    value = data.get("frequency_days")
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(
            f"Topic '{topic_name}' key 'frequency_days' must be a list of weekday names."
        )
    weekdays: list[int] = []
    for idx, raw_day in enumerate(value, start=1):
        if not isinstance(raw_day, str) or not raw_day.strip():
            raise ValueError(
                f"Topic '{topic_name}' has invalid weekday at frequency_days[{idx}]."
            )
        normalized = raw_day.strip().lower()
        weekday = WEEKDAY_INDEX_BY_NAME.get(normalized)
        if weekday is None:
            raise ValueError(
                f"Topic '{topic_name}' has unsupported weekday '{raw_day}' in 'frequency_days'."
            )
        weekdays.append(weekday)
    if not weekdays:
        raise ValueError(f"Topic '{topic_name}' key 'frequency_days' cannot be empty.")
    return tuple(sorted(set(weekdays)))


def _require_optional_int(
    data: Mapping[str, object],
    key: str,
    default: int,
) -> int:
    value = data.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Config key '{key}' must be an integer.")
    return value


def _require_optional_int_or_none(
    data: Mapping[str, object],
    key: str,
) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Config key '{key}' must be an integer or null.")
    if value < 1:
        raise ValueError(f"Config key '{key}' must be at least 1 when provided.")
    return value


def _require_feeds(value: object, topic_name: str) -> tuple[FeedSource, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"Topic '{topic_name}' must include a list of feeds.")

    feeds: list[FeedSource] = []
    for idx, raw_feed in enumerate(value, start=1):
        if not isinstance(raw_feed, Mapping):
            raise ValueError(
                f"Feed entry {idx} in topic '{topic_name}' must be a mapping."
            )
        name = raw_feed.get("name")
        url = raw_feed.get("url")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"Feed entry {idx} in topic '{topic_name}' needs a non-empty 'name'."
            )
        if not isinstance(url, str) or not url.strip():
            raise ValueError(
                f"Feed entry {idx} in topic '{topic_name}' needs a non-empty 'url'."
            )
        source_group = raw_feed.get("source_group")
        if source_group is not None and (
            not isinstance(source_group, str) or not source_group.strip()
        ):
            raise ValueError(
                f"Feed entry {idx} in topic '{topic_name}' has invalid 'source_group'."
            )
        feeds.append(FeedSource(name=name, url=url, source_group=source_group))
    return tuple(feeds)
