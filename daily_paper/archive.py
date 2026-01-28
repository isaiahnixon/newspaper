from __future__ import annotations

from datetime import datetime
from pathlib import Path


def archive_existing(output_path: Path, archive_dir: Path) -> Path | None:
    if not output_path.exists():
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    destination = archive_dir / timestamp / output_path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    output_path.replace(destination)
    return destination
