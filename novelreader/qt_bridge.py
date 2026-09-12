# -*- coding: utf-8 -*-
"""Versioned QWebChannel contract for the Qt desktop host."""

from __future__ import annotations

import json
import logging
import queue
import threading
import uuid
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot

from .import_service import ImportCandidate, ImportServiceError, LibraryImportService
from .library_service import LibraryDataError, LibraryQueryService


SCHEMA_VERSION = 1

CAPABILITIES = {
    "fileImport": True,
    "pasteImport": True,
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


def _safe_import_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ImportServiceError):
        return exc.as_dict()
    LOGGER.exception("Unexpected error in background import", exc_info=exc)
    return {
        "code": "IMPORT_FAILED",
        "message": "导入失败，请检查文件是否完整。",
        "retryable": True,
    }


class DesktopBridge(QObject):
    """The only native object exposed to the production frontend."""

    windowStateChanged = Signal(str)
    bridgeError = Signal(str)
    importProgress = Signal(str)
    importFinished = Signal(str)

    def __init__(
        self,
        window: Any,
        library: LibraryQueryService | None = None,
        importer: LibraryImportService | None = None,
        file_picker: Callable[[], list[str]] | None = None,
    ):
        super().__init__(window)
        self._window = window
        self._library = library or LibraryQueryService()
        library_path = getattr(self._library, "path", None)
        self._importer = importer or LibraryImportService(library_path)
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
        self.shutdownImports()
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

    def _emit_error(self, code: str, message: str) -> None:
        self.bridgeError.emit(_json({
            "schemaVersion": SCHEMA_VERSION,
            "code": code,
            "message": message,
            "retryable": False,
        }))
