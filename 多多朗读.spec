# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller configuration for the PySide6 + React desktop application."""

from pathlib import Path


ROOT = Path(SPECPATH)
FRONTEND_DIST = ROOT / "prototype" / "dist" / "client"
if not (FRONTEND_DIST / "index.html").is_file():
    raise SystemExit(
        "Missing prototype/dist/client/index.html; run the frontend production build first."
    )


a = Analysis(
    [str(ROOT / "novelreader" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "assets" / "app.ico"), "assets"),
        (str(FRONTEND_DIST), "prototype/dist/client"),
    ],
    hiddenimports=[
        "pyttsx3.drivers",
        "pyttsx3.drivers.sapi5",
        "edge_tts",
        "aiohttp",
        "pycaw",
        "pycaw.pycaw",
        "pycaw.api",
        "comtypes",
        "psutil",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "idlelib",
        "test",
        "tkinter",
        "tkinterdnd2",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="多多朗读",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(ROOT / "assets" / "app.ico")],
)
