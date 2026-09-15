# -*- coding: utf-8 -*-
"""Frameless PySide6 host for the production React frontend."""

from __future__ import annotations

import ctypes
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QFile, QIODevice, QRect, QTimer, Qt, QUrl, QUrlQuery
from PySide6.QtGui import QAction, QCloseEvent, QColor, QDesktopServices, QGuiApplication, QIcon, QRegion
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
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMenu, QMessageBox, QSystemTrayIcon

from .book_loader import SUPPORTED_EXTS
from .library_service import LibraryQueryService
from .playback_service import PlaybackService
from .qt_bridge import DesktopBridge
from .reader_service import ReaderService
from .tts_engine import SpeechController


def _qa_trace(message: str) -> None:
    if os.environ.get("DD_QA_TRACE"):
        print(f"[DD_QA_TRACE] {message}", flush=True)


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


def _configure_main_web_view(view: QWebEngineView, page: QWebEnginePage) -> None:
    """Let CSS paint the main window's anti-aliased outer corners."""
    view.setObjectName("mainWebView")
    page.setBackgroundColor(QColor(0, 0, 0, 0))
    view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    view.setStyleSheet("QWebEngineView#mainWebView { background: transparent; }")


def _configure_floating_web_view(view: QWebEngineView, page: QWebEnginePage) -> None:
    """Allow the floating surface to own its user-configurable opacity."""
    view.setObjectName("floatingWebView")
    page.setBackgroundColor(QColor(0, 0, 0, 0))
    view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    view.setStyleSheet("QWebEngineView#floatingWebView { background: transparent; }")


def _set_windows_corner_preference(window: QMainWindow, rounded: bool) -> bool:
    if sys.platform != "win32":
        return False
    try:
        preference = ctypes.c_int(2 if rounded else 1)
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(int(window.winId())),
            33,
            ctypes.byref(preference),
            ctypes.sizeof(preference),
        )
        return result == 0
    except (AttributeError, OSError, ValueError):
        return False


