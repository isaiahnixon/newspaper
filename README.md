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

- `no_visuals`: Enforces a text-first HTML output (no images, video, iframes, or remote scripts).
- `fetch_full_text`: When enabled, fetches the article body to provide more context and checks for paywalls.
- `items_per_topic`: Number of items per topic section.
- `item_model`: Model for headline-style item summaries.
- `topic_model`: Model for section summaries.
- `temperature`: Set to a number or `null` to omit the override and use provider defaults.
- `openai_timeout_secs`, `openai_max_retries`, `openai_retry_backoff_secs`, `openai_retry_on_timeout`: Request controls for the OpenAI client.

Item summaries always appear in the output; original titles are not rendered separately.

To use a different config file:

```bash
python -m daily_paper --config /path/to/daily_paper.yaml
```

Environment:

- `OPENAI_API_KEY` must be set to call the OpenAI API for item and topic summaries.
- `DAILY_PAPER_DRY_RUN=1` (or `OPENAI_DRY_RUN=1`) skips API calls and returns a placeholder summary.

## Paywall filtering

Two layers are used:

1. **Allowlist only**: feeds are curated per topic in config.
2. **Soft detection**: when `fetch_full_text=True`, the fetcher excludes items if the status code is 401/402/403/451 or the HTML contains common paywall markers.

## Dependencies

Install dependencies with:

```bash
pip install -r requirements.txt
```
