"""应用入口：Fluent 主窗口。"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme, Theme

from rmqueue.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Render Monitor Queue")
    app.setOrganizationName("RenderMonitorQueue")
    # v1：固定浅色主题，保证自带控件（树表等）在两种系统主题下均清晰可读
    setTheme(Theme.LIGHT)
    window = MainWindow()
    window.show()
    return app.exec()
