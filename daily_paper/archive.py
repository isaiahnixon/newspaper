from __future__ import annotations

from datetime import datetime
from pathlib import Path


def archive_existing(output_path: Path, archive_dir: Path) -> Path | None:
    if not output_path.exists():
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    # Keep archived files in one directory with a readable timestamp filename.
    suffix = output_path.suffix or ".html"
    destination = archive_dir / f"{timestamp}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    output_path.replace(destination)
    return destination


def build_archive_index(archive_dir: Path) -> Path:
    """Create a lightweight index page that lists archived reports."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    index_path = archive_dir / "index.html"
    archive_entries = sorted(
        (
            path
            for path in archive_dir.glob("*.html")
            if path.name != index_path.name
        ),
        reverse=True,
    )

    list_items = "\n".join(
        f'      <li><a href="{path.name}">{format_archive_label(path.stem)}</a></li>'
        for path in archive_entries
    )
    if not list_items:
        list_items = "      <li>No archived reports yet.</li>"

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Daily Signal Archive</title>
  <style>
    body {{
      margin: 2.5rem auto;
      max-width: 720px;
      padding: 0 1.5rem;
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, "Times New Roman", serif;
      line-height: 1.7;
      color: #1d1b16;
      background: #f8f3e8;
    }}
    h1 {{
      margin-bottom: 0.5rem;
    }}
    .meta {{
      color: #5a544a;
      font-size: 0.95rem;
      margin-bottom: 1.5rem;
    }}
    ul {{
      padding-left: 1.2rem;
    }}
    li {{
      margin-bottom: 0.5rem;
    }}
  </style>
</head>
<body>
  <h1>Archive</h1>
  <div class="meta">Archived Daily Signal reports, newest first.</div>
  <ul>
{list_items}
  </ul>
  <p><a href="../index.html">Back to latest edition</a></p>
</body>
</html>
"""
    index_path.write_text(html, encoding="utf-8")
    return index_path


def format_archive_label(stem: str) -> str:
    """Convert the timestamped filename stem into a human-readable label."""
    try:
        parsed = datetime.strptime(stem, "%Y-%m-%d_%H%M%S")
    except ValueError:
        return stem
    return parsed.strftime("%B %d, %Y at %H:%M:%S")
