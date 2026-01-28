# Daily Briefing Generator

A small Python 3 script that generates a text-only daily news briefing HTML page and archives the previous version.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python main.py
```

Optional config path:

```bash
python main.py --config ./config.json
```

Output: `./site/index.html` (previous `index.html` is archived into `./site/archive/`).

## Cron example

Run every morning at 7:30am local time:

```cron
30 7 * * * /usr/bin/env bash -lc 'cd /path/to/newspaper && /path/to/newspaper/.venv/bin/python main.py >> cron.log 2>&1'
```
