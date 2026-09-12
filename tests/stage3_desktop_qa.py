# -*- coding: utf-8 -*-
"""Launch the real Qt host with isolated data and drive it through raw CDP."""
from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if os.fspath(ROOT) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT))

from novelreader.book_loader import BookContent, Chapter
from novelreader.storage import Storage


BOOK_TITLE = "阶段三真实书"
SEARCH_TERM = "唯一搜索词"


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _qt_webengine_pids() -> set[int]:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq QtWebEngineProcess.exe", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    pids = set()
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) >= 2 and row[0].lower() == "qtwebengineprocess.exe":
            try:
                pids.add(int(row[1]))
            except ValueError:
                pass
    return pids


def _create_fixture(data_root: Path, fixture_root: Path) -> str:
    source = fixture_root / "stage3-real.txt"
    source.write_text(
        "第一章 QA入口\n第一章真实正文。这里验证内容库打开。播放第一句。\n"
        "第二章 QA导航\n第二章真实正文。唯一搜索词只在第二章出现。播放高亮目标句。",
        encoding="utf-8",
    )
    content = BookContent(
        BOOK_TITLE,
        "QA作者",
        "txt",
        [
            Chapter("第一章 QA入口", "第一章真实正文。这里验证内容库打开。播放第一句。"),
            Chapter("第二章 QA导航", "第二章真实正文。唯一搜索词只在第二章出现。播放高亮目标句。"),
        ],
    )
    storage = Storage(os.fspath(data_root / "library.json"))
    book_id = storage.book_id(os.fspath(source))
    now = time.time()
    storage.add_book({
        "id": book_id,
        "title": content.title,
        "author": content.author,
        "format": content.format,
        "path": os.fspath(source),
        "added_at": now,
        "last_read_at": now,
        "total_chars": content.total_chars,
        "chapter_titles": [chapter.title for chapter in content.chapters],
        "progress": {"chapter_idx": 0, "char_offset": 0, "percent": 0.0},
    })
    storage.write_cache(book_id, content)
    return book_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", required=True, help="Node 22+ executable")
    parser.add_argument("--screenshot", required=True, help="PNG output outside the repository")
    args = parser.parse_args()
    screenshot = Path(args.screenshot).resolve()
    screenshot.parent.mkdir(parents=True, exist_ok=True)

    before = _qt_webengine_pids()
    with tempfile.TemporaryDirectory(prefix="ddnr-stage3-qa-") as temporary:
        temporary_root = Path(temporary)
        data_root = temporary_root / "data"
        fixture_root = temporary_root / "fixture"
        data_root.mkdir()
        fixture_root.mkdir()
        previous_data_root = os.environ.get("DOUBAO_NOVEL_DATA")
        os.environ["DOUBAO_NOVEL_DATA"] = os.fspath(data_root)
        try:
            book_id = _create_fixture(data_root, fixture_root)
        finally:
            if previous_data_root is None:
                os.environ.pop("DOUBAO_NOVEL_DATA", None)
            else:
                os.environ["DOUBAO_NOVEL_DATA"] = previous_data_root
        port = _free_port()
        environment = os.environ.copy()
        environment.update({
            "DOUBAO_NOVEL_DATA": os.fspath(data_root),
            "QTWEBENGINE_REMOTE_DEBUGGING": str(port),
            "QTWEBENGINE_CHROMIUM_FLAGS": "--remote-allow-origins=*",
            "DD_QA_CDP_PORT": str(port),
            "DD_QA_BOOK_TITLE": BOOK_TITLE,
            "DD_QA_SEARCH_TERM": SEARCH_TERM,
            "DD_QA_SCREENSHOT": os.fspath(screenshot),
        })
        process = subprocess.Popen(
            [sys.executable, "-m", "novelreader.qt_main"],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            node = subprocess.run(
                [args.node, os.fspath(ROOT / "prototype" / "tests" / "stage3-qt-cdp.mjs")],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
            )
            print(node.stdout, end="")
            if node.stderr:
                print(node.stderr, file=sys.stderr, end="")
            if node.returncode:
                raise RuntimeError(f"CDP QA failed with exit code {node.returncode}")
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Qt host did not exit after the close-window action") from exc
            if process.returncode != 0:
                raise RuntimeError(f"Qt host exited with {process.returncode}")

            saved = json.loads((data_root / "library.json").read_text(encoding="utf-8"))
            metadata = saved["books"][book_id]
            if saved["settings"].get("font_size") != 18:
                raise AssertionError("font size was not persisted through the real Bridge")
            if not metadata.get("bookmarks"):
                raise AssertionError("bookmark was not persisted through the real Bridge")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process.stdout:
                host_output = process.stdout.read()
                if host_output:
                    print(host_output, file=sys.stderr, end="")

    deadline = time.time() + 5
    remaining = set()
    while time.time() < deadline:
        remaining = _qt_webengine_pids() - before
        if not remaining:
            break
        time.sleep(0.2)
    if remaining:
        raise AssertionError(f"QtWebEngine child processes remain: {sorted(remaining)}")
    print(json.dumps({"qtExit": 0, "qtWebEngineResidualPids": [], "screenshot": os.fspath(screenshot)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
