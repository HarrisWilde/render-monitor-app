"""队列页：文件▸场景▸快照 三层树 + 拖放 + 勾选/排序 + 渲染控制。

模型即 Queue（QueuePage 持有引用并直改），UI 操作写回模型后整树重建，
避免部分刷新带来的状态不同步。
"""

from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton, SubtitleLabel

from ..queue import Queue
from .workers import status_text

ROLE_TOKEN = Qt.ItemDataRole.UserRole
STATUS_COLORS = {
    "PENDING": QColor("#808080"),
    "RENDERING": QColor("#0078d4"),
    "DONE": QColor("#107c10"),
    "FAILED": QColor("#c42b1c"),
}


def _open_folder(path: str) -> None:
    folder = os.path.dirname(path) if os.path.isfile(path) else path
    if not os.path.isdir(folder):
        return
    if sys.platform == "win32":
        os.startfile(folder)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", folder])
    else:
        subprocess.Popen(["xdg-open", folder])


class QueuePage(QWidget):
    filesAdded = Signal(list)          # 需要探针的 .blend 路径
    renderRequested = Signal()
    cancelRequested = Signal()
    openProjectRequested = Signal()
    saveProjectRequested = Signal()
    saveProjectAsRequested = Signal()
    removeFileRequested = Signal(str)  # 绝对路径

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._queue: Queue | None = None
        self._loading = False
        self._build_ui()
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        head = QHBoxLayout()
        self.title = SubtitleLabel("渲染队列")
        head.addWidget(self.title)
        self.countLabel = BodyLabel("")
        head.addWidget(self.countLabel)
        head.addStretch(1)
        root.addLayout(head)

        actions = QHBoxLayout()
        self.btnOpen = PushButton("打开项目")
        self.btnSave = PushButton("保存项目")
        self.btnAdd = PushButton("添加文件")
        self.btnRemove = PushButton("移除文件")
        self.btnUp = PushButton("上移")
        self.btnDown = PushButton("下移")
        self.btnAll = PushButton("全选")
        self.btnNone = PushButton("全不选")
        self.btnRender = PrimaryPushButton("开始渲染")
        self.btnStop = PushButton("停止渲染")
        self.btnStop.hide()
        for b in (self.btnOpen, self.btnSave, self.btnAdd, self.btnRemove,
                  self.btnUp, self.btnDown, self.btnAll, self.btnNone):
            actions.addWidget(b)
        actions.addStretch(1)
        actions.addWidget(self.btnRender)
        actions.addWidget(self.btnStop)
        root.addLayout(actions)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["名称", "状态", "输出 / 说明"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.tree, 1)

        bottom = QHBoxLayout()
        self.statusLabel = BodyLabel("就绪：拖入 .blend 文件开始")
        self.workerLabel = BodyLabel("")
        bottom.addWidget(self.statusLabel, 1)
        bottom.addWidget(self.workerLabel)
        root.addLayout(bottom)

        # 信号
        self.btnOpen.clicked.connect(self.openProjectRequested)
        self.btnSave.clicked.connect(self._on_save)
        self.btnAdd.clicked.connect(self._on_add_files)
        self.btnRemove.clicked.connect(self._on_remove_file)
        self.btnUp.clicked.connect(lambda: self._move_file(-1))
        self.btnDown.clicked.connect(lambda: self._move_file(1))
        self.btnAll.clicked.connect(lambda: self._set_all_selected(True))
        self.btnNone.clicked.connect(lambda: self._set_all_selected(False))
        self.btnRender.clicked.connect(self.renderRequested)
        self.btnStop.clicked.connect(self.cancelRequested)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)

    def _on_save(self) -> None:
        if self._queue and self._queue.files:
            self.saveProjectRequested.emit()
        else:
            self.saveProjectAsRequested.emit()

    # --------------------------------------------------------------- 模型
    def set_queue(self, queue: Queue) -> None:
        self._queue = queue
        self.refresh()

    def queue(self) -> Queue | None:
        return self._queue

    def _root_file(self, item: QTreeWidgetItem | None) -> tuple[QueueFile | None, int]:
        """取 item 所属的顶层文件及其下标。"""
        if self._queue is None or item is None:
            return None, -1
        while item.parent() is not None:
            item = item.parent()
        idx = self.tree.indexOfTopLevelItem(item)
        if 0 <= idx < len(self._queue.files):
            return self._queue.files[idx], idx
        return None, -1

    def refresh(self) -> None:
        """整树重建（从模型读取）。"""
        self._loading = True
        try:
            self.tree.clear()
            if self._queue is None:
                return
            q = self._queue
            for f in q.files:
                finfo = os.path.basename(f.path)
                ok_count = sum(1 for s in f.all_shots()
                               if s.app_status == "DONE")
                file_item = QTreeWidgetItem([finfo,
                                             f"完成 {ok_count}/{len(f.all_shots())}",
                                             f.path])
                file_item.setFlags(file_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                file_item.setCheckState(0, Qt.CheckState.Checked
                                        if any(s.selected for s in f.all_shots())
                                        else Qt.CheckState.Unchecked)
                file_item.setToolTip(0, f.path)
                file_item.setData(0, ROLE_TOKEN, ("file", f.path))
                self.tree.addTopLevelItem(file_item)
                for scene in f.scenes:
                    sc_item = QTreeWidgetItem([scene.name, "", ""])
                    sc_item.setFlags(sc_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    sc_item.setCheckState(0, Qt.CheckState.Checked
                                          if any(s.selected for s in scene.shots)
                                          else Qt.CheckState.Unchecked)
                    sc_item.setData(0, ROLE_TOKEN, ("scene", f.path, scene.name))
                    file_item.addChild(sc_item)
                    for shot in scene.shots:
                        sh_item = QTreeWidgetItem([
                            shot.name,
                            status_text(shot.app_status),
                            shot.error or shot.output or shot.blend_output,
                        ])
                        sh_item.setFlags(sh_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        sh_item.setCheckState(0, Qt.CheckState.Checked
                                              if shot.selected
                                              else Qt.CheckState.Unchecked)
                        sh_item.setData(0, ROLE_TOKEN,
                                        ("shot", f.path, scene.name, shot.uid))
                        brush = QBrush(STATUS_COLORS.get(shot.app_status,
                                                         STATUS_COLORS["PENDING"]))
                        sh_item.setForeground(1, brush)
                        sh_item.setToolTip(2, shot.output or shot.error or "")
                        sc_item.addChild(sh_item)
                file_item.setExpanded(True)
            total = q.total_shots()
            done = sum(1 for f in q.files for s in f.all_shots()
                       if s.app_status == "DONE")
            self.countLabel.setText(f"{len(q.files)} 个文件 · {total} 个快照"
                                    + (f" · {done} 完成" if done else ""))
        finally:
            self._loading = False

    # ------------------------------------------------------------ 交互
    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._loading or column != 0 or self._queue is None:
            return
        token = item.data(0, ROLE_TOKEN)
        if not token:
            return
        checked = item.checkState(0) == Qt.CheckState.Checked
        kind = token[0]
        if kind == "shot":
            shot = self._queue.shot_by(token[1], token[2], token[3])
            if shot is not None:
                shot.selected = checked
        elif kind == "scene":
            f = self._queue.file_by_path(token[1])
            if f is not None:
                for scene in f.scenes:
                    if scene.name == token[2]:
                        for shot in scene.shots:
                            shot.selected = checked
                        break
        elif kind == "file":
            f = self._queue.file_by_path(token[1])
            if f is not None:
                for shot in f.all_shots():
                    shot.selected = checked
        self.refresh()

    def _set_all_selected(self, value: bool) -> None:
        if self._queue is None:
            return
        for f in self._queue.files:
            for shot in f.all_shots():
                shot.selected = value
        self.refresh()

    def _move_file(self, delta: int) -> None:
        if self._queue is None:
            return
        _, idx = self._root_file(self.tree.currentItem())
        new_idx = idx + delta
        if not (0 <= idx < len(self._queue.files)
                and 0 <= new_idx < len(self._queue.files)):
            return
        self._queue.files[idx], self._queue.files[new_idx] = (
            self._queue.files[new_idx], self._queue.files[idx])
        self.refresh()

    def _on_remove_file(self) -> None:
        if self._queue is None:
            return
        f, idx = self._root_file(self.tree.currentItem())
        if f is None:
            self.statusLabel.setText("请先选中要移除的文件")
            return
        if QMessageBox.question(
                self, "移除文件",
                f"从队列移除文件及其全部快照？\n{f.path}",
        ) != QMessageBox.StandardButton.Yes:
            return
        del self._queue.files[idx]
        self.refresh()
        self.statusLabel.setText(f"已移除 {os.path.basename(f.path)}")

    def _on_add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 .blend 文件", "", "Blender 文件 (*.blend)")
        if paths:
            self.filesAdded.emit(paths)

    def _on_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        token = item.data(0, ROLE_TOKEN)
        act_copy = menu.addAction("复制输出路径")
        act_open = menu.addAction("打开所在文件夹")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        output = ""
        if token and token[0] == "shot" and self._queue is not None:
            shot = self._queue.shot_by(token[1], token[2], token[3])
            if shot is not None:
                output = shot.output
        if chosen == act_copy:
            if output:
                QGuiApplication.clipboard().setText(output)
            else:
                self.statusLabel.setText("该快照尚无输出文件")
        elif chosen == act_open:
            if output:
                _open_folder(output)
            else:
                self.statusLabel.setText("该快照尚无输出文件")

    # ---------------------------------------------------------- 拖放
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if any(u.isLocalFile() and u.toLocalFile().lower().endswith(".blend")
               for u in urls):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile() and u.toLocalFile().lower().endswith(".blend")]
        if paths:
            self.filesAdded.emit(paths)
            event.acceptProposedAction()

    # ------------------------------------------------------- 忙碌状态
    def set_busy(self, busy: bool) -> None:
        for w in (self.btnOpen, self.btnSave, self.btnAdd, self.btnRemove,
                  self.btnUp, self.btnDown, self.btnAll, self.btnNone):
            w.setEnabled(not busy)
        self.tree.setEnabled(not busy)
        self.btnRender.setVisible(not busy)
        self.btnStop.setVisible(busy)
        self.btnRender.setEnabled(not busy)
        if busy:
            self.workerLabel.setText("渲染中…")
        else:
            self.workerLabel.setText("")

    def set_worker_text(self, text: str) -> None:
        self.workerLabel.setText(text)

    def set_status(self, text: str) -> None:
        self.statusLabel.setText(text)
