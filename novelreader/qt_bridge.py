# -*- coding: utf-8 -*-
"""Versioned QWebChannel contract for the Qt desktop host."""

from __future__ import annotations

import json
import logging
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal, Slot

from .library_service import LibraryDataError, LibraryQueryService


SCHEMA_VERSION = 1

CAPABILITIES = {
    "fileImport": False,
    "pasteImport": False,
    "webImport": False,
    "audioImport": False,
    "reader": False,
    "tts": False,
    "floatingReader": False,
}

RESIZE_EDGES = {
    "top": Qt.Edge.TopEdge,
    "right": Qt.Edge.RightEdge,
    "bottom": Qt.Edge.BottomEdge,
    "left": Qt.Edge.LeftEdge,
    "topRight": Qt.Edge.TopEdge | Qt.Edge.RightEdge,
    "bottomRight": Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
    "bottomLeft": Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
    "topLeft": Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
}
LOGGER = logging.getLogger(__name__)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class DesktopBridge(QObject):
    """The only native object exposed to the production frontend."""

    windowStateChanged = Signal(str)
    bridgeError = Signal(str)

    def __init__(self, window: Any, library: LibraryQueryService | None = None):
        super().__init__(window)
        self._window = window
        self._library = library or LibraryQueryService()

    def _state_data(self, library: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "library": library or {"books": [], "total": 0},
            "window": {"isMaximized": bool(self._window.isMaximized())},
            "capabilities": dict(CAPABILITIES),
        }

    @Slot(result=str)
    def getInitialState(self) -> str:
        try:
            library = self._library.load_library()
        except LibraryDataError as exc:
            return _json({
                "schemaVersion": SCHEMA_VERSION,
                "ok": False,
                "data": self._state_data(),
                "error": {
                    "code": exc.code,
                    "message": exc.user_message,
                    "retryable": False,
                },
            })
        except Exception:
            LOGGER.exception("Unexpected error while loading the read-only library")
            return _json({
                "schemaVersion": SCHEMA_VERSION,
                "ok": False,
                "data": self._state_data(),
                "error": {
                    "code": "LIBRARY_READ_FAILED",
                    "message": "书架数据读取失败，请稍后重试。",
                    "retryable": True,
                },
            })

        return _json({
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "data": self._state_data(library),
            "error": None,
        })

    @Slot()
    def minimizeWindow(self) -> None:
        self._window.showMinimized()

    @Slot()
    def toggleMaximizeWindow(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    @Slot()
    def closeWindow(self) -> None:
        self._window.close()

    @Slot()
    def startWindowMove(self) -> None:
        handle = self._window.windowHandle()
        if handle is None or not handle.startSystemMove():
            self._emit_error("WINDOW_MOVE_FAILED", "当前系统无法开始拖动窗口。")

    @Slot(str)
    def startWindowResize(self, edge: str) -> None:
        qt_edge = RESIZE_EDGES.get(edge)
        if qt_edge is None:
            self._emit_error("INVALID_RESIZE_EDGE", "无效的窗口缩放方向。")
            return
        handle = self._window.windowHandle()
        if handle is None or not handle.startSystemResize(qt_edge):
            self._emit_error("WINDOW_RESIZE_FAILED", "当前系统无法开始缩放窗口。")

    def emitWindowState(self) -> None:
        self.windowStateChanged.emit(_json({
            "schemaVersion": SCHEMA_VERSION,
            "isMaximized": bool(self._window.isMaximized()),
        }))

    def _emit_error(self, code: str, message: str) -> None:
        self.bridgeError.emit(_json({
            "schemaVersion": SCHEMA_VERSION,
            "code": code,
            "message": message,
            "retryable": False,
        }))
