from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import yaml


CONFIG_PATH = Path("daily_paper.yaml")


@dataclass(frozen=True)
class FeedSource:
    name: str
    url: str


@dataclass(frozen=True)
class TopicConfig:
    name: str
    lookback_hours: int
    feeds: tuple[FeedSource, ...]
    items_per_topic: int


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
    # Explicitly set models so the config is the single source of truth.
    item_model: str
    selection_model: str
    topic_model: str
    temperature: float | None
    # Use dry_run to avoid network calls while testing prompts safely.
    dry_run: bool
    verbose: bool
    # OpenAI request behavior: keep in config so it's easy to audit and tune.
    openai_timeout_secs: float
    openai_max_retries: int
    openai_retry_backoff_secs: float
    openai_retry_on_timeout: bool
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
    item_model = _require_str(data, "item_model")
    selection_model = _require_str(data, "selection_model")
    topic_model = _require_str(data, "topic_model")
    temperature = _require_optional_float(data, "temperature")
    dry_run = _require_bool(data, "dry_run")
    verbose = _require_bool(data, "verbose")
    openai_timeout_secs = _require_float(data, "openai_timeout_secs")
    openai_max_retries = _require_int(data, "openai_max_retries")
    openai_retry_backoff_secs = _require_float(data, "openai_retry_backoff_secs")
    openai_retry_on_timeout = _require_bool(data, "openai_retry_on_timeout")
    topics = _require_topics(data.get("topics"), items_per_topic)

    return DailyPaperConfig(
        output_dir=output_dir,
        output_file=output_file,
        archive_dir=archive_dir,
        fetch_full_text=fetch_full_text,
        max_full_text_chars=max_full_text_chars,
        items_per_topic=items_per_topic,
        item_model=item_model,
        selection_model=selection_model,
        topic_model=topic_model,
        temperature=temperature,
        dry_run=dry_run,
        verbose=verbose,
        openai_timeout_secs=openai_timeout_secs,
        openai_max_retries=openai_max_retries,
        openai_retry_backoff_secs=openai_retry_backoff_secs,
        openai_retry_on_timeout=openai_retry_on_timeout,
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
        feeds = _require_feeds(raw_topic.get("feeds"), name)
        topics.append(
            TopicConfig(
                name=name,
                lookback_hours=lookback_hours,
                feeds=feeds,
                items_per_topic=items_per_topic,
            )
        )
    return tuple(topics)


def _require_optional_int(
    data: Mapping[str, object],
    key: str,
    default: int,
) -> int:
    value = data.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Config key '{key}' must be an integer.")
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
        feeds.append(FeedSource(name=name, url=url))
    return tuple(feeds)
