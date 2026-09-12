# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QRect

from novelreader.floating_reader_service import (
    FloatingReaderError,
    FloatingReaderService,
)
from novelreader.qt_bridge import DesktopBridge
from novelreader.qt_host import (
    clamp_floating_geometry,
    floating_frontend_url,
    qt_geometry_string,
)


class _Playback:
    def __init__(self):
        self.closed = False
        self.drain_count = 0

    @staticmethod
    def session_identity():
        return {"sessionId": "session-4", "bookId": "book-4"}

    @staticmethod
    def snapshot():
        return {
            "status": "playing",
            "position": {"chapterIndex": 1, "charOffset": 4, "progressPercent": 50.0},
            "sentence": None,
            "requestedBackend": "sapi",
            "activeBackend": "sapi",
            "fallbackActive": False,
        }

    @staticmethod
    def floating_context():
        sentence = {
            "chapterIndex": 1,
            "startOffset": 4,
            "endOffset": 8,
            "text": "当前句。",
        }
        return {
            "chapterIndex": 1,
            "chapterTitle": "第二章",
            "previous": None,
            "current": sentence,
            "next": None,
        }

    def drain_events(self):
        self.drain_count += 1
        return []

    def shutdown(self, timeout=2.0):
        self.closed = True
        return True


class _Library:
    def __init__(self, path):
        self.path = path

    @staticmethod
    def load_library():
        return {"books": [], "total": 0}


class _Reader:
    pass


class _Handle:
    def __init__(self):
        self.moves = 0
        self.resizes = []

    def startSystemMove(self):
        self.moves += 1
        return True

    def startSystemResize(self, edge):
        self.resizes.append(edge)
        return True


class _Window(QObject):
    def __init__(self):
        super().__init__()
        self.handle = _Handle()
        self.shown = 0
        self.closed = 0
        self.applied = []
        self.shutdown_count = 0

    @staticmethod
    def isMaximized():
        return False

    def showFloatingReaderWindow(self, settings):
        self.shown += 1
        self.applied.append(dict(settings))

    def closeFloatingReaderWindow(self):
        self.closed += 1

    def applyFloatingReaderSettings(self, settings):
        self.applied.append(dict(settings))

    def floatingWindowHandle(self):
        return self.handle

    def shutdownFloatingReaderWindow(self):
        self.shutdown_count += 1


class Stage4FloatingServiceTests(unittest.TestCase):
    def test_settings_normalize_persist_and_preserve_library(self):
        with tempfile.TemporaryDirectory() as temp:
            library_path = Path(temp) / "library.json"
            library_path.write_text(json.dumps({
                "books": {"kept": {"title": "保留"}},
                "settings": {
                    "floating_reader_opacity": 5,
                    "floating_reader_font_size": 5,
                    "floating_reader_background": "beige",
                },
            }), encoding="utf-8")
            playback = _Playback()
            service = FloatingReaderService(playback, library_path)

            state = service.state()
            self.assertEqual(state["sessionId"], "session-4")
            self.assertEqual(state["bookId"], "book-4")
            self.assertEqual(state["settings"]["opacity"], 1.0)
            self.assertEqual(state["settings"]["fontSize"], 14)
            self.assertEqual(state["settings"]["background"], "sepia")

            state = service.update_settings({
                "opacity": 0.8,
                "fontSize": 28,
                "topmost": False,
                "background": "dark",
            })
            self.assertEqual(state["settings"]["opacity"], 0.8)
            service.update_geometry("600x300-1800+80")
            stored = json.loads(library_path.read_text(encoding="utf-8"))
            self.assertIn("kept", stored["books"])
            self.assertEqual(stored["settings"]["floating_reader_geometry"], "600x300-1800+80")
            self.assertEqual(stored["settings"]["floating_reader_background"], "dark")

    def test_invalid_patch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            service = FloatingReaderService(_Playback(), Path(temp) / "library.json")
            for patch in ({"geometry": "x"}, {"opacity": 0.2}, {"fontSize": True}):
                with self.assertRaises(FloatingReaderError):
                    service.update_settings(patch)

    def test_invalid_library_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            library_path = Path(temp) / "library.json"
            original = b"{broken-library"
            library_path.write_bytes(original)
            service = FloatingReaderService(_Playback(), library_path)

            with self.assertRaises(FloatingReaderError):
                service.update_settings({"fontSize": 24})

            self.assertEqual(library_path.read_bytes(), original)
            self.assertEqual(service.state()["settings"]["fontSize"], 22)

    def test_geometry_is_clamped_to_single_and_negative_screens(self):
        screens = [QRect(0, 0, 1280, 720), QRect(-1920, 0, 1920, 1080)]
        rect = clamp_floating_geometry("600x300-1800+80", screens)
        self.assertEqual(qt_geometry_string(rect), "600x300-1800+80")
        offscreen = clamp_floating_geometry("9000x9000+9000+9000", screens)
        self.assertEqual(offscreen, QRect(0, 0, 1280, 720))

    def test_floating_surface_url_is_frozen(self):
        self.assertEqual(floating_frontend_url().query(), "surface=floating")


class Stage4BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.library_path = Path(self.temp.name) / "library.json"
        self.window = _Window()
        self.playback = _Playback()
        self.bridge = DesktopBridge(
            self.window,
            library=_Library(self.library_path),
            reader=_Reader(),
            playback=self.playback,
        )

    def tearDown(self):
        self.bridge.shutdown()
        self.temp.cleanup()

    @staticmethod
    def _data(raw):
        payload = json.loads(raw)
        if not payload["ok"]:
            raise AssertionError(payload)
        return payload["data"]

    def test_show_update_close_share_playback_and_emit_state(self):
        events = []
        self.bridge.floatingReaderChanged.connect(lambda raw: events.append(json.loads(raw)))
        self.assertGreaterEqual(
            self.bridge.metaObject().indexOfSignal("floatingReaderChanged(QString)"),
            0,
        )

        shown = self._data(self.bridge.showFloatingReader())
        self.assertTrue(shown["visible"])
        self.assertEqual(shown["sessionId"], "session-4")
        self.assertEqual(shown["bookId"], "book-4")
        self.assertEqual(self.window.shown, 1)

        updated = self._data(self.bridge.updateFloatingReaderSettings(json.dumps({
            "patch": {"opacity": 0.75, "topmost": False, "fontSize": 30}
        })))
        self.assertEqual(updated["settings"]["fontSize"], 30)
        self.assertFalse(updated["settings"]["topmost"])
        self.assertGreaterEqual(len(events), 2)

        closed = self._data(self.bridge.closeFloatingReader())
        self.assertTrue(closed["closed"])
        self.assertFalse(self.playback.closed)

    def test_window_move_resize_and_single_drain_path(self):
        self.bridge.startFloatingWindowMove()
        self.bridge.startFloatingWindowResize("bottomRight")
        self.assertEqual(self.window.handle.moves, 1)
        self.assertEqual(len(self.window.handle.resizes), 1)

        self.bridge._drain_reader_events()
        self.assertEqual(self.playback.drain_count, 1)

    def test_shutdown_closes_window_and_only_then_shared_playback(self):
        self.bridge.shutdown()
        self.assertEqual(self.window.shutdown_count, 1)
        self.assertTrue(self.playback.closed)


if __name__ == "__main__":
    unittest.main()
