# -*- coding: utf-8 -*-
"""Application data paths for source runs and packaged Windows builds."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys


DATA_ENV = "DOUBAO_NOVEL_DATA"
DATA_DIRECTORY_NAME = "data"
LEGACY_DIRECTORY_NAME = "DDNovelReader"


def is_frozen() -> bool:
    """Return whether the application is running from a PyInstaller build."""
    return bool(getattr(sys, "frozen", False))


def application_dir() -> Path:
    """Return the directory containing the packaged executable."""
    return Path(sys.executable).resolve().parent


def legacy_data_dir() -> Path:
    """Return the pre-installer per-user data directory."""
    appdata = os.environ.get("APPDATA")
    return (Path(appdata) if appdata else Path.home()) / LEGACY_DIRECTORY_NAME


def default_data_dir() -> Path:
    """Resolve the data root without creating or migrating directories.

    Tests and diagnostics may explicitly override the location. Packaged builds
    keep all user data beside the executable, while source runs retain the
    historical per-user location so development never writes into the checkout.
    """
    configured = os.environ.get(DATA_ENV)
    if configured and configured.strip():
        return Path(configured.strip())
    if is_frozen():
        return application_dir() / DATA_DIRECTORY_NAME
    return legacy_data_dir()


def ensure_data_dir() -> Path:
    """Create the active data root and migrate legacy data when appropriate.

    Migration is copy-only: the old AppData directory remains available for
    rollback. A temporary sibling directory prevents a failed copy from being
    mistaken for a completed migration on the next launch.
    """
    target = default_data_dir()
    if target.exists():
        if not target.is_dir():
            raise NotADirectoryError(os.fspath(target))
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    if not is_frozen() or (os.environ.get(DATA_ENV) or "").strip():
        target.mkdir(parents=True, exist_ok=True)
        return target

    legacy = legacy_data_dir()
    if not legacy.is_dir() or _same_path(legacy, target):
        target.mkdir(parents=True, exist_ok=True)
        return target

    temporary = target.with_name(f".{target.name}.migrating-{os.getpid()}")
    if temporary.exists():
        shutil.rmtree(temporary)
    try:
        shutil.copytree(legacy, temporary)
        os.replace(temporary, target)
    except FileExistsError:
        # A second process may have completed the same migration first.
        shutil.rmtree(temporary, ignore_errors=True)
        if not target.is_dir():
            raise
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))
