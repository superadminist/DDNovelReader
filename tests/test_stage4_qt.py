# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QCoreApplication, QObject, QPoint, QRect, Qt

from novelreader.floating_reader_service import (
    FloatingReaderError,
    FloatingReaderService,
)
from novelreader.qt_bridge import DesktopBridge
from novelreader.qt_host import (
    DesktopWindow,
    FloatingReaderWindow,
    _apply_window_corners,
    _configure_floating_web_view,
    _configure_main_web_view,
    _rounded_window_region,
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
    @staticmethod
    def settings_state():
        return {"fontSize": 31}


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


class _GeometryBridge:
    def __init__(self):
        self.saved = []

    def floatingGeometryChanged(self, geometry):
        self.saved.append(geometry)


class _FloatingGeometryHarness:
    """Exercise the real live-clamp method without starting QtWebEngine."""

    def __init__(self, rect, work_areas):
        self._rect = QRect(rect)
        self._work_areas = work_areas
        self._applying_geometry_clamp = False
        self.bridge = _GeometryBridge()
        self.set_count = 0
        self.recursive_move_timer_started = False

    def geometry(self):
        return QRect(self._rect)

    def _available_work_areas(self):
        return self._work_areas

    def setGeometry(self, rect):
        self.set_count += 1
        self._rect = QRect(rect)
        # A real setGeometry emits move/resize events synchronously.  Record
        # whether the guard would allow those events to restart the timer.
        self.recursive_move_timer_started = not self._applying_geometry_clamp


class Stage4FloatingServiceTests(unittest.TestCase):
    def test_main_and_floating_web_views_use_separate_composition_paths(self):
        class View:
            def __init__(self):
                self.name = ""
                self.attributes = []
                self.style = ""

            def setObjectName(self, name):
                self.name = name

            def setAttribute(self, attribute, enabled):
                self.attributes.append((attribute, enabled))

            def setStyleSheet(self, style):
                self.style = style

        class Page:
            def setBackgroundColor(self, color):
                self.color = color

        main_view, main_page = View(), Page()
        floating_view, floating_page = View(), Page()

        _configure_main_web_view(main_view, main_page)
        _configure_floating_web_view(floating_view, floating_page)

        translucent = Qt.WidgetAttribute.WA_TranslucentBackground
        self.assertEqual(main_view.attributes, [(translucent, True)])
        self.assertEqual(main_page.color.alpha(), 0)
        self.assertIn("background: transparent", main_view.style)
        self.assertEqual(floating_view.attributes, [(translucent, True)])
        self.assertEqual(floating_page.color.alpha(), 0)
        self.assertIn("background: transparent", floating_view.style)

    def test_minimize_to_tray_is_silent(self):
        class Tray:
            @staticmethod
            def isVisible():
                return True

            @staticmethod
            def showMessage(*_args):
                raise AssertionError("minimize-to-tray must not create a notification")

        class Window:
            _tray = Tray()
            hidden = False

            def hide(self):
                self.hidden = True

            def showMinimized(self):
                raise AssertionError("visible tray should use the silent hide path")

        window = Window()
        DesktopWindow.minimizeToTray(window)
        self.assertTrue(window.hidden)

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
            self.assertEqual(state["settings"]["backgroundOpacity"], 1.0)
            self.assertEqual(state["settings"]["fontSize"], 14)
            self.assertEqual(state["settings"]["background"], "sepia")
            self.assertTrue(state["settings"]["hoverDisplayEnabled"])

            state = service.update_settings({
                "backgroundOpacity": 0.8,
                "fontSize": 28,
                "followReaderFont": False,
                "topmost": False,
                "background": "dark",
                "textColor": "#12abEF",
                "hoverDisplayEnabled": False,
            })
            self.assertEqual(state["settings"]["backgroundOpacity"], 0.8)
            self.assertEqual(state["settings"]["textColor"], "#12ABEF")
            self.assertFalse(state["settings"]["followReaderFont"])
            self.assertFalse(state["settings"]["hoverDisplayEnabled"])
            service.update_geometry("600x300-1800+80")
            stored = json.loads(library_path.read_text(encoding="utf-8"))
            self.assertIn("kept", stored["books"])
            self.assertEqual(stored["settings"]["floating_reader_geometry"], "600x300-1800+80")
            self.assertEqual(stored["settings"]["floating_reader_background"], "dark")
            self.assertEqual(stored["settings"]["floating_reader_background_opacity"], 0.8)
            self.assertEqual(stored["settings"]["floating_reader_text_color"], "#12ABEF")
            self.assertFalse(stored["settings"]["floating_reader_follow_font"])
            self.assertFalse(stored["settings"]["floating_reader_hover_display"])

            reloaded = FloatingReaderService(playback, library_path).state()["settings"]
            self.assertEqual(reloaded["backgroundOpacity"], 0.8)
            self.assertEqual(reloaded["fontSize"], 28)
            self.assertEqual(reloaded["textColor"], "#12ABEF")
            self.assertFalse(reloaded["followReaderFont"])
            self.assertFalse(reloaded["hoverDisplayEnabled"])

    def test_invalid_patch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            service = FloatingReaderService(_Playback(), Path(temp) / "library.json")
            for patch in ({"geometry": "x"}, {"backgroundOpacity": -0.01}, {"fontSize": True}, {"textColor": "red"}, {"hoverDisplayEnabled": "yes"}):
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

    def test_windows_10_corner_fallback_is_limited_to_the_opaque_main_window(self):
        class Window:
            def __init__(self, width=1200, height=800):
                self.clear_count = 0
                self.mask_count = 0
                self._width = width
                self._height = height

            def width(self):
                return self._width

            def height(self):
                return self._height

            def clearMask(self):
                self.clear_count += 1

            def setMask(self, mask):
                self.mask_count += 1
                self.mask = mask

        floating = Window()
        main = Window()
        with mock.patch(
            "novelreader.qt_host._set_windows_corner_preference", return_value=False
        ) as preference:
            _apply_window_corners(floating, 30, True)
            _apply_window_corners(main, 22, True)
            _apply_window_corners(main, 22, True)
        self.assertEqual(floating.mask_count, 0)
        self.assertEqual(floating.clear_count, 1)
        self.assertEqual(main.mask_count, 0)
        self.assertEqual(main.clear_count, 1)
        self.assertEqual(preference.call_count, 2)

    def test_rounded_window_region_preserves_edges_and_excludes_corner_pixels(self):
        region = _rounded_window_region(100, 80, 20)
        self.assertTrue(region.contains(QPoint(50, 0)))
        self.assertTrue(region.contains(QPoint(0, 40)))
        self.assertTrue(region.contains(QPoint(50, 40)))
        self.assertFalse(region.contains(QPoint(0, 0)))

    def test_live_persist_clamps_fully_offscreen_geometry_without_recursion(self):
        harness = _FloatingGeometryHarness(
            QRect(9000, 9000, 640, 320),
            [QRect(0, 0, 1280, 720), QRect(-1920, 0, 1920, 1080)],
        )

        FloatingReaderWindow._persist_geometry(harness)

        self.assertEqual(harness.geometry(), QRect(640, 400, 640, 320))
        self.assertEqual(harness.bridge.saved, ["640x320+640+400"])
        self.assertEqual(harness.set_count, 1)
        self.assertFalse(harness.recursive_move_timer_started)


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
        pointer_events = []
        self.bridge.floatingPointerChanged.connect(pointer_events.append)
        self.assertGreaterEqual(
            self.bridge.metaObject().indexOfSignal("floatingReaderChanged(QString)"),
            0,
        )
        self.assertGreaterEqual(
            self.bridge.metaObject().indexOfSignal("floatingPointerChanged(bool)"),
            0,
        )

        shown = self._data(self.bridge.showFloatingReader())
        self.assertTrue(shown["visible"])
        self.assertEqual(shown["sessionId"], "session-4")
        self.assertEqual(shown["bookId"], "book-4")
        self.assertEqual(self.window.shown, 1)

        updated = self._data(self.bridge.updateFloatingReaderSettings(json.dumps({
            "patch": {"backgroundOpacity": 0.75, "topmost": False, "fontSize": 30, "hoverDisplayEnabled": False}
        })))
        self.assertEqual(updated["settings"]["fontSize"], 30)
        self.assertFalse(updated["settings"]["topmost"])
        self.assertFalse(updated["settings"]["hoverDisplayEnabled"])
        self.bridge.floatingPointerChanged.emit(True)
        self.bridge.floatingPointerChanged.emit(False)
        self.assertEqual(pointer_events, [True, False])
        self.assertGreaterEqual(len(events), 2)

        followed = self._data(self.bridge.updateFloatingReaderSettings(json.dumps({
            "patch": {"followReaderFont": True}
        })))
        self.assertTrue(followed["settings"]["followReaderFont"])
        self.assertEqual(followed["settings"]["fontSize"], 31)

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
