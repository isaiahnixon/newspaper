from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .config import DailyPaperConfig
from .summarize import SummarizedItem, TopicSummary
from .utils import format_published


@dataclass
class RenderContext:
    config: DailyPaperConfig
    generated_at: datetime
    sources_checked: int
    paywalled_excluded: int
    topic_summaries: dict[str, TopicSummary]
    items_by_topic: dict[str, list[SummarizedItem]]


def render_html(context: RenderContext) -> str:
    config = context.config
    toc_items = "\n".join(
        f'<li><a href="#{slugify(topic)}">{topic}</a></li>'
        for topic in context.items_by_topic
    )

    sections = "\n".join(
        render_topic_section(
            topic,
            context.topic_summaries.get(topic),
            context.items_by_topic.get(topic, []),
            config,
        )
        for topic in context.items_by_topic
    )

    footer = (
        f"Generated {context.generated_at.strftime('%Y-%m-%d %H:%M:%S')} "
        f"local time. Sources checked: {context.sources_checked}. "
        f"Paywalled items excluded: {context.paywalled_excluded}. "
        f"<a href=\"archive/\">Archive</a>."
    )

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Daily AI Newspaper</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.6; max-width: 920px; }}
    h1 {{ margin-bottom: 0.25rem; }}
    nav ul {{ list-style: none; padding: 0; }}
    nav li {{ margin: 0.25rem 0; }}
    section {{ margin-top: 2.5rem; }}
    .item {{ margin-bottom: 1.25rem; }}
    .meta {{ color: #555; font-size: 0.9rem; }}
    .title {{ color: #666; font-size: 0.9rem; }}
    footer {{ margin-top: 3rem; font-size: 0.9rem; color: #444; }}
  </style>
</head>
<body>
  <header>
    <h1>Daily AI Newspaper</h1>
    <p>Text-first daily briefing with neutral summaries.</p>
  </header>
  <nav>
    <h2>Table of Contents</h2>
    <ul>
      {toc_items}
    </ul>
  </nav>
  {sections}
  <footer>
    {footer}
  </footer>
</body>
</html>"""


def render_topic_section(
    topic: str,
    summary: TopicSummary | None,
    items: Iterable[SummarizedItem],
    config: DailyPaperConfig,
) -> str:
    summary_html = f"<p>{summary.summary}</p>" if summary else "<p>No summary available.</p>"

    items_html = "\n".join(
        render_item(item, config.show_titles) for item in items
    )

    return f"""
<section id=\"{slugify(topic)}\">
  <h2>{topic}</h2>
  {summary_html}
  <div>
    {items_html}
  </div>
</section>
"""


def render_item(item: SummarizedItem, show_title: bool) -> str:
    entry = item.entry
    published = format_published(parse_iso(entry.published))
    meta_parts = [entry.source]
    if published:
        meta_parts.append(published)
    meta = " · ".join(meta_parts)

    title_html = f"<div class=\"title\">{entry.title}</div>" if show_title else ""

    return f"""
<div class=\"item\">
  <div>{item.summary}</div>
  <div class=\"meta\">{meta} · <a href=\"{entry.link}\">Source</a></div>
  {title_html}
</div>
"""


def parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def slugify(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")
