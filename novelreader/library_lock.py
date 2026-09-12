# -*- coding: utf-8 -*-
"""Process-local locks for read-modify-write operations on library files."""

from __future__ import annotations

import os
import threading
from pathlib import Path


_registry_lock = threading.Lock()
_library_locks: dict[str, threading.RLock] = {}


def library_write_lock(path: str | os.PathLike[str]) -> threading.RLock:
    """Return the shared lock for one resolved library path."""
    key = os.path.normcase(os.path.abspath(os.fspath(Path(path))))
    with _registry_lock:
        lock = _library_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _library_locks[key] = lock
        return lock
