# Daily Paper

A small, readable Python 3 project that generates a daily text-first “AI newspaper” HTML page and archives prior editions.

## Quick start

```bash
python -m daily_paper
```

The output is written to `./public/index.html`. If a previous index exists, it is archived to `./public/archive/YYYY-MM-DD_HHMMSS/index.html` before being overwritten.

## Configuration

Defaults live in `daily_paper/config.py` as `DEFAULT_CONFIG`.

Key options:

- `no_visuals=True`: Enforces a text-first HTML output (no images, video, iframes, or remote scripts).
- `show_titles=True`: Include the original article title below the AI summary for traceability.
- `fetch_full_text=False`: When enabled, fetches the article body to provide more context and checks for paywalls.
- `items_per_topic=8`: Number of items per topic section.
- `model="gpt-5-mini"`: Change to another OpenAI model as needed.

Environment:

- `OPENAI_API_KEY` must be set to call the OpenAI API for item and topic summaries.

## Paywall filtering

Two layers are used:

1. **Allowlist only**: feeds are curated per topic in config.
2. **Soft detection**: when `fetch_full_text=True`, the fetcher excludes items if the status code is 401/402/403/451 or the HTML contains common paywall markers.

## Dependencies

Install dependencies with:

```bash
pip install -r requirements.txt
```
