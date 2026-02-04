from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ARCHIVE_TIMESTAMP_FORMAT = "%Y-%m-%d_%H%M%S"
ARCHIVE_LINK_MAIN = "archive/index.html"
ARCHIVE_LINK_ARCHIVE = "index.html"
# Keep the archive masthead aligned with the main newspaper branding.
PAPER_NAME = "Tacitus' Log"


@dataclass(frozen=True)
class ArchiveEntry:
    path: Path
    timestamp: datetime | None
    label: str


def archive_existing(output_path: Path, archive_dir: Path) -> Path | None:
    if not output_path.exists():
        return None

    timestamp = datetime.now().strftime(ARCHIVE_TIMESTAMP_FORMAT)
    destination = archive_dir / f"{timestamp}.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    output_path.replace(destination)
    _rewrite_archive_link(destination)
    return destination


def write_archive_index(archive_dir: Path) -> Path:
    """Create a simple archive index page listing all archived reports."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    entries = _collect_archive_entries(archive_dir)
    archive_index = archive_dir / "index.html"
    archive_index.write_text(_render_archive_index(entries), encoding="utf-8")
    return archive_index


def _collect_archive_entries(archive_dir: Path) -> list[ArchiveEntry]:
    entries = []
    for path in sorted(archive_dir.glob("*.html")):
        if path.name == "index.html":
            continue
        timestamp = _parse_archive_timestamp(path.stem)
        label = (
            timestamp.strftime("%Y-%m-%d %H:%M:%S")
            if timestamp
            else path.stem.replace("_", " ")
        )
        entries.append(ArchiveEntry(path=path, timestamp=timestamp, label=label))

    # Most recent first for quick scanning.
    entries.sort(
        key=lambda entry: entry.timestamp or datetime.min,
        reverse=True,
    )
    return entries


def _parse_archive_timestamp(stem: str) -> datetime | None:
    try:
        return datetime.strptime(stem, ARCHIVE_TIMESTAMP_FORMAT)
    except ValueError:
        return None


def _rewrite_archive_link(archive_path: Path) -> None:
    """Ensure archived reports point back to the archive index."""
    html = archive_path.read_text(encoding="utf-8")
    if ARCHIVE_LINK_MAIN in html:
        html = html.replace(
            f'href="{ARCHIVE_LINK_MAIN}"',
            f'href="{ARCHIVE_LINK_ARCHIVE}"',
        )
    if 'href="archive/"' in html:
        html = html.replace('href="archive/"', f'href="{ARCHIVE_LINK_ARCHIVE}"')
    archive_path.write_text(html, encoding="utf-8")


def _render_archive_index(entries: list[ArchiveEntry]) -> str:
    if entries:
        items = "\n".join(
            f'      <li><a href="{entry.path.name}" target="_blank" '
            f'rel="noopener noreferrer">{entry.label}</a></li>'
            for entry in entries
        )
        content = f"    <ul>\n{items}\n    </ul>"
    else:
        content = "    <p>No archived reports yet. Check back after the next run.</p>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Archive — {PAPER_NAME}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #1d1b16;
      --muted: #5a544a;
      --paper: #f8f3e8;
      --rule: #c9c2b8;
    }}
    body {{
      margin: 2.5rem auto;
      max-width: 720px;
      padding: 0 1.5rem;
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, "Times New Roman", serif;
      line-height: 1.7;
      color: var(--ink);
      background: var(--paper);
    }}
    header {{
      text-align: center;
      border-bottom: 1px solid var(--rule);
      padding-bottom: 1.2rem;
      margin-bottom: 1.6rem;
    }}
    h1 {{
      font-size: 2rem;
      margin: 0;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }}
    p {{
      color: var(--muted);
    }}
    ul {{
      list-style: none;
      padding: 0;
      margin: 1rem 0 0;
    }}
    li {{
      margin: 0.45rem 0;
    }}
    a {{
      color: inherit;
      text-decoration: none;
      border-bottom: 1px solid var(--rule);
    }}
    a:hover {{
      color: var(--muted);
    }}
    footer {{
      margin-top: 2rem;
      font-size: 0.9rem;
      color: var(--muted);
      text-align: center;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Archive</h1>
    <p>Past editions of {PAPER_NAME}, listed chronologically.</p>
  </header>
{content}
  <footer>
    <a href="../index.html" target="_blank" rel="noopener noreferrer">
      Return to the latest edition
    </a>
  </footer>
</body>
</html>"""
