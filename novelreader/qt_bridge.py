# -*- coding: utf-8 -*-
"""Versioned QWebChannel contract for the Qt desktop host."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot

from . import __version__
from .app_service import AppPreferencesError, AppPreferencesService
from .floating_reader_service import FloatingReaderError, FloatingReaderService
from .import_service import ImportCandidate, ImportServiceError, LibraryImportService
from .library_service import LibraryDataError, LibraryQueryService
from .playback_service import PlaybackService
from .reader_service import ReaderService, ReaderServiceError
from .tts_engine import SpeechController


SCHEMA_VERSION = 1

CAPABILITIES = {
    "fileImport": True,
    "pasteImport": True,
    "webImport": False,
    "audioImport": False,
    "reader": True,
    "tts": True,
    "floatingReader": True,
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


def _safe_import_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ImportServiceError):
        return exc.as_dict()
    LOGGER.exception("Unexpected error in background import", exc_info=exc)
    return {
        "code": "IMPORT_FAILED",
        "message": "导入失败，请检查文件是否完整。",
        "retryable": True,
    }


def _safe_reader_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ReaderServiceError):
        return exc.as_dict()
    if isinstance(exc, (RuntimeError, ValueError)):
        return {
            "code": "INVALID_REQUEST",
            "message": "阅读请求无法执行，请重新打开书籍后重试。",
            "retryable": False,
        }
    LOGGER.exception("Unexpected error in reader request", exc_info=exc)
    return {
        "code": "READER_FAILED",
        "message": "阅读功能暂时不可用，请稍后重试。",
        "retryable": True,
    }


class DesktopBridge(QObject):
    """The only native object exposed to the production frontend."""

    windowStateChanged = Signal(str)
    bridgeError = Signal(str)
    importProgress = Signal(str)
    importFinished = Signal(str)
    readerOpened = Signal(str)
    readerSearchFinished = Signal(str)
    readerPlaybackChanged = Signal(str)
    floatingReaderChanged = Signal(str)
    appPreferencesChanged = Signal(str)

    def __init__(
        self,
        window: Any,
        library: LibraryQueryService | None = None,
        importer: LibraryImportService | None = None,
        reader: ReaderService | None = None,
        playback: PlaybackService | None = None,
        app_preferences: AppPreferencesService | None = None,
        file_picker: Callable[[], list[str]] | None = None,
    ):
        super().__init__(window)
        self._window = window
        self._library = library or LibraryQueryService()
        library_path = getattr(self._library, "path", None)
        self._importer = importer or LibraryImportService(library_path)
        self._reader = reader or ReaderService(library_path)
        self._playback = playback or PlaybackService(SpeechController())
        self._app = app_preferences or AppPreferencesService(library_path)
        self._floating = FloatingReaderService(self._playback, library_path)
        self._file_picker = file_picker or (lambda: [])
        self._selections: dict[str, tuple[ImportCandidate, ...]] = {}
        self._active_job_id = ""
        self._import_cancel: threading.Event | None = None
        self._import_thread: threading.Thread | None = None
        self._import_events: queue.Queue[tuple[str, str, dict[str, Any]]] = queue.Queue()
        self._import_timer = QTimer(self)
        self._import_timer.setInterval(25)
        self._import_timer.timeout.connect(self._drain_import_events)
        self._import_timer.start()
        self._reader_events: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._reader_open_request_id = ""
        self._search_thread: threading.Thread | None = None
        self._search_cancel: threading.Event | None = None
        self._search_request_id = ""
        self._reader_timer = QTimer(self)
        self._reader_timer.setInterval(25)
        self._reader_timer.timeout.connect(self._drain_reader_events)
        self._reader_timer.start()
        self._shutdown = False

    def _state_data(
        self,
        library: dict[str, Any] | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "app": {"version": __version__},
            "library": library or {"books": [], "total": 0},
            "preferences": preferences or {
                "theme": "护眼",
                "colorScheme": "light",
                "autoOpenLast": True,
                "startupBookId": "",
            },
            "window": {"isMaximized": bool(self._window.isMaximized())},
            "capabilities": dict(CAPABILITIES),
        }

    @Slot(result=str)
    def getInitialState(self) -> str:
        try:
            library = self._library.load_library()
            preferences = self._app.state()
        except (LibraryDataError, AppPreferencesError) as exc:
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
            "data": self._state_data(library, preferences),
            "error": None,
        })

    @Slot(result=str)
    def selectImportFiles(self) -> str:
        if self._active_job_id:
            return self._error_response(
                self._empty_selection(),
                "IMPORT_BUSY",
                "已有导入任务正在进行，请稍候。",
            )
        try:
            paths = [str(path) for path in self._file_picker() if path]
            if not paths:
                return self._ok_response(self._empty_selection(cancelled=True))
            candidates = tuple(self._importer.inspect_files(paths))
        except ImportServiceError as exc:
            return self._service_error_response(self._empty_selection(), exc)
        except Exception:
            LOGGER.exception("Unexpected error while selecting import files")
            return self._error_response(
                self._empty_selection(),
                "FILE_SELECTION_FAILED",
                "无法读取所选文件，请重试。",
                retryable=True,
            )

        selection_id = uuid.uuid4().hex
        self._selections.clear()
        self._selections[selection_id] = candidates
        data = {
            "cancelled": False,
            "selectionId": selection_id,
            "total": len(candidates),
            "duplicateCount": sum(candidate.duplicate_exists for candidate in candidates),
            "largeFileCount": sum(candidate.large for candidate in candidates),
            "items": [candidate.public_data() for candidate in candidates],
        }
        return self._ok_response(data)

    @Slot(str, result=str)
    def startFileImport(self, request_json: str) -> str:
        empty = {"jobId": "", "state": "queued"}
        request = self._request_object(request_json)
        if request is None:
            return self._error_response(empty, "INVALID_REQUEST", "导入请求格式不正确。")
        if self._active_job_id:
            return self._error_response(empty, "IMPORT_BUSY", "已有导入任务正在进行，请稍候。")

        selection_id = request.get("selectionId")
        duplicate_mode = request.get("duplicateMode")
        confirm_large_files = request.get("confirmLargeFiles")
        if (
            not isinstance(selection_id, str)
            or duplicate_mode not in {"cancel", "overwrite", "reparse"}
            or not isinstance(confirm_large_files, bool)
        ):
            return self._error_response(empty, "INVALID_REQUEST", "导入请求参数不完整。")
        candidates = self._selections.get(selection_id)
        if candidates is None:
            return self._error_response(empty, "SELECTION_EXPIRED", "文件选择已失效，请重新选择。")
        if any(candidate.large for candidate in candidates) and not confirm_large_files:
            return self._error_response(
                empty,
                "LARGE_FILE_CONFIRMATION_REQUIRED",
                "所选文件中包含超过 25MB 的文件，请确认后再导入。",
            )

        self._selections.pop(selection_id, None)
        importer = self._importer
        return self._start_import_job(
            lambda cancel, progress: importer.import_files(
                list(candidates),
                duplicate_mode,
                confirm_large_files,
                cancel,
                progress,
            ),
            candidates,
        )

    @Slot(str, result=str)
    def startPasteImport(self, request_json: str) -> str:
        empty = {"jobId": "", "state": "queued"}
        request = self._request_object(request_json)
        if request is None:
            return self._error_response(empty, "INVALID_REQUEST", "粘贴导入请求格式不正确。")
        if self._active_job_id:
            return self._error_response(empty, "IMPORT_BUSY", "已有导入任务正在进行，请稍候。")
        title = request.get("title")
        text = request.get("text")
        if not isinstance(title, str) or not isinstance(text, str):
            return self._error_response(empty, "INVALID_REQUEST", "粘贴导入请求参数不完整。")
        if not text.strip():
            return self._error_response(empty, "PASTE_EMPTY", "正文不能为空，请粘贴要朗读的内容。")

        importer = self._importer
        return self._start_import_job(
            lambda cancel, progress: importer.import_pasted_text(
                title,
                text,
                cancel,
                progress,
            ),
            (),
            failure_name=(title.strip() or "粘贴文本"),
        )

    @Slot(str, result=str)
    def cancelImport(self, job_id: str) -> str:
        data = {"jobId": str(job_id or ""), "cancelRequested": False}
        if not job_id or job_id != self._active_job_id or self._import_cancel is None:
            return self._error_response(data, "IMPORT_JOB_NOT_FOUND", "导入任务不存在或已结束。")
        self._import_cancel.set()
        data["cancelRequested"] = True
        return self._ok_response(data)

    @Slot(str, result=str)
    def openReaderBook(self, book_id: str) -> str:
        safe_book_id = str(book_id or "")
        empty = {"requestId": "", "bookId": safe_book_id, "state": "loading"}
        if not safe_book_id:
            return self._error_response(empty, "INVALID_REQUEST", "书籍编号不能为空。")
        if self._reader_open_request_id:
            return self._error_response(empty, "READER_BUSY", "正在打开另一本书，请稍候。")

        request_id = uuid.uuid4().hex
        self._reader_open_request_id = request_id
        events = self._reader_events
        reader = self._reader
        playback = self._playback

        def worker() -> None:
            try:
                data = reader.open_book(safe_book_id)
                content = reader.get_session_content(data["sessionId"])
                settings = data["settings"]
                self._apply_speech_settings(settings)
                data["playback"] = playback.bind_session(
                    data["sessionId"],
                    safe_book_id,
                    content,
                    data["position"]["chapterIndex"],
                    data["position"]["charOffset"],
                )
                event = {
                    "schemaVersion": SCHEMA_VERSION,
                    "requestId": request_id,
                    "bookId": safe_book_id,
                    "ok": True,
                    "data": data,
                    "error": None,
                }
            except Exception as exc:
                event = {
                    "schemaVersion": SCHEMA_VERSION,
                    "requestId": request_id,
                    "bookId": safe_book_id,
                    "ok": False,
                    "data": None,
                    "error": _safe_reader_error(exc),
                }
            events.put(("opened", event))

        self._reader_thread = threading.Thread(
            target=worker,
            name=f"dd-reader-{request_id[:8]}",
            daemon=False,
        )
        self._reader_thread.start()
        return self._ok_response({
            "requestId": request_id,
            "bookId": safe_book_id,
            "state": "loading",
        })

    @Slot(str, result=str)
    def getReaderWindow(self, request_json: str) -> str:
        request = self._request_object(request_json)
        empty = self._empty_reader_window()
        if request is None:
            return self._error_response(empty, "INVALID_REQUEST", "阅读窗口请求格式不正确。")
        try:
            data = self._reader.get_window(
                request.get("sessionId"),
                request.get("chapterIndex"),
                request.get("anchorOffset"),
            )
            return self._ok_response(data)
        except Exception as exc:
            return self._reader_error_response(empty, exc)

    @Slot(str, result=str)
    def navigateReader(self, request_json: str) -> str:
        request = self._request_object(request_json)
        empty = {
            "position": self._empty_position(),
            "window": self._empty_reader_window(),
            "playback": self._playback.snapshot(),
        }
        if request is None:
            return self._error_response(empty, "INVALID_REQUEST", "阅读导航请求格式不正确。")
        try:
            data = self._reader.navigate(request.get("sessionId"), request.get("target"))
            position = data["position"]
            self._playback.set_position(
                position["chapterIndex"], position["charOffset"], restart_playing=True
            )
            data["playback"] = self._playback.snapshot()
            self._emit_floating_state_if_visible()
            return self._ok_response(data)
        except Exception as exc:
            return self._reader_error_response(empty, exc)

    @Slot(str, result=str)
    def updateReaderPosition(self, request_json: str) -> str:
        request = self._request_object(request_json)
        empty = {"updated": False, "position": self._empty_position()}
        if request is None:
            return self._error_response(empty, "INVALID_REQUEST", "阅读进度请求格式不正确。")
        try:
            data = self._reader.update_position(
                request.get("sessionId"),
                request.get("chapterIndex"),
                request.get("charOffset"),
            )
            position = data["position"]
            self._playback.set_position(position["chapterIndex"], position["charOffset"])
            self._emit_floating_state_if_visible()
            return self._ok_response(data)
        except Exception as exc:
            return self._reader_error_response(empty, exc)

    @Slot(str, result=str)
    def searchReader(self, request_json: str) -> str:
        request = self._request_object(request_json)
        empty = {"requestId": "", "state": "searching"}
        if request is None:
            return self._error_response(empty, "INVALID_REQUEST", "搜索请求格式不正确。")
        session_id = request.get("sessionId")
        query = request.get("query")
        cursor = request.get("cursor", "")
        if not isinstance(session_id, str) or not isinstance(query, str) or not isinstance(cursor, str):
            return self._error_response(empty, "INVALID_REQUEST", "搜索请求参数不完整。")

        if self._search_cancel is not None:
            self._search_cancel.set()
        cancel = threading.Event()
        self._search_cancel = cancel
        request_id = uuid.uuid4().hex
        self._search_request_id = request_id
        events = self._reader_events
        reader = self._reader

        def worker() -> None:
            try:
                data = reader.search(session_id, query, cursor, cancel)
                event = {
                    "schemaVersion": SCHEMA_VERSION,
                    "requestId": request_id,
                    "sessionId": session_id,
                    "ok": True,
                    "data": data,
                    "error": None,
                }
            except Exception as exc:
                event = {
                    "schemaVersion": SCHEMA_VERSION,
                    "requestId": request_id,
                    "sessionId": session_id,
                    "ok": False,
                    "data": None,
                    "error": _safe_reader_error(exc),
                }
            events.put(("search", event))

        self._search_thread = threading.Thread(
            target=worker,
            name=f"dd-search-{request_id[:8]}",
            daemon=False,
        )
        self._search_thread.start()
        return self._ok_response({"requestId": request_id, "state": "searching"})

    @Slot(str, result=str)
    def listReaderBookmarks(self, request_json: str) -> str:
        request = self._request_object(request_json)
        empty = {"total": 0, "nextCursor": "", "items": []}
        if request is None:
            return self._error_response(empty, "INVALID_REQUEST", "书签请求格式不正确。")
        try:
            return self._ok_response(self._reader.list_bookmarks(
                request.get("sessionId"), request.get("cursor", "")
            ))
        except Exception as exc:
            return self._reader_error_response(empty, exc)

    @Slot(str, result=str)
    def addReaderBookmark(self, request_json: str) -> str:
        request = self._request_object(request_json)
        empty = self._empty_bookmark()
        if request is None:
            return self._error_response(empty, "INVALID_REQUEST", "书签请求格式不正确。")
        try:
            return self._ok_response(self._reader.add_bookmark(
                request.get("sessionId"),
                request.get("chapterIndex"),
                request.get("startOffset"),
                request.get("endOffset"),
                request.get("note", ""),
            ))
        except Exception as exc:
            return self._reader_error_response(empty, exc)

    @Slot(str, result=str)
    def removeReaderBookmark(self, request_json: str) -> str:
        request = self._request_object(request_json)
        bookmark_id = request.get("bookmarkId", "") if request else ""
        empty = {"bookmarkId": str(bookmark_id or ""), "removed": False}
        if request is None:
            return self._error_response(empty, "INVALID_REQUEST", "删除书签请求格式不正确。")
        try:
            return self._ok_response(self._reader.remove_bookmark(
                request.get("sessionId"), bookmark_id
            ))
        except Exception as exc:
            return self._reader_error_response(empty, exc)

    @Slot(str, result=str)
    def controlReaderPlayback(self, request_json: str) -> str:
        request = self._request_object(request_json)
        empty = {"commandId": "", "accepted": False}
        if request is None:
            return self._error_response(empty, "INVALID_REQUEST", "播放请求格式不正确。")
        try:
            session_id = request.get("sessionId")
            return self._ok_response(self._playback.control(
                request.get("command"), session_id=session_id
            ))
        except Exception as exc:
            return self._reader_error_response(empty, exc)

    @Slot(str, result=str)
    def updateReaderSettings(self, request_json: str) -> str:
        request = self._request_object(request_json)
        empty: dict[str, Any] = {}
        if request is None:
            return self._error_response(empty, "INVALID_REQUEST", "阅读设置请求格式不正确。")
        try:
            data = self._reader.update_settings(request.get("sessionId"), request.get("patch"))
            self._apply_speech_settings(data)
            return self._ok_response(data)
        except Exception as exc:
            return self._reader_error_response(empty, exc)

    @Slot(result=str)
    def getFloatingReaderState(self) -> str:
        return self._ok_response(self._floating.state())

    @Slot(result=str)
    def showFloatingReader(self) -> str:
        try:
            if not self._playback.session_identity().get("sessionId"):
                raise FloatingReaderError("READER_NOT_OPEN", "请先打开一本内容再使用悬浮朗读窗。")
            self._floating.show()
            show = getattr(self._window, "showFloatingReaderWindow", None)
            if not callable(show):
                raise RuntimeError("floating window host is unavailable")
            show(self._floating.state()["settings"])
            state = self._floating.state()
            self._emit_floating_state(state)
            return self._ok_response(state)
        except Exception as exc:
            self._floating.close()
            return self._floating_error_response(self._floating.state(), exc)

    @Slot(result=str)
    def closeFloatingReader(self) -> str:
        try:
            close = getattr(self._window, "closeFloatingReaderWindow", None)
            if callable(close):
                close()
            if self._floating.close():
                self._emit_floating_state()
            return self._ok_response({"closed": True})
        except Exception as exc:
            return self._floating_error_response({"closed": False}, exc)

    @Slot(str, result=str)
    def updateFloatingReaderSettings(self, request_json: str) -> str:
        request = self._request_object(request_json)
        if request is None:
            return self._error_response(
                self._floating.state(),
                "INVALID_REQUEST",
                "悬浮窗设置请求格式不正确。",
            )
        try:
            state = self._floating.update_settings(request.get("patch"))
            apply_settings = getattr(self._window, "applyFloatingReaderSettings", None)
            if callable(apply_settings):
                apply_settings(state["settings"])
            self._emit_floating_state(state)
            return self._ok_response(state)
        except Exception as exc:
            return self._floating_error_response(self._floating.state(), exc)

    @Slot()
    def startFloatingWindowMove(self) -> None:
        handle = self._floating_window_handle()
        if handle is None or not handle.startSystemMove():
            self._emit_error("WINDOW_MOVE_FAILED", "当前系统无法开始拖动悬浮窗。")

    @Slot(str)
    def startFloatingWindowResize(self, edge: str) -> None:
        qt_edge = RESIZE_EDGES.get(edge)
        if qt_edge is None:
            self._emit_error("INVALID_RESIZE_EDGE", "无效的悬浮窗缩放方向。")
            return
        handle = self._floating_window_handle()
        if handle is None or not handle.startSystemResize(qt_edge):
            self._emit_error("WINDOW_RESIZE_FAILED", "当前系统无法开始缩放悬浮窗。")

    def floatingWindowClosed(self) -> None:
        """Handle a user-close without stopping the shared TTS controller."""
        if self._floating.close():
            self._emit_floating_state()

    def floatingGeometryChanged(self, geometry: str) -> None:
        try:
            changed = self._floating.update_geometry(geometry)
        except FloatingReaderError as exc:
            self._emit_error(exc.code, exc.user_message)
            return
        if changed and self._floating.visible:
            self._emit_floating_state()

    @Slot(str, result=str)
    def updateAppPreferences(self, request_json: str) -> str:
        request = self._request_object(request_json)
        if request is None:
            return self._error_response(
                self._state_data()["preferences"],
                "INVALID_REQUEST",
                "应用设置请求格式不正确。",
            )
        try:
            preferences = self._app.update(request.get("patch"))
            self.appPreferencesChanged.emit(_json(preferences))
            return self._ok_response(preferences)
        except AppPreferencesError as exc:
            try:
                current = self._app.state()
            except AppPreferencesError:
                current = self._state_data()["preferences"]
            return self._error_response(
                current, exc.code, exc.user_message, exc.retryable
            )

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
    def toggleFullscreen(self) -> None:
        toggle = getattr(self._window, "toggleFullscreenWindow", None)
        if callable(toggle):
            toggle()
        elif self._window.isFullScreen():
            self._window.showNormal()
        else:
            self._window.showFullScreen()

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

    def shutdownImports(self) -> None:
        if self._import_cancel is not None:
            self._import_cancel.set()
        self._selections.clear()

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self.shutdownImports()
        if self._search_cancel is not None:
            self._search_cancel.set()
        self._reader_timer.stop()
        self._import_timer.stop()
        shutdown_floating = getattr(self._window, "shutdownFloatingReaderWindow", None)
        if callable(shutdown_floating):
            shutdown_floating()
        deadline = time.monotonic() + 2.0
        for thread in (self._import_thread, self._reader_thread, self._search_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        self._playback.shutdown(2.0)

    def _floating_window_handle(self):
        getter = getattr(self._window, "floatingWindowHandle", None)
        return getter() if callable(getter) else None

    def _emit_floating_state_if_visible(self) -> None:
        if self._floating.visible:
            self._emit_floating_state()

    def _emit_floating_state(self, state: dict[str, Any] | None = None) -> None:
        self.floatingReaderChanged.emit(_json({
            "schemaVersion": SCHEMA_VERSION,
            "state": state or self._floating.state(),
        }))

    def _floating_error_response(self, data: dict[str, Any], exc: Exception) -> str:
        if isinstance(exc, FloatingReaderError):
            return self._error_response(
                data, exc.code, exc.user_message, exc.retryable
            )
        LOGGER.exception("Unexpected floating reader failure", exc_info=exc)
        return self._error_response(
            data,
            "FLOATING_READER_FAILED",
            "悬浮朗读窗暂时不可用，请稍后重试。",
            True,
        )

    def _start_import_job(
        self,
        work: Callable[[threading.Event, Callable[[dict[str, Any]], None]], dict[str, Any]],
        candidates: tuple[ImportCandidate, ...],
        failure_name: str = "",
    ) -> str:
        job_id = uuid.uuid4().hex
        cancel_event = threading.Event()
        self._active_job_id = job_id
        self._import_cancel = cancel_event
        event_queue = self._import_events
        candidate_names = [candidate.name for candidate in candidates]

        def progress(payload: dict[str, Any]) -> None:
            event_queue.put(("progress", job_id, payload))

        def worker() -> None:
            try:
                result = work(cancel_event, progress)
            except Exception as exc:
                error = _safe_import_error(exc)
                names = candidate_names
                if not names:
                    names = [failure_name or "导入内容"]
                result = {
                    "state": "cancelled" if cancel_event.is_set() else "completed",
                    "total": len(names),
                    "processed": len(names),
                    "succeeded": 0,
                    "failed": len(names),
                    "lastImportedBookId": "",
                    "openAfterImportBookId": "",
                    "results": [
                        {"name": name, "status": "failed", "bookId": "", "error": error}
                        for name in names
                    ],
                }
            event_queue.put(("finished", job_id, result))

        self._import_thread = threading.Thread(
            target=worker,
            name=f"dd-import-{job_id[:8]}",
            daemon=False,
        )
        self._import_thread.start()
        return self._ok_response({"jobId": job_id, "state": "queued"})

    def _drain_import_events(self) -> None:
        while True:
            try:
                event_type, job_id, payload = self._import_events.get_nowait()
            except queue.Empty:
                return
            event = {"schemaVersion": SCHEMA_VERSION, "jobId": job_id, **payload}
            if event_type == "progress":
                self.importProgress.emit(_json(event))
                continue
            if job_id == self._active_job_id:
                self._active_job_id = ""
                self._import_cancel = None
                self._import_thread = None
            self.importFinished.emit(_json(event))

    def _drain_reader_events(self) -> None:
        while True:
            try:
                event_type, payload = self._reader_events.get_nowait()
            except queue.Empty:
                break
            if event_type == "opened":
                if payload.get("requestId") == self._reader_open_request_id:
                    self._reader_open_request_id = ""
                    self._reader_thread = None
                self.readerOpened.emit(_json(payload))
                self._emit_floating_state_if_visible()
            elif event_type == "search":
                if payload.get("requestId") == self._search_request_id:
                    self._search_thread = None
                    self._search_cancel = None
                    self._search_request_id = ""
                self.readerSearchFinished.emit(_json(payload))

        try:
            events = self._playback.drain_events()
        except RuntimeError:
            return
        for event in events:
            if event.get("reason") in {"sentenceDone", "finished"}:
                position = event.get("playback", {}).get("position", {})
                try:
                    self._reader.update_position(
                        event.get("sessionId"),
                        position.get("chapterIndex"),
                        position.get("charOffset"),
                    )
                except ReaderServiceError as exc:
                    self._emit_error(exc.code, exc.user_message)
            self.readerPlaybackChanged.emit(_json(event))
            self._emit_floating_state_if_visible()

    @staticmethod
    def _request_object(request_json: str) -> dict[str, Any] | None:
        try:
            request = json.loads(request_json)
        except (TypeError, json.JSONDecodeError):
            return None
        return request if isinstance(request, dict) else None

    @staticmethod
    def _empty_selection(cancelled: bool = False) -> dict[str, Any]:
        return {
            "cancelled": cancelled,
            "selectionId": "",
            "total": 0,
            "duplicateCount": 0,
            "largeFileCount": 0,
            "items": [],
        }

    @staticmethod
    def _empty_position() -> dict[str, Any]:
        return {"chapterIndex": 0, "charOffset": 0, "progressPercent": 0.0}

    @staticmethod
    def _empty_reader_window() -> dict[str, Any]:
        return {
            "sessionId": "",
            "bookId": "",
            "chapterIndex": 0,
            "chapterTitle": "",
            "chapterCharCount": 0,
            "anchorOffset": 0,
            "windowStartOffset": 0,
            "windowEndOffset": 0,
            "hasBefore": False,
            "hasAfter": False,
            "blocks": [],
        }

    @staticmethod
    def _empty_bookmark() -> dict[str, Any]:
        return {
            "id": "",
            "chapterIndex": 0,
            "chapterTitle": "",
            "startOffset": 0,
            "endOffset": 0,
            "text": "",
            "note": "",
            "createdAt": 0.0,
        }

    @staticmethod
    def _ok_response(data: dict[str, Any]) -> str:
        return _json({
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "data": data,
            "error": None,
        })

    @staticmethod
    def _error_response(
        data: dict[str, Any],
        code: str,
        message: str,
        retryable: bool = False,
    ) -> str:
        return _json({
            "schemaVersion": SCHEMA_VERSION,
            "ok": False,
            "data": data,
            "error": {"code": code, "message": message, "retryable": retryable},
        })

    @classmethod
    def _service_error_response(cls, data: dict[str, Any], exc: ImportServiceError) -> str:
        return cls._error_response(data, exc.code, exc.user_message, exc.retryable)

    @classmethod
    def _reader_error_response(cls, data: dict[str, Any], exc: Exception) -> str:
        error = _safe_reader_error(exc)
        return cls._error_response(
            data,
            error["code"],
            error["message"],
            error["retryable"],
        )

    def _apply_speech_settings(self, settings: dict[str, Any]) -> None:
        speech = self._playback.speech_controller
        voice_id = settings.get("ttsVoiceId")
        if voice_id:
            speech.set_voice(voice_id)
        speech.set_rate(settings.get("ttsRate", 200))
        speech.set_sentence_gap(settings.get("sentenceGapSeconds", 0.1))
        speech.set_volume(settings.get("volume", 100))

    def _emit_error(self, code: str, message: str) -> None:
        self.bridgeError.emit(_json({
            "schemaVersion": SCHEMA_VERSION,
            "code": code,
            "message": message,
            "retryable": False,
        }))
