"""真实桌面（非 offscreen）窗口创建验证。

启动主窗 2.5s 后输出可见性/标题/尺寸并自动退出。
用法：python tests/desktop_smoke.py
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

# 关键：不设置 QT_QPA_PLATFORM=offscreen，使用本机会话真实窗口平台
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from rmqueue.ui.main_window import MainWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1000, 700)
    win.show()

    def report() -> None:
        print(f"visible={win.isVisible()} title={win.windowTitle()!r} "
              f"size={win.width()}x{win.height()}")
        app.quit()

    QTimer.singleShot(2500, report)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
