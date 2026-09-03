"""应用入口：Fluent 主窗口。"""

from __future__ import annotations

import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from rmqueue.ui.main_window import MainWindow


def _app_icon_path() -> str | None:
    """返回应用图标路径（PyInstaller 包内/开发目录）。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            path = os.path.join(meipass, "icon", "app.ico")
            if os.path.isfile(path):
                return path
        return None

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, "icon", "app.ico")
    return path if os.path.isfile(path) else None


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Render Monitor Queue")
    app.setOrganizationName("RenderMonitorQueue")
    icon_path = _app_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))
    # 主题/强调色在 MainWindow 内处理：默认跟随系统（深浅色），
    # 并读取 Windows 系统强调色作为主题色
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
