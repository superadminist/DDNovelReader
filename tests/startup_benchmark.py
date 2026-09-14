# -*- coding: utf-8 -*-
"""Measure time from process creation to the first visible DDNovelReader window."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

import psutil

from stage4_window_probe import _windows


def _process_ids(process: subprocess.Popen) -> list[int]:
    result = [process.pid]
    try:
        result.extend(child.pid for child in psutil.Process(process.pid).children(recursive=True))
    except (psutil.Error, OSError):
        pass
    return list(dict.fromkeys(result))


def _terminate_tree(process: subprocess.Popen) -> None:
    processes: list[psutil.Process] = []
    try:
        root = psutil.Process(process.pid)
        processes.extend(root.children(recursive=True))
        processes.append(root)
    except psutil.NoSuchProcess:
        return
    for item in reversed(processes):
        try:
            item.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(processes, timeout=4)
    for item in alive:
        try:
            item.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(alive, timeout=4)


def _one_run(executable: Path, data_root: Path, timeout: float) -> float:
    environment = os.environ.copy()
    environment["DOUBAO_NOVEL_DATA"] = os.fspath(data_root)
    started = time.perf_counter()
    process = subprocess.Popen(
        [os.fspath(executable)],
        cwd=executable.parent,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = started + timeout
        while time.perf_counter() < deadline:
            for pid in _process_ids(process):
                try:
                    windows = _windows(pid)
                except OSError:
                    continue
                if any(item["title"] == "多多朗读" and item["visible"] for item in windows):
                    return time.perf_counter() - started
            if process.poll() is not None:
                raise RuntimeError(f"process exited before showing a window: {process.returncode}")
            time.sleep(0.025)
        raise TimeoutError(f"no visible window after {timeout:.1f}s")
    finally:
        _terminate_tree(process)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executables", nargs="+", type=Path)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")

    results = []
    with tempfile.TemporaryDirectory(prefix="ddnr-startup-") as temporary:
        root = Path(temporary)
        for index, candidate in enumerate(args.executables):
            executable = candidate.resolve()
            if not executable.is_file():
                raise SystemExit(f"missing executable: {executable}")
            samples = [
                _one_run(executable, root / f"data-{index}-{run}", args.timeout)
                for run in range(args.runs)
            ]
            results.append({
                "path": os.fspath(executable),
                "runsSeconds": [round(value, 3) for value in samples],
                "medianSeconds": round(statistics.median(samples), 3),
                "minSeconds": round(min(samples), 3),
                "maxSeconds": round(max(samples), 3),
            })
    print(json.dumps({"runs": args.runs, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
