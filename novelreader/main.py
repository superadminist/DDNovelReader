# -*- coding: utf-8 -*-
"""Compatibility entry point for the Qt desktop application."""
from __future__ import annotations

try:
    from .qt_main import main
except ImportError:  # Direct script execution from run.bat/PyInstaller analysis.
    from novelreader.qt_main import main


if __name__ == "__main__":
    raise SystemExit(main())
