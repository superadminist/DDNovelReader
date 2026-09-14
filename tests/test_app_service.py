# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from novelreader.app_service import AppPreferencesError, AppPreferencesService


class AppPreferencesServiceTests(unittest.TestCase):
    def test_missing_library_is_read_only_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "library.json"
            state = AppPreferencesService(path).state()
            self.assertEqual(state["theme"], "护眼")
            self.assertEqual(state["colorScheme"], "light")
            self.assertTrue(state["autoOpenLast"])
            self.assertFalse(state["closeToTray"])
            self.assertTrue(state["autoCheckUpdates"])
            self.assertEqual(state["startupBookId"], "")
            self.assertFalse(path.exists())

    def test_startup_book_requires_enabled_existing_last_book(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "library.json"
            path.write_text(json.dumps({
                "books": {"book-1": {"title": "保留"}},
                "settings": {"theme": "夜间", "auto_open_last": True, "last_book": "book-1"},
            }), encoding="utf-8")
            state = AppPreferencesService(path).state()
            self.assertEqual(state["startupBookId"], "book-1")
            self.assertEqual(state["colorScheme"], "dark")

            path.write_text(json.dumps({
                "books": {"book-1": {}},
                "settings": {"auto_open_last": False, "last_book": "book-1"},
            }), encoding="utf-8")
            self.assertEqual(AppPreferencesService(path).state()["startupBookId"], "")

    def test_update_preserves_books_and_legacy_setting_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "library.json"
            path.write_text(json.dumps({
                "books": {"book-1": {"title": "保留"}},
                "settings": {"last_book": "book-1", "tts_rate": 260},
            }), encoding="utf-8")
            state = AppPreferencesService(path).update({
                "theme": "夜间", "autoOpenLast": False, "closeToTray": True,
                "autoCheckUpdates": False,
            })
            self.assertEqual(state["theme"], "夜间")
            self.assertFalse(state["autoOpenLast"])
            self.assertTrue(state["closeToTray"])
            self.assertFalse(state["autoCheckUpdates"])
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("book-1", stored["books"])
            self.assertEqual(stored["settings"]["tts_rate"], 260)
            self.assertEqual(stored["settings"]["theme"], "夜间")
            self.assertFalse(stored["settings"]["auto_open_last"])
            self.assertTrue(stored["settings"]["close_to_tray"])
            self.assertFalse(stored["settings"]["auto_check_updates"])

    def test_update_metadata_persists_check_time_and_skipped_version(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "library.json"
            service = AppPreferencesService(path)
            service.record_update_check("2026-09-14T17:00:00+08:00")
            service.skip_update_version("v2.0.2")

            self.assertEqual(service.update_metadata(), {
                "skippedVersion": "2.0.2",
                "lastCheckedAt": "2026-09-14T17:00:00+08:00",
            })
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(stored["settings"]["skipped_update_version"], "2.0.2")

    def test_invalid_or_damaged_input_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "library.json"
            path.write_text("{broken", encoding="utf-8")
            service = AppPreferencesService(path)
            with self.assertRaises(AppPreferencesError):
                service.update({"theme": "夜间"})
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")
            for patch in (
                {}, {"theme": "蓝色"}, {"autoOpenLast": 1},
                {"closeToTray": 1}, {"autoCheckUpdates": 1}, {"unknown": True},
            ):
                with self.assertRaises(AppPreferencesError):
                    service.update(patch)


if __name__ == "__main__":
    unittest.main()
