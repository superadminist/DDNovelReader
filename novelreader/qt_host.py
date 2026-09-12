# -*- coding: utf-8 -*-
"""Frameless PySide6 host for the production React frontend."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QFile, QIODevice, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox

from .book_loader import SUPPORTED_EXTS
from .library_service import LibraryQueryService
from .qt_bridge import DesktopBridge


class OfflineRequestInterceptor(QWebEngineUrlRequestInterceptor):
    """Prevent the packaged UI from depending on remote resources."""

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        if info.requestUrl().scheme().lower() in {"http", "https", "ws", "wss"}:
            info.block(True)


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def frontend_index_path() -> Path:
    root = application_root()
    candidates = (
        root / "prototype" / "dist" / "client" / "index.html",
        root / "frontend" / "index.html",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


class DesktopWindow(QMainWindow):
    def __init__(self, library: LibraryQueryService | None = None):
        super().__init__()
        self.setWindowTitle("多多朗读")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(960, 620)
        self.resize(1280, 720)

        icon_path = application_root() / "assets" / "app.ico"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(os.fspath(icon_path)))

        # Create the view first so its page is destroyed before the custom
        # profile owned by this window.
        self._view = QWebEngineView(self)
        self._profile = QWebEngineProfile(self)
        self._interceptor = OfflineRequestInterceptor(self._profile)
        self._profile.setUrlRequestInterceptor(self._interceptor)

        self._page = QWebEnginePage(self._profile, self._view)
        self._view.setPage(self._page)
        self._page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            True,
        )

        self._inject_qwebchannel_script()
        self.bridge = DesktopBridge(self, library, file_picker=self._select_import_files)
        self._channel = QWebChannel(self._page)
        self._channel.registerObject("ddBridge", self.bridge)
        self._page.setWebChannel(self._channel)

        self.setCentralWidget(self._view)
        self._load_error_shown = False
        self._view.loadFinished.connect(self._handle_load_finished)
        self._view.setUrl(QUrl.fromLocalFile(os.fspath(frontend_index_path())))

    def _handle_load_finished(self, succeeded: bool) -> None:
        if succeeded or self._load_error_shown:
            return
        self._load_error_shown = True
        QMessageBox.critical(
            self,
            "多多朗读",
            "前端界面加载失败。请检查 prototype/dist/client 构建文件是否完整。",
        )

    def _inject_qwebchannel_script(self) -> None:
        resource = QFile(":/qtwebchannel/qwebchannel.js")
        if not resource.open(QIODevice.OpenModeFlag.ReadOnly):
            return
        source = bytes(resource.readAll()).decode("utf-8")
        script = QWebEngineScript()
        script.setName("qwebchannel.js")
        script.setSourceCode(source)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        self._page.scripts().insert(script)

    def centerOnPrimaryScreen(self) -> None:
        screen = self.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def _select_import_files(self) -> list[str]:
        patterns = " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_EXTS))
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择要加入书架的小说（可多选）",
            "",
            f"支持的小说格式 ({patterns});;所有文件 (*)",
        )
        return paths

    def closeEvent(self, event: QCloseEvent) -> None:
        if hasattr(self, "bridge"):
            self.bridge.shutdownImports()
        super().closeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "bridge"):
            self.bridge.emitWindowState()
