# -*- coding: utf-8 -*-
import importlib.util
import json
import sys
import unittest


PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None

if PYSIDE6_AVAILABLE:
    from PySide6.QtCore import QCoreApplication, QObject
    from PySide6.QtTest import QSignalSpy

    from novelreader.library_service import LibraryDataError
    from novelreader.qt_bridge import DesktopBridge, SCHEMA_VERSION


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class DesktopBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])

    def setUp(self):
        class FakeHandle:
            def __init__(self):
                self.moves = 0
                self.resize_edges = []

            def startSystemMove(self):
                self.moves += 1
                return True

            def startSystemResize(self, edge):
                self.resize_edges.append(edge)
                return True

        class FakeWindow(QObject):
            def __init__(self):
                super().__init__()
                self.maximized = False
                self.minimized = False
                self.closed = False
                self.handle = FakeHandle()

            def isMaximized(self):
                return self.maximized

            def showMinimized(self):
                self.minimized = True

            def showMaximized(self):
                self.maximized = True

            def showNormal(self):
                self.maximized = False

            def close(self):
                self.closed = True

            def windowHandle(self):
                return self.handle

        class FakeLibrary:
            def load_library(self):
                return {"books": [{"id": "book-1"}], "total": 1}

        self.window = FakeWindow()
        self.bridge = DesktopBridge(self.window, FakeLibrary())

    def test_initial_state_uses_schema_v1_and_disabled_phase_one_capabilities(self):
        payload = json.loads(self.bridge.getInitialState())
        self.assertEqual(payload["schemaVersion"], SCHEMA_VERSION)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["library"]["total"], 1)
        self.assertFalse(any(payload["data"]["capabilities"].values()))

    def test_library_error_is_a_safe_failure_envelope(self):
        class BrokenLibrary:
            def load_library(self):
                raise LibraryDataError()

        payload = json.loads(DesktopBridge(self.window, BrokenLibrary()).getInitialState())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "LIBRARY_INVALID")
        self.assertEqual(payload["data"]["library"], {"books": [], "total": 0})

    def test_window_controls_delegate_to_the_host(self):
        state_spy = QSignalSpy(self.bridge.windowStateChanged)
        self.bridge.minimizeWindow()
        self.bridge.toggleMaximizeWindow()
        self.bridge.startWindowMove()
        self.bridge.startWindowResize("bottomRight")
        self.bridge.closeWindow()

        self.assertTrue(self.window.minimized)
        self.assertTrue(self.window.maximized)
        self.assertEqual(self.window.handle.moves, 1)
        self.assertEqual(len(self.window.handle.resize_edges), 1)
        self.assertTrue(self.window.closed)
        self.assertEqual(state_spy.count(), 0)

        self.bridge.emitWindowState()
        self.assertEqual(state_spy.count(), 1)

        self.bridge.toggleMaximizeWindow()
        self.assertFalse(self.window.maximized)

    def test_invalid_resize_edge_emits_bridge_error(self):
        error_spy = QSignalSpy(self.bridge.bridgeError)
        self.bridge.startWindowResize("diagonal")
        self.assertEqual(error_spy.count(), 1)
        payload = json.loads(error_spy.at(0)[0])
        self.assertEqual(payload["code"], "INVALID_RESIZE_EDGE")
        self.assertEqual(self.window.handle.resize_edges, [])


if __name__ == "__main__":
    unittest.main()