def _rounded_window_region(width: int, height: int, radius: int) -> QRegion:
    """Build a stable rounded region for an opaque Windows 10 top-level window."""
    width = max(1, int(width))
    height = max(1, int(height))
    radius = max(0, min(int(radius), width // 2, height // 2))
    if radius == 0:
        return QRegion(0, 0, width, height)
    diameter = radius * 2
    region = QRegion(radius, 0, width - diameter, height)
    region |= QRegion(0, radius, width, height - diameter)
    ellipse = QRegion.RegionType.Ellipse
    region |= QRegion(0, 0, diameter, diameter, ellipse)
    region |= QRegion(width - diameter, 0, diameter, diameter, ellipse)
    region |= QRegion(0, height - diameter, diameter, diameter, ellipse)
    region |= QRegion(width - diameter, height - diameter, diameter, diameter, ellipse)
    return region


def _suspend_window_corner_mask(window: QMainWindow) -> None:
    if not getattr(window, "_dd_corner_mask_active", False):
        return
    window.clearMask()
    window._dd_corner_mask_active = False
    window._dd_corner_state = None


def _apply_window_corners(
    window: QMainWindow,
    radius: int,
    rounded: bool,
    *,
    allow_opaque_mask: bool = False,
) -> None:
    # resizeEvent fires continuously while the user drags a window edge. On a
    # translucent WebEngine top-level window, repeatedly clearing the mask and
    # asking DWM to re-apply the same preference invalidates the compositor
    # surface and can make the entire window disappear for a frame. Corner mode
    # changes only when entering/leaving maximized or fullscreen state.
    mask_size = (int(window.width()), int(window.height())) if rounded and allow_opaque_mask else None
    corner_state = (bool(rounded), int(radius), bool(allow_opaque_mask), mask_size)
    if getattr(window, "_dd_corner_state", None) == corner_state:
        return
    window._dd_corner_state = corner_state
    if not rounded:
        window.clearMask()
        window._dd_corner_mask_active = False
        _set_windows_corner_preference(window, False)
        return
    if _set_windows_corner_preference(window, True) or not allow_opaque_mask:
        window.clearMask()
        window._dd_corner_mask_active = False
        return
    # Windows 10 has no DWMWA_WINDOW_CORNER_PREFERENCE.  Only the opaque main
    # window uses this fallback, and it is applied after live resize settles so
    # the region never invalidates every compositor frame.  The translucent
    # floating window continues to use its smoother CSS anti-aliased corners.
    window.setMask(_rounded_window_region(window.width(), window.height(), radius))
    window._dd_corner_mask_active = True


class FloatingReaderWindow(QMainWindow):
    """Independent frameless React window sharing the main window's bridge."""

    def __init__(self, bridge: DesktopBridge, profile: QWebEngineProfile):
        super().__init__(None)
        self.bridge = bridge
        self._profile = profile
        self._allow_close = False
        self._applying_geometry_clamp = False
        self._settings: dict = {}
        self.setWindowTitle("启远阅读 - 悬浮朗读")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(360, 220)

        self._view = QWebEngineView(self)
        self._page = QWebEnginePage(profile, self._view)
        self._view.setPage(self._page)
        _configure_floating_web_view(self._view, self._page)
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
        self.bridge.floatingPointerChanged.emit(False)
        self.show()
        _apply_window_corners(self, 30, True)
        if settings.get("topmost", True):
            self.raise_()
        self._persist_geometry()

    def apply_settings(self, settings: dict) -> None:
        self._settings = dict(settings)
        was_visible = self.isVisible()
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint,
            bool(settings.get("topmost", True)),
        )
        if was_visible:
            self.show()
            QTimer.singleShot(0, lambda: _apply_window_corners(self, 30, True))

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
        self.bridge.floatingPointerChanged.emit(False)
        self._persist_geometry()
        self.hide()
        event.ignore()
        self.bridge.floatingWindowClosed()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.bridge.floatingPointerChanged.emit(True)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.bridge.floatingPointerChanged.emit(False)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if (
            hasattr(self, "_geometry_timer")
            and not self._applying_geometry_clamp
        ):
            self._geometry_timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        _apply_window_corners(self, 30, True)
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
        _qa_trace("desktop-window:start")
        self.setWindowTitle("启远阅读")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        # Windows 10 does not honor DWMWA_WINDOW_CORNER_PREFERENCE.  Its
        # binary QRegion mask leaves stair-stepped black triangles around a
        # frameless window, so let the transparent WebEngine/CSS surface own
        # the single anti-aliased clip instead.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("QMainWindow { background: transparent; }")
        self.setMinimumSize(960, 620)
        self._corner_timer = QTimer(self)
        self._corner_timer.setSingleShot(True)
        self._corner_timer.setInterval(140)
        self._corner_timer.timeout.connect(self._sync_window_corners)
        self.resize(1280, 720)
        self._exit_requested = False
        self._tray: QSystemTrayIcon | None = None

        icon_path = application_root() / "assets" / "app.ico"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(os.fspath(icon_path)))

        # Create the view first so its page is destroyed before the custom
        # profile owned by this window.
        self._view = QWebEngineView(self)
        _qa_trace("desktop-window:view-created")
        self._profile = QWebEngineProfile(self)
        self._fullscreen_restore_maximized = False
        self._interceptor = OfflineRequestInterceptor(self._profile)
        self._profile.setUrlRequestInterceptor(self._interceptor)

        self._page = QWebEnginePage(self._profile, self._view)
        _qa_trace("desktop-window:page-created")
        self._view.setPage(self._page)
        _configure_main_web_view(self._view, self._page)
        self._page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            True,
        )

        self._inject_qwebchannel_script()
        library = library or LibraryQueryService()
        self._speech = SpeechController()
        _qa_trace("desktop-window:speech-created")
        self._playback = PlaybackService(self._speech)
        self._reader = ReaderService(library.path)
        self.bridge = DesktopBridge(
            self,
            library,
            reader=self._reader,
            playback=self._playback,
            file_picker=self._select_import_files,
        )
        self._setup_system_tray()
        _qa_trace("desktop-window:bridge-created")
        self._floating_window: FloatingReaderWindow | None = None
        self._channel = QWebChannel(self._page)
        self._channel.registerObject("ddBridge", self.bridge)
        self._page.setWebChannel(self._channel)
        _qa_trace("desktop-window:channel-ready")

        self.setCentralWidget(self._view)
        self._load_error_shown = False
        self._view.loadFinished.connect(self._handle_load_finished)
        index_path = frontend_index_path()
        _qa_trace(f"desktop-window:load:{index_path}:{index_path.is_file()}")
        self._view.setUrl(QUrl.fromLocalFile(os.fspath(index_path)))

    def _handle_load_finished(self, succeeded: bool) -> None:
        _qa_trace(f"desktop-window:load-finished:{succeeded}:{self._view.url().toString()}")
        if succeeded or self._load_error_shown:
            return
        self._load_error_shown = True
        QMessageBox.critical(
            self,
            "启远阅读",
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

    def _setup_system_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = self.windowIcon()
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("启远阅读")
        menu = QMenu(self)
        self._tray_menu = menu
        self._tray_show_action = QAction("显示主界面", menu)
        self._tray_show_action.triggered.connect(self.restoreFromTray)
        self._tray_floating_action = QAction("显示悬浮朗读", menu)
        self._tray_floating_action.triggered.connect(self._toggle_floating_from_tray)
        self._tray_exit_action = QAction("退出", menu)
        self._tray_exit_action.triggered.connect(self.requestApplicationExit)
        menu.addAction(self._tray_show_action)
        menu.addAction(self._tray_floating_action)
        menu.addSeparator()
        menu.addAction(self._tray_exit_action)
        menu.aboutToShow.connect(self._refresh_tray_menu)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._handle_tray_activation)
        self._tray.show()

    def _refresh_tray_menu(self) -> None:
        if not hasattr(self, "_tray_floating_action"):
            return
        visible = bool(self._floating_window and self._floating_window.isVisible())
        self._tray_floating_action.setText("隐藏悬浮朗读" if visible else "显示悬浮朗读")
        identity = self._playback.session_identity()
        self._tray_floating_action.setEnabled(visible or bool(identity.get("sessionId")))

    def _handle_tray_activation(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restoreFromTray()

    def _toggle_floating_from_tray(self) -> None:
        if self._floating_window is not None and self._floating_window.isVisible():
            self.closeFloatingReaderWindow()
            return
        self.bridge.showFloatingReader()

    def minimizeToTray(self) -> None:
        if self._tray is None or not self._tray.isVisible():
            self.showMinimized()
            return
        self.hide()

    def restoreFromTray(self) -> None:
        self.restoreNormalWindow()
        self.raise_()
        self.activateWindow()

    def restoreNormalWindow(self) -> None:
        self.showNormal()
        if sys.platform == "win32" and self.isMaximized():
            # Some translucent frameless Qt windows retain WS_MAXIMIZE after
            # QWidget.showNormal(). Restore the exact top-level HWND once;
            # Windows will use its saved normal placement and notify Qt.
            ctypes.windll.user32.ShowWindow(ctypes.c_void_p(int(self.winId())), 9)
            self.setWindowState(Qt.WindowState.WindowNoState)
            self.bridge.emitWindowState()

    def hideMainForFloating(self) -> None:
        self.hide()

    def requestApplicationExit(self) -> None:
        self._exit_requested = True
        self.close()

    def openExternalUrl(self, url: str) -> bool:
        return bool(QDesktopServices.openUrl(QUrl(url)))

    def launchUpdateInstaller(self, path: str) -> bool:
        installer = Path(path)
        if os.name != "nt" or not installer.is_file() or installer.suffix.lower() != ".exe":
            return False
        os.startfile(os.fspath(installer))
        QTimer.singleShot(500, self.requestApplicationExit)
        return True

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
                self.restoreNormalWindow()
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
        self._exit_requested = True
        if self._tray is not None:
            self._tray.hide()
            self._tray.deleteLater()
        if hasattr(self, "bridge"):
            self.bridge.shutdown()
        super().closeEvent(event)
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "bridge"):
            QTimer.singleShot(0, self._sync_window_corners)
            self.bridge.emitWindowState()
            if self.isMinimized() and self._floating_window is not None:
                self._floating_window.ensure_visible_after_main_minimize()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.isMaximized() or self.isFullScreen():
            self._corner_timer.stop()
            self._sync_window_corners()
            return
        _suspend_window_corner_mask(self)
        self._corner_timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_window_corners)

    def _sync_window_corners(self) -> None:
        rounded = not self.isMaximized() and not self.isFullScreen()
        _apply_window_corners(self, 22, rounded)
