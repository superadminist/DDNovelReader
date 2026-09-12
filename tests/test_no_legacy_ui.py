from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LegacyUiRemovalTests(unittest.TestCase):
    def test_formal_entrypoint_does_not_load_tk_ui(self) -> None:
        script = """
import sys
import novelreader.main
import novelreader.qt_main
import novelreader.qt_host
import novelreader.qt_bridge

forbidden = {
    'tkinter',
    'tkinterdnd2',
    'novelreader.constants',
    'novelreader.gui',
    'novelreader.modern_ui',
}
loaded = sorted(name for name in sys.modules if name in forbidden)
if loaded:
    raise SystemExit('legacy modules loaded: ' + ', '.join(loaded))
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def test_legacy_ui_modules_are_removed(self) -> None:
        removed = (
            "bookmark_ui.py",
            "cache_ui.py",
            "dialog_ui.py",
            "download_ui.py",
            "gui.py",
            "import_ui.py",
            "modern_ui.py",
            "reader_ui.py",
            "search_ui.py",
            "shelf_ui.py",
            "shortcuts_ui.py",
            "theme_ui.py",
            "tts_ui.py",
        )
        leftovers = [name for name in removed if (ROOT / "novelreader" / name).exists()]
        self.assertEqual(leftovers, [])
        self.assertNotIn("tkinterdnd2", (ROOT / "requirements.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
