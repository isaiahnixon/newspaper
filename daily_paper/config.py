from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class FeedSource:
    name: str
    url: str


@dataclass(frozen=True)
class TopicConfig:
    name: str
    feeds: tuple[FeedSource, ...]


@dataclass(frozen=True)
class DailyPaperConfig:
    output_dir: Path = Path("public")
    output_file: str = "index.html"
    archive_dir: Path = Path("public/archive")
    no_visuals: bool = True
    show_titles: bool = True
    fetch_full_text: bool = False
    max_full_text_chars: int = 2000
    items_per_topic: int = 8
    model: str = "gpt-5-nano"
    # Item summaries are short headline-style rewrites; use a cheaper model by default.
    item_model: str | None = None
    # Topic summaries are longer and higher-level; keep a stronger model by default.
    topic_model: str = "gpt-5-mini"
    temperature: float | None = None
    verbose: bool = False
    topics: tuple[TopicConfig, ...] = field(default_factory=tuple)

    @property
    def output_path(self) -> Path:
        return self.output_dir / self.output_file

    def resolve_item_model(self) -> str:
        """Resolve the model for item summaries while honoring config overrides."""
        if self.item_model is None:
            return self.model
        return self.item_model

    def resolve_topic_model(self) -> str:
        """Resolve the model for topic summaries while honoring config overrides."""
        if self.topic_model is None:
            return self.model
        return self.topic_model

    def iter_feeds(self) -> Iterable[FeedSource]:
        for topic in self.topics:
            yield from topic.feeds


DEFAULT_CONFIG = DailyPaperConfig(
    item_model="gpt-5-nano",
    topic_model="gpt-5-mini",
    topics=(
        TopicConfig(
            name="Artificial Intelligence",
            feeds=(
                FeedSource("OpenAI Blog", "https://openai.com/blog/rss"),
                FeedSource("Google AI Blog", "https://ai.googleblog.com/feeds/posts/default"),
                FeedSource("Hugging Face", "https://huggingface.co/blog/feed.xml"),
            ),
        ),
        TopicConfig(
            name="Web Tech News",
            feeds=(
                FeedSource("Mozilla Hacks", "https://hacks.mozilla.org/feed/"),
                FeedSource("Web.dev", "https://web.dev/feed.xml"),
                FeedSource("Chromium Blog", "https://blog.chromium.org/feeds/posts/default"),
            ),
        ),
        TopicConfig(
            name="Economic News",
            feeds=(
                # Prioritize official, non-paywalled economic releases for neutral coverage.
                FeedSource("U.S. Bureau of Labor Statistics Releases", "https://www.bls.gov/feed/bls_latest.rss"),
                FeedSource("Federal Reserve Press Releases", "https://www.federalreserve.gov/feeds/press_all.xml"),
                FeedSource("European Central Bank Press Releases", "https://www.ecb.europa.eu/rss/press.html"),
            ),
        ),
        TopicConfig(
            name="Political News",
            feeds=(
                FeedSource("United Nations News", "https://news.un.org/feed/subscribe/en/news/all/rss.xml"),
                FeedSource("U.S. State Dept. Press Releases", "https://www.state.gov/feeds/press-releases/"),
                FeedSource("European Parliament News", "https://www.europarl.europa.eu/rss/doc/news/en.xml"),
            ),
        ),
    )
)
