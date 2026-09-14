# -*- coding: utf-8 -*-
"""Application preferences shared by the Qt host and React surfaces."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .library_lock import library_write_lock
from .library_service import default_library_path
from .storage import DEFAULT_SETTINGS


APP_THEMES = {"白天", "护眼", "夜间", "米黄"}


class AppPreferencesError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.retryable = retryable


class AppPreferencesService:
    """Read and update existing library settings without changing their keys."""

    def __init__(self, library_path: str | os.PathLike[str] | None = None):
        self.library_path = Path(library_path) if library_path else default_library_path()

    def state(self) -> dict[str, Any]:
        payload = self._load()
        settings = payload.get("settings")
        books = payload.get("books")
        if not isinstance(settings, dict) or not isinstance(books, dict):
            raise AppPreferencesError("LIBRARY_INVALID", "应用设置无法读取，书架数据格式不正确。")
        theme = settings.get("theme", DEFAULT_SETTINGS["theme"])
        if theme not in APP_THEMES:
            theme = DEFAULT_SETTINGS["theme"]
        auto_open = settings.get("auto_open_last", DEFAULT_SETTINGS["auto_open_last"])
        auto_open = auto_open if isinstance(auto_open, bool) else DEFAULT_SETTINGS["auto_open_last"]
        close_to_tray = settings.get("close_to_tray", DEFAULT_SETTINGS["close_to_tray"])
        close_to_tray = (
            close_to_tray
            if isinstance(close_to_tray, bool)
            else DEFAULT_SETTINGS["close_to_tray"]
        )
        last_book = str(settings.get("last_book") or "")
        startup_book = last_book if auto_open and last_book in books else ""
        return {
            "theme": theme,
            "colorScheme": "dark" if theme == "夜间" else "light",
            "autoOpenLast": auto_open,
            "closeToTray": close_to_tray,
            "startupBookId": startup_book,
        }

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        if (
            not isinstance(patch, dict)
            or not patch
            or set(patch) - {"theme", "autoOpenLast", "closeToTray"}
        ):
            raise AppPreferencesError("INVALID_REQUEST", "应用设置参数不正确。")
        updates: dict[str, Any] = {}
        if "theme" in patch:
            theme = patch["theme"]
            if theme not in APP_THEMES:
                raise AppPreferencesError("INVALID_REQUEST", "主题设置不正确。")
            updates["theme"] = theme
        if "autoOpenLast" in patch:
            auto_open = patch["autoOpenLast"]
            if not isinstance(auto_open, bool):
                raise AppPreferencesError("INVALID_REQUEST", "自动续读设置不正确。")
            updates["auto_open_last"] = auto_open
        if "closeToTray" in patch:
            close_to_tray = patch["closeToTray"]
            if not isinstance(close_to_tray, bool):
                raise AppPreferencesError("INVALID_REQUEST", "关闭按钮设置不正确。")
            updates["close_to_tray"] = close_to_tray

        with library_write_lock(self.library_path):
            payload = self._load()
            books = payload.get("books")
            settings = payload.get("settings")
            if not isinstance(books, dict) or not isinstance(settings, dict):
                raise AppPreferencesError("LIBRARY_INVALID", "应用设置无法保存，书架数据格式不正确。")
            settings.update(updates)
            self.library_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.library_path.with_suffix(self.library_path.suffix + ".tmp")
            try:
                with temporary.open("w", encoding="utf-8") as stream:
                    json.dump(payload, stream, ensure_ascii=False, indent=1)
                os.replace(temporary, self.library_path)
            except OSError as exc:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                raise AppPreferencesError(
                    "PREFERENCES_SAVE_FAILED", "应用设置保存失败，请稍后重试。", True
                ) from exc
        return self.state()

    def _load(self) -> dict[str, Any]:
        if not self.library_path.exists():
            return {"books": {}, "settings": dict(DEFAULT_SETTINGS)}
        try:
            with self.library_path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AppPreferencesError("LIBRARY_INVALID", "应用设置无法读取，书架数据格式不正确。") from exc
        if not isinstance(payload, dict):
            raise AppPreferencesError("LIBRARY_INVALID", "应用设置无法读取，书架数据格式不正确。")
        payload.setdefault("books", {})
        payload.setdefault("settings", {})
        return payload
