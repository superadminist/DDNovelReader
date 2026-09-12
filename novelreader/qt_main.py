# -*- coding: utf-8 -*-
"""Independent entry point for the phase-1 Qt desktop host."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        from .qt_host import DesktopWindow, frontend_index_path
    except ImportError:
        print("[错误] 缺少 PySide6/QtWebEngine，请先安装 requirements.txt 中的依赖。", file=sys.stderr)
        return 2

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("多多朗读")
    app.setOrganizationName("DDNovelReader")

    index_path = frontend_index_path()
    if not index_path.is_file():
        QMessageBox.critical(
            None,
            "多多朗读",
            "未找到前端构建文件。请先构建 prototype/dist/client/index.html。",
        )
        return 3

    window = DesktopWindow()
    window.centerOnPrimaryScreen()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
