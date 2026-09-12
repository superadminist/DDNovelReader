# -*- coding: utf-8 -*-
"""Frameless PySide6 host for the production React frontend."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QFile, QIODevice, QRect, QTimer, Qt, QUrl, QUrlQuery
from PySide6.QtGui import QCloseEvent, QGuiApplication, QIcon
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
from .playback_service import PlaybackService
from .qt_bridge import DesktopBridge
from .reader_service import ReaderService
from .tts_engine import SpeechController


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


_GEOMETRY_PATTERN = re.compile(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$")


def clamp_floating_geometry(value: str, work_areas: list[QRect]) -> QRect:
    """Normalize a saved geometry into one of the available screen work areas."""
    areas = [QRect(area) for area in work_areas if area.isValid()]
    if not areas:
        areas = [QRect(0, 0, 1280, 720)]
    primary = areas[0]
    match = _GEOMETRY_PATTERN.fullmatch(str(value or ""))
    if match:
        width, height, x, y = (int(part) for part in match.groups())
    else:
        width, height = 560, 300
        x = primary.right() - width - 31
        y = primary.bottom() - height - 31
    target = next(
        (area for area in areas if area.contains(x + width // 2, y + height // 2)),
        None,
    )
    if target is None:
        candidate = QRect(x, y, max(1, width), max(1, height))
        target = max(
            areas,
            key=lambda area: area.intersected(candidate).width()
            * area.intersected(candidate).height(),
        )
        if not target.intersects(candidate):
            target = primary
    width = min(max(360, width), target.width())
    height = min(max(220, height), target.height())
    x = min(max(x, target.left()), target.right() - width + 1)
    y = min(max(y, target.top()), target.bottom() - height + 1)
    return QRect(x, y, width, height)


def qt_geometry_string(rect: QRect) -> str:
    x = f"+{rect.x()}" if rect.x() >= 0 else str(rect.x())
    y = f"+{rect.y()}" if rect.y() >= 0 else str(rect.y())
    return f"{rect.width()}x{rect.height()}{x}{y}"


def floating_frontend_url() -> QUrl:
    url = QUrl.fromLocalFile(os.fspath(frontend_index_path()))
    query = QUrlQuery()
    query.addQueryItem("surface", "floating")
    url.setQuery(query)
    return url


def _inject_qwebchannel_script(page: QWebEnginePage) -> None:
    resource = QFile(":/qtwebchannel/qwebchannel.js")
    if not resource.open(QIODevice.OpenModeFlag.ReadOnly):
        return
    script = QWebEngineScript()
    script.setName("qwebchannel.js")
    script.setSourceCode(bytes(resource.readAll()).decode("utf-8"))
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(False)
    page.scripts().insert(script)


class FloatingReaderWindow(QMainWindow):
    """Independent frameless React window sharing the main window's bridge."""

    def __init__(self, bridge: DesktopBridge, profile: QWebEngineProfile):
        super().__init__(None)
        self.bridge = bridge
        self._profile = profile
        self._allow_close = False
        self._applying_geometry_clamp = False
        self._settings: dict = {}
        self.setWindowTitle("多多朗读 - 悬浮朗读")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(360, 220)

        self._view = QWebEngineView(self)
        self._page = QWebEnginePage(profile, self._view)
        self._view.setPage(self._page)
        self._page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            True,
        )
        _inject_qwebchannel_script(self._page)
        self._channel = QWebChannel(self._page)
        self._channel.registerObject("ddBridge", bridge)
        self._page.setWebChannel(self._channel)
        self.setCentralWidget(self._view)

        self._view.setUrl(floating_frontend_url())

        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(180)
        self._geometry_timer.timeout.connect(self._persist_geometry)

    def show_with_settings(self, settings: dict) -> None:
        self._settings = dict(settings)
        rect = clamp_floating_geometry(
            settings.get("geometry", ""), self._available_work_areas()
        )
        self.setGeometry(rect)
        self.apply_settings(settings)
        self.show()
        if settings.get("topmost", True):
            self.raise_()
        self._persist_geometry()

    def apply_settings(self, settings: dict) -> None:
        self._settings = dict(settings)
        was_visible = self.isVisible()
        self.setWindowOpacity(float(settings.get("opacity", 0.92)))
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint,
            bool(settings.get("topmost", True)),
        )
        if was_visible:
            self.show()

    def ensure_visible_after_main_minimize(self) -> None:
        if self.isVisible():
            self.show()
            if self._settings.get("topmost", True):
                self.raise_()

    def shutdown(self) -> None:
        self._geometry_timer.stop()
        if self.isVisible():
            self._persist_geometry()
        self._allow_close = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close:
            event.accept()
            return
        self._geometry_timer.stop()
        self._persist_geometry()
        self.hide()
        event.ignore()
        self.bridge.floatingWindowClosed()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if (
            hasattr(self, "_geometry_timer")
            and not self._applying_geometry_clamp
        ):
            self._geometry_timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if (
            hasattr(self, "_geometry_timer")
            and not self._applying_geometry_clamp
        ):
            self._geometry_timer.start()

    def _persist_geometry(self) -> None:
        rect = clamp_floating_geometry(
            qt_geometry_string(self.geometry()), self._available_work_areas()
        )
        if rect != self.geometry():
            self._applying_geometry_clamp = True
            try:
                self.setGeometry(rect)
            finally:
                self._applying_geometry_clamp = False
        self.bridge.floatingGeometryChanged(qt_geometry_string(rect))

    def _available_work_areas(self) -> list[QRect]:
        screen = self.screen()
        screens = screen.virtualSiblings() if screen is not None else QGuiApplication.screens()
        return [item.availableGeometry() for item in screens]


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
        self._fullscreen_restore_maximized = False
        self._interceptor = OfflineRequestInterceptor(self._profile)
        self._profile.setUrlRequestInterceptor(self._interceptor)

        self._page = QWebEnginePage(self._profile, self._view)
        self._view.setPage(self._page)
        self._page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            True,
        )

        self._inject_qwebchannel_script()
        library = library or LibraryQueryService()
        self._speech = SpeechController()
        self._playback = PlaybackService(self._speech)
        self._reader = ReaderService(library.path)
        self.bridge = DesktopBridge(
            self,
            library,
            reader=self._reader,
            playback=self._playback,
            file_picker=self._select_import_files,
        )
        self._floating_window: FloatingReaderWindow | None = None
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
        _inject_qwebchannel_script(self._page)

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

    def showFloatingReaderWindow(self, settings: dict) -> None:
        if self._floating_window is None:
            self._floating_window = FloatingReaderWindow(self.bridge, self._profile)
        self._floating_window.show_with_settings(settings)

    def closeFloatingReaderWindow(self) -> None:
        if self._floating_window is not None and self._floating_window.isVisible():
            self._floating_window.close()

    def applyFloatingReaderSettings(self, settings: dict) -> None:
        if self._floating_window is not None:
            self._floating_window.apply_settings(settings)

    def floatingWindowHandle(self):
        if self._floating_window is None or not self._floating_window.isVisible():
            return None
        return self._floating_window.windowHandle()

    def toggleFullscreenWindow(self) -> None:
        if self.isFullScreen():
            if self._fullscreen_restore_maximized:
                self.showMaximized()
            else:
                self.showNormal()
            return
        self._fullscreen_restore_maximized = self.isMaximized()
        self.showFullScreen()

    def shutdownFloatingReaderWindow(self) -> None:
        if self._floating_window is None:
            return
        window = self._floating_window
        self._floating_window = None
        window.shutdown()
        window.deleteLater()

    def closeEvent(self, event: QCloseEvent) -> None:
        if hasattr(self, "bridge"):
            self.bridge.shutdown()
        super().closeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "bridge"):
            self.bridge.emitWindowState()
            if self.isMinimized() and self._floating_window is not None:
                self._floating_window.ensure_visible_after_main_minimize()
