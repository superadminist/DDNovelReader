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


def _wait_for_port(port: int, process: subprocess.Popen, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"desktop host exited before CDP became ready: {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("desktop host did not expose its CDP endpoint")


def _runtime_child_images(pid: int) -> list[str]:
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("psutil is required for packaged-process verification") from exc
    try:
        process = psutil.Process(pid)
        return sorted({child.name().lower() for child in process.children(recursive=True)})
    except psutil.Error as exc:
        raise RuntimeError(f"could not inspect packaged process tree: {exc}") from exc


def _terminate_process_tree(process: subprocess.Popen) -> None:
    try:
        import psutil

        root = psutil.Process(process.pid)
        descendants = root.children(recursive=True)
        for child in descendants:
            child.terminate()
        root.terminate()
        _, alive = psutil.wait_procs(descendants + [root], timeout=5)
        for item in alive:
            item.kill()
        psutil.wait_procs(alive, timeout=5)
    except Exception:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


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
    parser.add_argument("--node", required=True, help="Node 20+ executable")
    parser.add_argument("--screenshot", required=True, help="PNG output outside the repository")
    parser.add_argument(
        "--executable",
        help="packaged desktop executable; omit to verify the Python source entry",
    )
    parser.add_argument(
        "--single-process",
        action="store_true",
        help="diagnose a broken graphics session by keeping WebEngine in the host process",
    )
    parser.add_argument("--trace", action="store_true", help="print Qt host QA checkpoints")
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
        chromium_flags = "--remote-allow-origins=*"
        if args.single_process:
            chromium_flags += " --single-process"
        environment.update({
            "DOUBAO_NOVEL_DATA": os.fspath(data_root),
            "QTWEBENGINE_REMOTE_DEBUGGING": str(port),
            "QTWEBENGINE_CHROMIUM_FLAGS": chromium_flags,
            "DD_QA_CDP_PORT": str(port),
            "DD_QA_BOOK_TITLE": BOOK_TITLE,
            "DD_QA_SEARCH_TERM": SEARCH_TERM,
            "DD_QA_SCREENSHOT": os.fspath(screenshot),
        })
        if args.trace:
            environment["DD_QA_TRACE"] = "1"
        launch_command = (
            [os.fspath(Path(args.executable).resolve())]
            if args.executable
            else [sys.executable, "-m", "novelreader.qt_main"]
        )
        child_images: list[str] = []
        external_runtime_children: list[str] = []
        process = subprocess.Popen(
            launch_command,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            _wait_for_port(port, process)
            child_images = _runtime_child_images(process.pid) if args.executable else []
            if args.executable:
                external_runtime_children = [
                    image for image in child_images if image in {"node.exe", "python.exe", "pythonw.exe"}
                ]
                if external_runtime_children:
                    raise AssertionError(
                        f"desktop package launched external runtimes: {external_runtime_children}"
                    )
            node = subprocess.run(
                [args.node, os.fspath(ROOT / "prototype" / "tests" / "stage3-qt-cdp.mjs")],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120 if args.executable else 45,
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
                _terminate_process_tree(process)
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
    print(json.dumps({
        "qtExit": 0,
        "qtWebEngineResidualPids": [],
        "externalRuntimeChildren": external_runtime_children,
        "observedChildImages": child_images,
        "screenshot": os.fspath(screenshot),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
