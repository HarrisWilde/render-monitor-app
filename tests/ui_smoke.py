"""UI offscreen smoke：QT_QPA_PLATFORM=offscreen 下实例化主窗并验证队列页联动。

用法：python tests/ui_smoke.py
（跳过真实 Blender；只验证控件构造/模型双向同步/渲染前校验路径）
"""

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


def build_queue() -> Queue:
    q = Queue()
    f = QueueFile(path=r"C:\demo\scene.blend")
    f.scenes = [
        QueueScene(name="Scene A", shots=[
            QueueShot(uid="u1", name="A1", selected=True),
            QueueShot(uid="u2", name="A2", selected=False),
            QueueShot(uid="u3", name="A3", selected=True, app_status="DONE",
                      output=r"D:\out\a3.png"),
        ]),
        QueueScene(name="Scene B", shots=[QueueShot(uid="u4", name="B1")]),
    ]
    q.files = [f]
    return q


def main() -> int:
    print("step: qapp", flush=True)
    app = QApplication(sys.argv)
    print("step: win ctor", flush=True)
    win = MainWindow()
    print("step: win ctor done", flush=True)
    win.resize(1000, 700)
    print("step: show", flush=True)
    win.show()
    print("step: shown", flush=True)
    app.processEvents()
    print("step: events1", flush=True)

    # 注入模型 → 树应展示 2 个场景 4 个快照
    print("step: inject model", flush=True)
    q = build_queue()
    win.queue = q
    win.page.set_queue(q)
    top = win.page.tree.topLevelItemCount()
    assert top == 1, top
    root_item = win.page.tree.topLevelItem(0)
    assert root_item.childCount() == 2, root_item.childCount()
    shots_item = root_item.child(0)
    assert shots_item.childCount() == 3
    assert [shots_item.child(i).text(0) for i in range(3)] == ["A1", "A2", "A3"]
    app.processEvents()
    print("step: model injected ok", flush=True)

    # 勾选联动：点场景头 → 全部快照取消勾选
    sc = root_item.child(1)
    from PySide6.QtCore import Qt
    sc.setCheckState(0, Qt.CheckState.Unchecked)
    app.processEvents()
    assert q.shot_by(r"C:\demo\scene.blend", "Scene B", "u4").selected is False
    print("step: scene uncheck ok", flush=True)

    # 全选/全不选（顶栏图标+文字按钮）
    win.page._action_buttons["all"].click()
    app.processEvents()
    assert len(q.flatten_selected()) == 4
    print("step: btn_all ok", flush=True)
    win.page._action_buttons["none"].click()
    app.processEvents()
    assert len(q.flatten_selected()) == 0
    print("step: btn_none ok", flush=True)
    win.page._action_buttons["all"].click()
    app.processEvents()
    print("step: btn_all2 ok", flush=True)

    # 开始渲染的校验路径（显式空配置 → 提示而不启动，防止误起真实渲染）
    win.page.config_set({
        "blender_exe": "", "output_dir": "",
        "output_source": "global", "file_template": "{file}/{scene}/{name} {index}"})
    app.processEvents()
    print("step: config_set ok", flush=True)
    win._start_render()
    app.processEvents()
    assert win._render is None  # 校验失败不应启动
    print("step: start_render guard ok", flush=True)

    # “?”模板帮助（富文本 Tooltip，仅验证不崩溃）
    win.page.btnTemplateHelp.click()
    app.processEvents()
    print("step: template help ok", flush=True)

    # 关闭（若有 worker 残留则先取消等待）
    if win._render is not None:
        win._render.cancel()
        win._render.wait(3000)
    win.close()
    app.processEvents()
    print("UI SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
