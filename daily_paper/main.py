from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .archive import archive_existing, write_archive_index
from .config import DailyPaperConfig, load_config
from .fetch import fetch_feeds
from .render import RenderContext, render_html
from .summarize import select_top_items, summarize_items, summarize_topic
from .utils import log_verbose


def run(config: DailyPaperConfig) -> Path:
    log_verbose(config.verbose, "Starting Daily Paper run.")
    entries_by_topic, stats = fetch_feeds(config)
    if stats.no_result_sources:
        missing_sources = ", ".join(sorted(set(stats.no_result_sources)))
        print(f"[daily_paper] Sources with no results: {missing_sources}", flush=True)

    summarized_by_topic = {}
    topic_summaries = {}

    for topic, entries in entries_by_topic.items():
        # Look up per-topic limits so each section can tune its own item count.
        topic_config = config.get_topic_config(topic)
        if not entries:
            log_verbose(config.verbose, f"No entries for '{topic}', skipping summarization.")
            summarized_by_topic[topic] = []
            continue
        # Respect the configured per-topic limit when selecting items for summarization.
        selected_entries = select_top_items(
            config,
            entries,
            topic=topic,
            limit=topic_config.items_per_topic,
        )
        summarized_items = summarize_items(config, selected_entries, topic=topic)
        summarized_by_topic[topic] = summarized_items
        if summarized_items:
            topic_summaries[topic] = summarize_topic(config, topic, summarized_items)
        else:
            log_verbose(config.verbose, f"No summarized items for '{topic}'.")

    context = RenderContext(
        config=config,
        generated_at=datetime.now(),
        sources_checked=stats.sources_checked,
        topic_summaries=topic_summaries,
        items_by_topic=summarized_by_topic,
    )

    log_verbose(config.verbose, "Rendering HTML output.")
    html = render_html(context)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    log_verbose(config.verbose, f"Archiving existing output to {config.archive_dir}.")
    archive_existing(config.output_path, config.archive_dir)
    log_verbose(config.verbose, f"Writing output to {config.output_path}.")
    config.output_path.write_text(html, encoding="utf-8")
    write_archive_index(config.archive_dir)
    log_verbose(config.verbose, "Daily Paper run complete.")
    return config.output_path


if __name__ == "__main__":
    run(load_config())
