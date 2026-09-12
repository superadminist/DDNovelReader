# -*- coding: utf-8 -*-
"""Small Win32 probe used by the stage-4 real-Qt acceptance driver.

The helper deliberately lives outside production code.  It observes and moves
only top-level windows that belong to the explicitly supplied Qt host PID.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes


if sys.platform != "win32":
    raise SystemExit("stage4_window_probe.py requires Windows")


user32 = ctypes.WinDLL("user32", use_last_error=True)

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
SW_RESTORE = 9
SW_MINIMIZE = 6
SWP_NOACTIVATE = 0x0010
SWP_NOZORDER = 0x0004
MONITOR_DEFAULTTONEAREST = 2


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(RECT),
    wintypes.LPARAM,
)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(RECT), MONITORENUMPROC, wintypes.LPARAM]
user32.EnumDisplayMonitors.restype = wintypes.BOOL
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
user32.mouse_event.restype = None


def _rect_payload(rect: RECT) -> dict[str, int]:
    return {
        "left": int(rect.left),
        "top": int(rect.top),
        "right": int(rect.right),
        "bottom": int(rect.bottom),
        "width": int(rect.right - rect.left),
        "height": int(rect.bottom - rect.top),
    }


def _text(hwnd: int, getter, length_getter=None) -> str:
    length = int(length_getter(hwnd)) if length_getter else 255
    buffer = ctypes.create_unicode_buffer(max(1, length + 1))
    getter(hwnd, buffer, len(buffer))
    return buffer.value


def _windows(pid: int) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []

    @WNDENUMPROC
    def callback(hwnd, _lparam):
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if int(owner_pid.value) != pid:
            return True
        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        visible = bool(user32.IsWindowVisible(hwnd))
        iconic = bool(user32.IsIconic(hwnd))
        payload = _rect_payload(rect)
        if payload["width"] <= 0 or payload["height"] <= 0:
            return True
        ex_style = int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
        found.append({
            "hwnd": int(hwnd),
            "title": _text(hwnd, user32.GetWindowTextW, user32.GetWindowTextLengthW),
            "className": _text(hwnd, user32.GetClassNameW),
            "visible": visible,
            "minimized": iconic,
            "topmost": bool(ex_style & WS_EX_TOPMOST),
            "rect": payload,
        })
        return True

    if not user32.EnumWindows(callback, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return found


def _monitors() -> list[dict[str, object]]:
    found: list[dict[str, object]] = []

    @MONITORENUMPROC
    def callback(handle, _hdc, _rect, _lparam):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            found.append({
                "handle": int(handle),
                "primary": bool(info.dwFlags & 1),
                "monitor": _rect_payload(info.rcMonitor),
                "work": _rect_payload(info.rcWork),
            })
        return True

    if not user32.EnumDisplayMonitors(0, None, callback, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return found


def _with_roles(items: list[dict[str, object]]) -> list[dict[str, object]]:
    candidates = [item for item in items if item["visible"] or item["minimized"]]
    main = next((item for item in candidates if item["title"] == "多多朗读"), None)
    floating = next((item for item in candidates if "悬浮" in str(item["title"])), None)
    if main is None and candidates:
        main = max(candidates, key=lambda item: item["rect"]["width"] * item["rect"]["height"])
    if floating is None:
        remainder = [item for item in candidates if item is not main]
        if remainder:
            floating = max(remainder, key=lambda item: item["rect"]["width"] * item["rect"]["height"])
    for item in items:
        item["role"] = "main" if item is main else "floating" if item is floating else "other"
    return items


def snapshot(pid: int) -> dict[str, object]:
    return {
        "pid": pid,
        "windows": _with_roles(_windows(pid)),
        "monitors": _monitors(),
    }


def _role_window(pid: int, role: str) -> dict[str, object]:
    result = snapshot(pid)
    item = next((entry for entry in result["windows"] if entry["role"] == role), None)
    if item is None:
        raise RuntimeError(f"No {role} top-level window for PID {pid}")
    return item


def _show(pid: int, role: str, command: int) -> None:
    item = _role_window(pid, role)
    if not user32.ShowWindow(item["hwnd"], command):
        # ShowWindow returns the previous visibility state, not an error flag.
        ctypes.set_last_error(0)


def _place(pid: int, role: str, x: int, y: int, width: int, height: int) -> None:
    item = _role_window(pid, role)
    if not user32.SetWindowPos(
        item["hwnd"],
        0,
        x,
        y,
        width,
        height,
        SWP_NOACTIVATE | SWP_NOZORDER,
    ):
        raise ctypes.WinError(ctypes.get_last_error())


def _drag(pid: int, role: str, local_x: int, local_y: int, delta_x: int, delta_y: int) -> None:
    item = _role_window(pid, role)
    point = POINT(local_x, local_y)
    if not user32.ClientToScreen(item["hwnd"], ctypes.byref(point)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not user32.SetCursorPos(point.x, point.y):
        raise ctypes.WinError(ctypes.get_last_error())
    time.sleep(0.08)
    user32.mouse_event(0x0002, 0, 0, 0, None)  # MOUSEEVENTF_LEFTDOWN
    time.sleep(0.08)
    if not user32.SetCursorPos(point.x + delta_x, point.y + delta_y):
        user32.mouse_event(0x0004, 0, 0, 0, None)
        raise ctypes.WinError(ctypes.get_last_error())
    time.sleep(0.18)
    user32.mouse_event(0x0004, 0, 0, 0, None)  # MOUSEEVENTF_LEFTUP
    time.sleep(0.12)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("snapshot", "restore", "minimize", "place", "drag"))
    parser.add_argument("pid", type=int)
    parser.add_argument("--role", choices=("main", "floating"), default="floating")
    parser.add_argument("--x", type=int, default=0)
    parser.add_argument("--y", type=int, default=0)
    parser.add_argument("--width", type=int, default=520)
    parser.add_argument("--height", type=int, default=280)
    parser.add_argument("--from-x", type=int, default=80)
    parser.add_argument("--from-y", type=int, default=24)
    parser.add_argument("--dx", type=int, default=80)
    parser.add_argument("--dy", type=int, default=40)
    args = parser.parse_args()

    if args.action == "restore":
        _show(args.pid, args.role, SW_RESTORE)
    elif args.action == "minimize":
        _show(args.pid, args.role, SW_MINIMIZE)
    elif args.action == "place":
        _place(args.pid, args.role, args.x, args.y, args.width, args.height)
    elif args.action == "drag":
        _drag(args.pid, args.role, args.from_x, args.from_y, args.dx, args.dy)
    # ASCII escaping keeps the JSON transport stable when a Windows child
    # process inherits a non-UTF-8 console code page.
    print(json.dumps(snapshot(args.pid), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
