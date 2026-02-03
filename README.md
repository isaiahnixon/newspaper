# Daily Paper

A small, readable Python 3 project that generates a daily text-first “AI newspaper” HTML page and archives prior editions.

## License

[MIT](LICENSE)

## Quick start

```bash
python -m daily_paper
```

The output is written to `./index.html`. If a previous index exists, it is archived to `./archive/YYYY-MM-DD_HHMMSS.html` before being overwritten, and the archive index is refreshed at `./archive/index.html`.

## Configuration

Configuration lives in the root-level `daily_paper.yaml`. Every required key must be present so missing values fail fast instead of being silently defaulted.

Key options:

- `fetch_full_text`: When enabled, fetches the article body to provide more context.
- `items_per_topic`: Default number of items per topic section.
- `topics[].items_per_topic`: Optional override for a specific topic’s item count.
- `topics[].lookback_hours`: Per-topic window (in hours) for eligible feed entries.
- `item_model`: Model for headline-style item summaries.
- `selection_model`: Model used to rank items before summarization.
- `topic_model`: Model for section summaries.
- `temperature`: Set to a number or `null` to omit the override and use provider defaults.
- `dry_run`: Set to `true` to skip API calls and return placeholder summaries.
- `openai_timeout_secs`, `openai_max_retries`, `openai_retry_backoff_secs`, `openai_retry_on_timeout`: Request controls for the OpenAI client.

Item summaries always appear in the output; original titles are not rendered separately. Each topic starts
with a single macro summary that synthesizes themes without repeating item-level details.

The default configuration includes a Montana News section built from non-paywalled local sources to
expand regional coverage alongside national and global topics.

Duplicate stories are deduplicated across topics using canonicalized URLs and a near-duplicate title check.
Selection favors higher-information items and source diversity while remaining deterministic.

To use a different config file:

```bash
python -m daily_paper --config /path/to/daily_paper.yaml
```

Environment:

- `OPENAI_API_KEY` must be set to call the OpenAI API for item and topic summaries.

## Output behavior

- Links in the generated HTML open in a new tab for safer navigation.
- Tech News item summaries render without category tags or label prefixes.
- The masthead notes that the digest is updated weekdays.

## Dependencies

Install dependencies with:

```bash
pip install -r requirements.txt
```
