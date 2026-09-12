# -*- coding: utf-8 -*-
"""Repeatable 20k/100k reader and playback performance gate."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if os.fspath(ROOT) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT))

from novelreader.book_loader import BookContent, Chapter
from novelreader.playback_service import PlaybackService
from novelreader.reader_service import ReaderService
from novelreader.storage import Storage
from novelreader.tts_engine import SpeechController


def _fixture(root: Path, size: int):
    source = root / f"performance-{size}.txt"
    text = ("这是一句用于阶段三性能回归的真实正文。" * (size // 18 + 1))[:size]
    source.write_text(text, encoding="utf-8")
    content = BookContent(f"性能书-{size}", "", "txt", [Chapter("长章节", text)])
    storage = Storage(os.fspath(root / "library.json"))
    book_id = storage.book_id(os.fspath(source))
    now = time.time()
    storage.add_book({
        "id": book_id,
        "title": content.title,
        "author": "",
        "format": "txt",
        "path": os.fspath(source),
        "added_at": now,
        "last_read_at": now,
        "total_chars": content.total_chars,
        "chapter_titles": ["长章节"],
        "progress": {"chapter_idx": 0, "char_offset": 0, "percent": 0.0},
    })
    storage.write_cache(book_id, content)
    return book_id


def main() -> int:
    results = []
    with tempfile.TemporaryDirectory(prefix="ddnr-stage3-perf-") as temporary:
        data_root = Path(temporary)
        previous = os.environ.get("DOUBAO_NOVEL_DATA")
        os.environ["DOUBAO_NOVEL_DATA"] = os.fspath(data_root)
        try:
            for size in (20_000, 100_000):
                book_id = _fixture(data_root, size)
                reader = ReaderService(data_root / "library.json")
                started = time.perf_counter()
                opened = reader.open_book(book_id)
                open_ms = (time.perf_counter() - started) * 1000
                started = time.perf_counter()
                window = reader.get_window(opened["sessionId"], 0, size // 2)
                window_ms = (time.perf_counter() - started) * 1000

                speech = SpeechController()
                playback = PlaybackService(speech)
                content = reader.get_session_content(opened["sessionId"])
                playback.bind_session(opened["sessionId"], book_id, content, 0, 0)
                started = time.perf_counter()
                sentence_count = len(playback._sentence_entries(0))
                sentence_index_ms = (time.perf_counter() - started) * 1000
                playback.shutdown()
                results.append({
                    "chars": size,
                    "openMs": round(open_ms, 3),
                    "windowMs": round(window_ms, 3),
                    "sentenceIndexMs": round(sentence_index_ms, 3),
                    "sentenceCount": sentence_count,
                    "windowChars": sum(len(block["text"]) for block in window["blocks"]),
                })
        finally:
            if previous is None:
                os.environ.pop("DOUBAO_NOVEL_DATA", None)
            else:
                os.environ["DOUBAO_NOVEL_DATA"] = previous

    if results[0]["openMs"] > 500 or results[1]["openMs"] > 1500:
        raise AssertionError(f"reader open gate failed: {results}")
    if results[0]["sentenceIndexMs"] > 500 or results[1]["sentenceIndexMs"] > 1500:
        raise AssertionError(f"sentence index gate failed: {results}")
    if results[1]["sentenceIndexMs"] / max(results[0]["sentenceIndexMs"], 0.001) > 7.5:
        raise AssertionError(f"sentence index scaling gate failed: {results}")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
