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
    model: str = "gpt-5-mini"
    # Item summaries are short headline-style rewrites; use a cheaper model by default.
    item_model: str | None = None
    # Topic summaries are longer and higher-level; keep a stronger model by default.
    topic_model: str | None = None
    temperature: float | None = None
    verbose: bool = False
    topics: tuple[TopicConfig, ...] = field(default_factory=tuple)

    @property
    def output_path(self) -> Path:
        return self.output_dir / self.output_file

    def resolve_item_model(self) -> str:
        """Resolve the model for item summaries while honoring config overrides."""
        if (
            self.model != DEFAULT_CONFIG.model
            and self.item_model == DEFAULT_CONFIG.item_model
        ):
            return self.model
        return self.item_model or self.model

    def resolve_topic_model(self) -> str:
        """Resolve the model for topic summaries while honoring config overrides."""
        if (
            self.model != DEFAULT_CONFIG.model
            and self.topic_model == DEFAULT_CONFIG.topic_model
        ):
            return self.model
        return self.topic_model or self.model

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
                FeedSource("IMF Blog", "https://www.imf.org/external/rss/feeds.aspx?category=blog"),
                FeedSource("World Bank Blogs", "https://blogs.worldbank.org/rss"),
                FeedSource("OECD Newsroom", "https://www.oecd.org/newsroom/oecdnews.xml"),
            ),
        ),
        TopicConfig(
            name="Political News",
            feeds=(
                FeedSource("Brookings", "https://www.brookings.edu/feed/"),
                FeedSource("Council on Foreign Relations", "https://www.cfr.org/rss/rss.xml"),
                FeedSource("U.S. State Department", "https://www.state.gov/rss-feed/"),
            ),
        ),
    )
)
