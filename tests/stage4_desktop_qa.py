# -*- coding: utf-8 -*-
"""Run the stage-4 floating-reader gate against the real Qt desktop host.

This is an explicit acceptance driver, not a unit-test substitute.  It launches
the packaged React build through QWebEngine, uses raw CDP to drive both page
targets, and keeps all library/cache writes in a temporary data directory.
"""
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

import psutil

ROOT = Path(__file__).resolve().parents[1]
if os.fspath(ROOT) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT))

from novelreader.book_loader import BookContent, Chapter
from novelreader.storage import Storage


BOOK_TITLE = "阶段四真实悬浮窗"
LONG_MARKER = "阶段四长句标记"


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
    pids: set[int] = set()
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) >= 2 and row[0].lower() == "qtwebengineprocess.exe":
            try:
                pids.add(int(row[1]))
            except ValueError:
                pass
    return pids


def _create_fixture(data_root: Path, fixture_root: Path) -> str:
    long_sentence = LONG_MARKER + "持续朗读用于验证浮窗关闭后不会停止唯一播放控制器" * 180 + "。"
    chapter_one = long_sentence + "这是紧随其后的第二句。这里是用于三句上下文的第三句。"
    chapter_two = "第二章用于验证上一句和下一句仍绑定同一个阅读会话。"
    source = fixture_root / "stage4-floating.txt"
    source.write_text(f"第一章 长句\n{chapter_one}\n第二章 共享状态\n{chapter_two}", encoding="utf-8")
    content = BookContent(
        BOOK_TITLE,
        "QA作者",
        "txt",
        [
            Chapter("第一章 长句", chapter_one),
            Chapter("第二章 共享状态", chapter_two),
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


def _outside_repository(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return True
    return False


def _wait_for_no_children(before: set[int], timeout: float = 7.0) -> None:
    deadline = time.time() + timeout
    remaining: set[int] = set()
    while time.time() < deadline:
        remaining = _qt_webengine_pids() - before
        if not remaining:
            return
        time.sleep(0.2)
    raise AssertionError(f"QtWebEngine child processes remain: {sorted(remaining)}")


def _resolve_window_host_pid(process: subprocess.Popen, window_probe: Path, timeout: float = 12.0) -> int:
    """Follow the Windows venv launcher to the Python process that owns Qt windows."""
    deadline = time.time() + timeout
    while time.time() < deadline and process.poll() is None:
        candidates = [process.pid]
        try:
            candidates.extend(child.pid for child in psutil.Process(process.pid).children(recursive=True))
        except (psutil.Error, OSError):
            pass
        for candidate in dict.fromkeys(candidates):
            result = subprocess.run(
                [sys.executable, os.fspath(window_probe), "snapshot", str(candidate)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode:
                continue
            try:
                windows = json.loads(result.stdout).get("windows", [])
            except json.JSONDecodeError:
                continue
            if any(item.get("title") == "启远阅读" for item in windows):
                return candidate
        time.sleep(0.1)
    raise RuntimeError("Unable to locate the Python process that owns the Qt main window")


def _run_phase(
    *,
    node: str,
    app_executable: str,
    data_root: Path,
    screenshot_dir: Path,
    checkpoint: Path,
    phase: str,
    scale: float,
    before_pids: set[int],
) -> dict[str, object]:
    port = _free_port()
    environment = os.environ.copy()
    environment.update({
        "DOUBAO_NOVEL_DATA": os.fspath(data_root),
        "QTWEBENGINE_REMOTE_DEBUGGING": str(port),
        # This runner executes inside an isolated desktop whose shared GPU
        # context is unavailable. Keeping WebEngine in the QA host process
        # makes the real-window visual gate deterministic; production builds
        # intentionally do not use this diagnostic Chromium switch.
        "QTWEBENGINE_CHROMIUM_FLAGS": "--remote-allow-origins=* --single-process",
        "QT_SCALE_FACTOR": str(scale),
        "QT_AUTO_SCREEN_SCALE_FACTOR": "0",
        "DD_QA_CDP_PORT": str(port),
        "DD_QA_BOOK_TITLE": BOOK_TITLE,
        "DD_QA_LONG_MARKER": LONG_MARKER,
        "DD_QA_SCREENSHOT_DIR": os.fspath(screenshot_dir),
        "DD_QA_CHECKPOINT": os.fspath(checkpoint),
        "DD_QA_STAGE4_PHASE": phase,
        "DD_QA_SCALE_FACTOR": str(scale),
        "DD_QA_PYTHON": sys.executable,
        "DD_QA_WINDOW_PROBE": os.fspath(ROOT / "tests" / "stage4_window_probe.py"),
    })
    process = subprocess.Popen(
        [app_executable] if app_executable else [sys.executable, "-m", "novelreader.qt_main"],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    host_pid = process.pid
    host_output = ""
    try:
        host_pid = _resolve_window_host_pid(
            process, ROOT / "tests" / "stage4_window_probe.py", timeout=30.0
        )
        environment["DD_QA_HOST_PID"] = str(host_pid)
        driven = subprocess.run(
            [node, os.fspath(ROOT / "prototype" / "tests" / "stage4-qt-cdp.mjs")],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
        if driven.stdout:
            print(driven.stdout, end="")
        if driven.stderr:
            print(driven.stderr, file=sys.stderr, end="")
        if driven.returncode:
            raise RuntimeError(f"stage-4 CDP QA phase {phase!r} failed with {driven.returncode}")
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Qt host did not exit after stage-4 phase {phase!r}") from exc
        if process.returncode != 0:
            raise RuntimeError(f"Qt host exited with {process.returncode} in phase {phase!r}")
        if not checkpoint.is_file():
            raise AssertionError("CDP driver did not create the stage-4 checkpoint")
        return json.loads(checkpoint.read_text(encoding="utf-8"))
    finally:
        if host_pid != process.pid:
            try:
                host_process = psutil.Process(host_pid)
                if host_process.is_running():
                    host_process.terminate()
                    try:
                        host_process.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        host_process.kill()
                        host_process.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
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
        _wait_for_no_children(before_pids)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", required=True, help="Node 20+ executable")
    parser.add_argument("--app-executable", default="", help="optional packaged one-file executable")
    parser.add_argument("--screenshot-dir", required=True, help="output directory outside the repository")
    parser.add_argument(
        "--dpi",
        default="1,1.25,1.5,2",
        help="comma-separated QT_SCALE_FACTOR matrix; first factor runs the full scenario",
    )
    args = parser.parse_args()

    screenshot_dir = Path(args.screenshot_dir).resolve()
    if not _outside_repository(screenshot_dir):
        raise SystemExit("--screenshot-dir must be outside the repository")
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    scales = [float(value.strip()) for value in args.dpi.split(",") if value.strip()]
    if not scales or any(value <= 0 for value in scales):
        raise SystemExit("--dpi must contain positive scale factors")
    if not (ROOT / "prototype" / "dist" / "client" / "index.html").is_file():
        raise SystemExit("Build prototype/dist/client before running the real Qt acceptance gate")

    before_pids = _qt_webengine_pids()
    with tempfile.TemporaryDirectory(prefix="ddnr-stage4-qa-") as temporary:
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

        checkpoint = temporary_root / "stage4-checkpoint.json"
        primary = _run_phase(
            node=args.node,
            app_executable=args.app_executable,
            data_root=data_root,
            screenshot_dir=screenshot_dir,
            checkpoint=checkpoint,
            phase="primary",
            scale=scales[0],
            before_pids=before_pids,
        )
        if primary.get("bookId") != book_id:
            raise AssertionError("floating reader was not bound to the isolated fixture book")
        persisted_geometry = primary.get("persistedGeometry")
        if not isinstance(persisted_geometry, str) or not persisted_geometry:
            raise AssertionError("floating-reader geometry was not persisted")

        restored = _run_phase(
            node=args.node,
            app_executable=args.app_executable,
            data_root=data_root,
            screenshot_dir=screenshot_dir,
            checkpoint=checkpoint,
            phase="restore",
            scale=scales[0],
            before_pids=before_pids,
        )
        if restored.get("restoredGeometry") != persisted_geometry:
            raise AssertionError(
                f"geometry did not survive restart: {persisted_geometry!r} -> {restored.get('restoredGeometry')!r}"
            )

        dpi_results = []
        for scale in scales[1:]:
            dpi_results.append(_run_phase(
                node=args.node,
                app_executable=args.app_executable,
                data_root=data_root,
                screenshot_dir=screenshot_dir,
                checkpoint=checkpoint,
                phase="dpi",
                scale=scale,
                before_pids=before_pids,
            ))

        saved = json.loads((data_root / "library.json").read_text(encoding="utf-8"))
        if book_id not in saved.get("books", {}):
            raise AssertionError("isolated fixture book disappeared during floating-reader QA")

    _wait_for_no_children(before_pids)
    print(json.dumps({
        "qtExit": 0,
        "qtWebEngineResidualPids": [],
        "screenshots": sorted(os.fspath(path) for path in screenshot_dir.glob("stage4-*.png")),
        "primary": primary,
        "restored": restored,
        "dpi": dpi_results,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
