# -*- coding: utf-8 -*-
"""Read-only content-library queries for the Qt frontend."""

from __future__ import annotations

import json
import hashlib
import math
import os
from pathlib import Path
from typing import Any

from .paths import default_data_dir


DEFAULT_COVER_URLS = (
    "covers/library-indigo.jpg",
    "covers/library-sage.jpg",
    "covers/library-amber.jpg",
    "covers/library-night.jpg",
)
DEFAULT_COVER_URL = DEFAULT_COVER_URLS[0]


class LibraryDataError(Exception):
    """Raised when an existing library file cannot be read safely."""

    code = "LIBRARY_INVALID"
    user_message = "书架数据读取失败，请检查 library.json 是否完整。"


def default_library_path() -> Path:
    """Resolve the existing library path without creating any directories."""
    return default_data_dir() / "library.json"


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integer(value: Any, default: int = 0) -> int:
    number = _finite_number(value)
    return int(number) if number is not None else default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _default_cover_url(book_id: Any) -> str:
    """Choose a stable cover without relying on Python's randomized hash()."""
    digest = hashlib.blake2s(_text(book_id).encode("utf-8"), digest_size=1).digest()[0]
    return DEFAULT_COVER_URLS[digest % len(DEFAULT_COVER_URLS)]


class LibraryQueryService:
    """Project the legacy library schema into the Bridge v1 read model."""

    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = Path(path) if path is not None else default_library_path()

    def load_library(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"books": [], "total": 0}

        try:
            with self.path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LibraryDataError() from exc

        if not isinstance(payload, dict):
            raise LibraryDataError()

        raw_books = payload.get("books", {})
        if raw_books is None:
            raw_books = {}
        if not isinstance(raw_books, dict):
            raise LibraryDataError()

        books = [
            self._book_summary(book_id, metadata)
            for book_id, metadata in raw_books.items()
            if isinstance(metadata, dict)
        ]
        books.sort(key=lambda book: book["lastReadAt"] or 0, reverse=True)
        return {"books": books, "total": len(books)}

    @staticmethod
    def _book_summary(book_id: Any, metadata: dict[str, Any]) -> dict[str, Any]:
        resolved_book_id = _text(metadata.get("id") or book_id)
        progress = metadata.get("progress")
        if not isinstance(progress, dict):
            progress = {}

        chapter_index = _integer(progress.get("chapter_idx"), 0)
        chapter_titles = metadata.get("chapter_titles")
        if not isinstance(chapter_titles, list):
            chapter_titles = []
        current_chapter = ""
        if 0 <= chapter_index < len(chapter_titles):
            current_chapter = _text(chapter_titles[chapter_index])

        percent = _finite_number(progress.get("percent"))
        percent = min(100.0, max(0.0, percent if percent is not None else 0.0))
        progress_percent: int | float = round(percent, 1)
        if progress_percent == int(progress_percent):
            progress_percent = int(progress_percent)

        last_read_at = _finite_number(metadata.get("last_read_at"))
        total_chars = max(0, _integer(metadata.get("total_chars"), 0))

        return {
            "id": resolved_book_id,
            "title": _text(metadata.get("title"), "未命名内容") or "未命名内容",
            "author": _text(metadata.get("author")),
            "format": _text(metadata.get("format")).lstrip(".").upper(),
            "progressPercent": progress_percent,
            "chapterIndex": chapter_index,
            "chapterCount": len(chapter_titles),
            "currentChapterTitle": current_chapter,
            "lastReadAt": last_read_at,
            "totalChars": total_chars,
            "coverUrl": _default_cover_url(resolved_book_id),
        }
