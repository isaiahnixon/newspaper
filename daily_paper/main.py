from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .archive import archive_existing
from .config import DEFAULT_CONFIG, DailyPaperConfig
from .fetch import fetch_feeds
from .render import RenderContext, render_html
from .summarize import summarize_items, summarize_topic


def run(config: DailyPaperConfig = DEFAULT_CONFIG) -> Path:
    entries_by_topic, stats = fetch_feeds(config)

    summarized_by_topic = {}
    topic_summaries = {}

    for topic, entries in entries_by_topic.items():
        entries = entries[: config.items_per_topic]
        summarized_items = summarize_items(config, entries)
        summarized_by_topic[topic] = summarized_items
        if summarized_items:
            topic_summaries[topic] = summarize_topic(config, topic, summarized_items)

    context = RenderContext(
        config=config,
        generated_at=datetime.now(),
        sources_checked=stats.sources_checked,
        paywalled_excluded=stats.paywalled,
        topic_summaries=topic_summaries,
        items_by_topic=summarized_by_topic,
    )

    if config.no_visuals:
        html = render_html(context)
    else:
        html = render_html(context)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    archive_existing(config.output_path, config.archive_dir)
    config.output_path.write_text(html, encoding="utf-8")
    return config.output_path


if __name__ == "__main__":
    run()
