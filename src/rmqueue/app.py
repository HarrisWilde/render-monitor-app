"""应用入口：Fluent 主窗口。"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from rmqueue.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Render Monitor Queue")
    app.setOrganizationName("RenderMonitorQueue")
    # 主题/强调色在 MainWindow 内处理：默认跟随系统（深浅色），
    # 并读取 Windows 系统强调色作为主题色
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
