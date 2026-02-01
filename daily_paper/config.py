from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class FeedSource:
    name: str
    url: str
    category: str | None = None


@dataclass(frozen=True)
class TopicConfig:
    name: str
    feeds: tuple[FeedSource, ...]


@dataclass(frozen=True)
class DailyPaperConfig:
    # Publish the latest edition directly to the repository root.
    output_dir: Path = Path(".")
    output_file: str = "index.html"
    # Keep historical editions in a dedicated root-level archive folder.
    archive_dir: Path = Path("archive")
    no_visuals: bool = True
    show_titles: bool = True
    fetch_full_text: bool = False
    max_full_text_chars: int = 2000
    items_per_topic: int = 8
    model: str = "gpt-5-nano"
    # Item summaries are short headline-style rewrites; use a cheaper model by default.
    item_model: str | None = None
    # Topic summaries are longer and higher-level; keep a stronger model by default.
    topic_model: str | None = None
    temperature: float | None = None
    verbose: bool = False
    # OpenAI request behavior: keep in config so it's easy to audit and tune.
    openai_timeout_secs: float = 180.00
    openai_max_retries: int = 1
    openai_retry_backoff_secs: float = 1.0
    openai_retry_on_timeout: bool = False
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
            name="Tech News",
            feeds=(
                FeedSource("OpenAI Blog", "https://openai.com/blog/rss", category="AI"),
                FeedSource(
                    "Google AI Blog",
                    "https://ai.googleblog.com/feeds/posts/default",
                    category="AI",
                ),
                FeedSource("Hugging Face", "https://huggingface.co/blog/feed.xml", category="AI"),
                FeedSource("DeepMind Blog", "https://deepmind.google/blog/rss.xml", category="AI"),
                FeedSource("Meta AI Blog", "https://ai.facebook.com/blog/rss/", category="AI"),
                FeedSource(
                    "Microsoft Research Blog",
                    "https://www.microsoft.com/en-us/research/feed/",
                    category="AI",
                ),
                FeedSource("Ars Technica (AI)", "https://arstechnica.com/ai/feed/", category="AI"),
                FeedSource("arXiv cs.AI", "https://rss.arxiv.org/rss/cs.AI", category="AI"),
                FeedSource("arXiv cs.LG", "https://rss.arxiv.org/rss/cs.LG", category="AI"),
                FeedSource(
                    "NVIDIA Developer Blog",
                    "https://developer.nvidia.com/blog/feed",
                    category="AI",
                ),
                FeedSource("Mozilla Hacks", "https://hacks.mozilla.org/feed/", category="Web"),
                FeedSource("Web.dev", "https://web.dev/feed.xml", category="Web"),
                FeedSource(
                    "Chromium Blog",
                    "https://blog.chromium.org/feeds/posts/default",
                    category="Web",
                ),
                FeedSource("W3C News", "https://www.w3.org/blog/news/feed/", category="Web"),
                FeedSource("CSS-Tricks", "https://css-tricks.com/feed/", category="Web"),
                FeedSource(
                    "Smashing Magazine",
                    "https://www.smashingmagazine.com/feed/",
                    category="Web",
                ),
                FeedSource(
                    "Cloudflare Changelog (All)",
                    "https://developers.cloudflare.com/changelog/rss/index.xml",
                    category="Web",
                ),
                FeedSource(
                    "Cloudflare Changelog (App Security)",
                    "https://developers.cloudflare.com/changelog/rss/application-security.xml",
                    category="Web",
                ),
                FeedSource("V8 Blog (Atom)", "https://v8.dev/blog.atom", category="Web"),
                FeedSource(
                    "Google Security Blog",
                    "https://security.googleblog.com/feeds/posts/default",
                    category="Web",
                ),
            ),
        ),
        TopicConfig(
            name="Economic News",
            feeds=(
                # Prioritize official, non-paywalled economic releases for neutral coverage.
                FeedSource("U.S. Bureau of Labor Statistics Releases", "https://www.bls.gov/feed/bls_latest.rss"),
                FeedSource("Federal Reserve Press Releases", "https://www.federalreserve.gov/feeds/press_all.xml"),
                FeedSource("European Central Bank Press Releases", "https://www.ecb.europa.eu/rss/press.html"),
                FeedSource("International Monetary Fund News", "https://www.imf.org/en/News/RSS"),
                FeedSource("OECD Newsroom", "https://www.oecd.org/newsroom/rss.xml"),
                FeedSource("U.S. Treasury Press Releases", "https://home.treasury.gov/rss/press-releases.xml"),
                FeedSource("BEA News Releases", "https://apps.bea.gov/rss/rss.xml"),
                FeedSource("US Census Newsroom", "https://www.census.gov/newsroom/rss.xml"),
                FeedSource("US Census Economic Indicators", "https://www.census.gov/economic-indicators/rss.xml"),
                FeedSource("BIS Press Releases", "https://www.bis.org/doclist/all_pressrels.rss"),
                FeedSource("BIS Statistical Releases", "https://www.bis.org/doclist/all_statistics.rss"),
            ),
        ),
        TopicConfig(
            name="U.S. Governance",
            feeds=(
                FeedSource("U.S. State Dept. Press Releases", "https://www.state.gov/feeds/press-releases/"),
                FeedSource("White House Briefing Room", "https://www.whitehouse.gov/briefing-room/feed/"),
                FeedSource("PBS NewsHour - Politics", "https://www.pbs.org/newshour/feeds/rss/politics"),
                FeedSource("NPR - Politics", "https://feeds.npr.org/1014/rss.xml"),
            ),
        ),
        TopicConfig(
            name="Global Affairs",
            feeds=(
                FeedSource("United Nations News", "https://news.un.org/feed/subscribe/en/news/all/rss.xml"),
                FeedSource("European Parliament News", "https://www.europarl.europa.eu/rss/doc/news/en.xml"),
                FeedSource("NATO News", "https://www.nato.int/cps/en/natohq/news_rss.htm"),
                FeedSource("UK Parliament News", "https://www.parliament.uk/rss/news-feed/"),
                FeedSource(
                    "BBC - UK Politics",
                    "http://newsrss.bbc.co.uk/rss/newsonline_uk_edition/uk_politics/rss.xml",
                ),
            ),
        ),
    )
)
