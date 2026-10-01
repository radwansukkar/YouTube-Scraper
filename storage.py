"""CSV export helpers."""
from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from scraper import FIELDS, Video

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]+')


def safe_name(text: str) -> str:
    cleaned = _INVALID_CHARS.sub("_", text.strip()).replace(" ", "_")
    return cleaned or "youtube"


def build_filename(keyword: str, custom: Optional[str] = None) -> str:
    if custom and custom.strip():
        name = safe_name(custom)
        if name.lower().endswith(".csv"):
            name = name[:-4]
        return f"{name}.csv"
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{safe_name(keyword)}_{stamp}.csv"


def save_csv(videos: Iterable[Video], folder: str | Path, filename: str) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    # utf-8-sig so Excel displays Arabic / non-Latin titles correctly
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDS)
        writer.writerows(v.as_row() for v in videos)
    return path
