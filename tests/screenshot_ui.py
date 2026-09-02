"""渲染主窗预览图（离屏 grab，无显示环境可用）→ tests/data/ui_preview.png"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from rmqueue.queue import Queue, QueueFile, QueueScene, QueueShot  # noqa: E402
from rmqueue.ui.main_window import MainWindow  # noqa: E402


def demo_queue() -> Queue:
    q = Queue()
    f = QueueFile(path=r"D:\projects\product_01\scene.blend")
    f.scenes = [
        QueueScene(name="产品白底", shots=[
            QueueShot(uid="u1", name="正面", selected=True),
            QueueShot(uid="u2", name="侧面", selected=True, app_status="DONE",
                      output=r"D:\out\product_01\产品白底\侧面_2.png"),
            QueueShot(uid="u3", name="背面", selected=True, app_status="FAILED",
                      error="渲染未生成输出文件（采样不足被取消）"),
        ]),
        QueueScene(name="特写", shots=[
            QueueShot(uid="u4", name="logo 特写", selected=True, app_status="DONE",
                      output=r"D:\out\product_01\特写\logo_特写_4.png"),
        ]),
    ]
    f2 = QueueFile(path=r"D:\projects\layout\layout.blend")
    f2.scenes = [QueueScene(name="Layout", shots=[QueueShot(uid="v1", name="总览", selected=True)])]
    q.files = [f, f2]
    q.settings.output_dir = r"D:\out"
    q.settings.file_template = "{file}/{scene}/{name} {index}"
    return q


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.queue = demo_queue()
    win.page.set_queue(win.queue)
    win.page.set_busy(False)
    win.resize(1180, 760)
    win.show()
    app.processEvents()
    app.processEvents()
    out = os.path.join(_ROOT, "tests", "data", "ui_preview.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ok = win.grab().save(out)
    assert ok, "grab 保存失败"
    print("saved:", out)
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
