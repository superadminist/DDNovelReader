# -*- coding: utf-8 -*-
"""多多朗读（DDNovelReader）入口。

负责：
- 自动定位并设置 Tcl/Tk 库路径（源码运行 & exe 打包两种模式）
- 创建主窗口并进入主循环
"""
import os
import sys


def _setup_tcltk():
    """为 tkinter 定位 Tcl/Tk 脚本库。本机 Python 为精简发行版时必需。"""
    current_tcl = os.environ.get("TCL_LIBRARY", "")
    current_tk = os.environ.get("TK_LIBRARY", "")
    if (os.path.isfile(os.path.join(current_tcl, "init.tcl")) and
            os.path.isfile(os.path.join(current_tk, "tk.tcl"))):
        return

    # 无效或不完整的外部配置会阻止 Tcl 自身继续搜索，先清理后统一探测。
    os.environ.pop("TCL_LIBRARY", None)
    os.environ.pop("TK_LIBRARY", None)

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base_prefix = getattr(sys, "base_prefix", sys.prefix)
    candidates = [
        # venv 对应的基础 Python 安装（标准 Windows Python 的 Tcl/Tk 所在位置）
        (os.path.join(base_prefix, "tcl", "tcl8.6"),
         os.path.join(base_prefix, "tcl", "tk8.6")),
        (os.path.join(base_prefix, "Lib", "tcl8.6"),
         os.path.join(base_prefix, "Lib", "tk8.6")),
    ]
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        # 打包程序必须优先使用包内资源，避免依赖目标机器的 Python。
        candidates[0:0] = [
            (os.path.join(base, "tcl8.6"), os.path.join(base, "tk8.6")),
            (os.path.join(base, "tcl", "tcl8.6"), os.path.join(base, "tcl", "tk8.6")),
            (os.path.join(base, "lib", "tcl8.6"), os.path.join(base, "lib", "tk8.6")),
            (os.path.join(base, "_tcl_data"), os.path.join(base, "_tk_data")),
        ]
    else:
        candidates.extend([
            (os.path.join(sys.prefix, "tcl", "tcl8.6"),
             os.path.join(sys.prefix, "tcl", "tk8.6")),
            (os.path.join(here, ".venv", "Lib", "tcl8.6"),
             os.path.join(here, ".venv", "Lib", "tk8.6")),
            (os.path.join(here, "Lib", "tcl8.6"),
             os.path.join(here, "Lib", "tk8.6")),
            (os.path.join(here, "tcl", "tcl8.6"),
             os.path.join(here, "tcl", "tk8.6")),
        ])

    for tcl_dir, tk_dir in candidates:
        if (os.path.isfile(os.path.join(tcl_dir, "init.tcl")) and
                os.path.isfile(os.path.join(tk_dir, "tk.tcl"))):
            os.environ["TCL_LIBRARY"] = os.path.normpath(tcl_dir)
            os.environ["TK_LIBRARY"] = os.path.normpath(tk_dir)
            return


def _enable_dpi_awareness():
    """启用 Windows 高 DPI 感知，保证在不同百分比缩放下文字清晰、控件布局正确。"""
    try:
        import ctypes
        try:
            # PROCESS_SYSTEM_DPI_AWARE：按系统缩放比渲染，tkinter 字号/布局随之缩放
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    except Exception:
        pass


def main():
    _enable_dpi_awareness()
    _setup_tcltk()
    if getattr(sys, "frozen", False):
        BASE = os.path.dirname(sys.executable)
    else:
        BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if BASE not in sys.path:
            sys.path.insert(0, BASE)

    import tkinter as tk

    from novelreader.gui import NovelReaderApp

    # 优先用 tkinterdnd2（原生拖拽，事件在主线程，稳定不闪退）
    # 不可用时降级为普通 Tk，拖拽功能不可用但不影响其他功能
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except Exception:
        root = tk.Tk()
    NovelReaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
