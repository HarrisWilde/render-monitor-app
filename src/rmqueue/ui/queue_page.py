"""队列页 v2：现代分组卡片布局。

- 队列操作分组（项目 / 文件 / 勾选）+ 渲染控制（开始/停止）与整体进度条；
- 文件▸场景▸快照 三层树：默认全展开，渲染期不冻结（可滚动查看/勾选，
  勾选只影响后续批次）；每个快照行内嵌独立进度条；
- 渲染选项卡已上移本页：Blender（简短名+浅色路径）、输出目录来源
  （全局 / 跟随项目场景内插件设置）、命名模板；
- 拖放 .blend 时跟随鼠标显示文字提示。
"""

from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QToolTip,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    IndeterminateProgressBar,
    LineEdit,
    MessageBox,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    RoundMenu,
    SubtitleLabel,
    TreeWidget,
)

from .. import blender_tools
from ..naming import DEFAULT_FILE_TEMPLATE
from ..queue import Queue
from .workers import status_text

ROLE_TOKEN = Qt.ItemDataRole.UserRole
_STATUS_COLORS = {
    "PENDING": QColor("#8a8a8a"),
    "RENDERING": QColor("#0078d4"),
    "DONE": QColor("#107c10"),
    "FAILED": QColor("#c42b1c"),
}
_BLENDER_EXE_HINT = (
    "渲染设备/引擎取自快照内保存的项目设置；若在 Blender 中为 GPU，"
    "请用该设置重新捕获快照。")


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path or ""))


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


class _DropHint(QLabel):
    """跟随鼠标的拖放文字提示。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__("松开鼠标：添加 .blend 文件到队列", parent)
        self.setStyleSheet(
            "background: rgba(0, 120, 212, 0.92); color: white;"
            "border-radius: 8px; padding: 8px 16px; font-size: 13px;")
        self.adjustSize()
        self.hide()

    def show_at(self, pos) -> None:
        self.move(int(pos.x()) + 14, int(pos.y()) + 14)
        self.show()
        self.raise_()


class _ShotProgressCell(QWidget):
    """行内快照进度：Fluent 进度条（主题色）+ 固定宽度百分比文本。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 6, 0)
        lay.setSpacing(4)
        self.bar = ProgressBar(self)
        self.bar.setFixedHeight(8)
        self.bar.setUseAni(False)  # 跟随 0.5s tick 直刷，不做 150ms 动画
        self.bar.setFixedWidth(96)
        self.label = QLabel("0%")
        self.label.setAlignment(Qt.AlignmentFlag.AlignRight
                                | Qt.AlignmentFlag.AlignVCenter)
        fm = self.label.fontMetrics()
        self.label.setFixedWidth(fm.horizontalAdvance("100%") + 4)
        self.label.setStyleSheet("color:#808080;font-size:11px;")
        lay.addWidget(self.bar)
        lay.addWidget(self.label)
        self.setFixedWidth(160)
        self.set_fraction(0.0, "PENDING")

    def set_fraction(self, fraction: float, status: str = "RENDERING") -> None:
        frac = max(0.0, min(float(fraction), 1.0))
        # Fluent 条按 val/(max-min) 画宽，默认区间 0..100 → 传 0..100 刻度
        self.bar.setVal(frac * 100)
        # 完成=绿色、失败=错误色、其它=主题色（accent）
        if status == "DONE":
            self.bar.setCustomBarColor(QColor("#0f7b0f"), QColor("#6ccb5f"))
            self.bar.setError(False)
        elif status == "FAILED":
            self.bar.setError(True)
        else:
            self.bar.setCustomBarColor(QColor(), QColor())  # 复位为主题色
            self.bar.setError(False)
        self.label.setText(f"{int(round(frac * 100))}%")


class QueuePage(QWidget):
    filesAdded = Signal(list)
    renderRequested = Signal()
    cancelRequested = Signal()
    openProjectRequested = Signal()
    saveProjectRequested = Signal()
    saveProjectAsRequested = Signal()
    configChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._queue: Queue | None = None
        self._loading = False
        self._installs: list = []
        self._action_buttons: dict = {}
        # 行索引：key=(file,scene,uid) → (item, progressbar)
        self._rows: dict[tuple, tuple] = {}
        self._build_ui()
        self.setAcceptDrops(True)

    # ================================================================== UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # ---- 标题行
        head = QHBoxLayout()
        self.title = SubtitleLabel("渲染队列")
        head.addWidget(self.title)
        self.countLabel = BodyLabel("")
        head.addWidget(self.countLabel)
        head.addStretch(1)
        self.lblPercent = QLabel("0.0%")
        self.lblPercent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        fm = self.lblPercent.fontMetrics()
        self.lblPercent.setFixedWidth(fm.horizontalAdvance("100.0%") + 6)
        # 整体进度：Fluent 细条（主题色）+ 忙碌（Indeterminate）双形态
        self.progressOverall = ProgressBar()
        self.progressOverall.setFixedHeight(10)
        self.progressOverall.setFixedWidth(240)
        self.progressOverall.setUseAni(False)
        self.progressBusy = IndeterminateProgressBar()
        self.progressBusy.setFixedHeight(10)
        self.progressBusy.setFixedWidth(240)
        head.addWidget(self.progressOverall)
        head.addWidget(self.progressBusy)
        head.addWidget(self.lblPercent)
        self.progressOverall.hide()
        self.progressBusy.hide()
        self.lblPercent.hide()
        root.addLayout(head)

        # ---- 队列操作卡片（分组）
        actions = CardWidget(self)
        acts = QHBoxLayout(actions)
        acts.setSpacing(6)
        self._add_group(acts, "项目", [("打开项目", "open"), ("保存项目", "save")])
        self._add_group(acts, "文件", [("添加文件", "add"), ("移除", "remove"),
                                       ("上移", "up"), ("下移", "down")])
        self._add_group(acts, "勾选", [("全选", "all"), ("全不选", "none")])
        acts.addStretch(1)
        self.btnRender = PrimaryPushButton("开始渲染")
        self.btnStop = PushButton("停止渲染")
        self.btnStop.hide()
        acts.addWidget(self.btnRender)
        acts.addWidget(self.btnStop)
        root.addWidget(actions)

        self.workerLabel = BodyLabel("")
        root.addWidget(self.workerLabel)

        # ---- 树（Fluent TreeWidget：自动主题样式，API 与 QTreeWidget 兼容）
        self.tree = TreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["名称", "状态", "进度", "输出 / 说明"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.tree, 1)

        # ---- 渲染选项卡片（在首页）
        opts = CardWidget(self)
        ov = QVBoxLayout(opts)
        ov.setSpacing(8)

        # Blender：标准 Fluent ComboBox（简短名），完整路径显示在右侧灰字
        row1 = QHBoxLayout()
        row1.addWidget(BodyLabel("Blender"))
        self.cmbBlender = ComboBox()
        self.cmbBlender.setMinimumWidth(200)
        row1.addWidget(self.cmbBlender)
        self.lblBlenderPath = QLabel("")
        self.lblBlenderPath.setStyleSheet("color:#808080;font-size:11px;")
        self.lblBlenderPath.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lblBlenderPath.setMinimumWidth(60)
        row1.addWidget(self.lblBlenderPath, 1)
        self.btnBrowseBlender = PushButton("浏览…")
        self.btnRescanBlender = PushButton("重新探测")
        row1.addWidget(self.btnBrowseBlender)
        row1.addWidget(self.btnRescanBlender)
        ov.addLayout(row1)

        # 输出目录来源（下拉即含说明，不再另置灰色小字）
        row2 = QHBoxLayout()
        row2.addWidget(BodyLabel("输出目录"))
        self.cmbSource = ComboBox()
        self.cmbSource.addItem("全局输出目录（下方路径）", userData="global")
        self.cmbSource.addItem("跟随 .blend 场景内插件设置（未设置时用全局）",
                               userData="project")
        row2.addWidget(self.cmbSource)
        self.edOutdir = LineEdit()
        self.edOutdir.setPlaceholderText("全局输出目录（绝对路径）")
        row2.addWidget(self.edOutdir, 1)
        self.btnBrowseOut = PushButton("浏览…")
        row2.addWidget(self.btnBrowseOut)
        ov.addLayout(row2)

        # 命名模板 + “?”（富文本 Tooltip 说明，非自绘）
        row3 = QHBoxLayout()
        row3.addWidget(BodyLabel("命名模板"))
        self.edTemplate = LineEdit()
        self.edTemplate.setText(DEFAULT_FILE_TEMPLATE)
        row3.addWidget(self.edTemplate, 1)
        self.btnTemplateHelp = PushButton("?")
        self.btnTemplateHelp.setFixedSize(30, 30)
        self.btnTemplateHelp.setToolTip("占位符说明")
        self.btnTemplateHelp.clicked.connect(self._show_template_tips)
        row3.addWidget(self.btnTemplateHelp)
        self.btnDefaultTemplate = PushButton("恢复默认")
        row3.addWidget(self.btnDefaultTemplate)
        ov.addLayout(row3)
        root.addWidget(opts)

        # ---- 状态行
        self.statusLabel = BodyLabel("就绪：拖入 .blend 文件开始")
        root.addWidget(self.statusLabel)

        self._dropHint = _DropHint(self)

        # ---- 信号
        self.btnRender.clicked.connect(self.renderRequested)
        self.btnStop.clicked.connect(self.cancelRequested)
        self._wire_action("open", self.openProjectRequested)
        self._wire_action("save", self._on_save)
        self._wire_action("add", self._on_add_files)
        self._wire_action("remove", self._on_remove_file)
        self._wire_action("up", lambda: self._move_file(-1))
        self._wire_action("down", lambda: self._move_file(1))
        self._wire_action("all", lambda: self._set_all_selected(True))
        self._wire_action("none", lambda: self._set_all_selected(False))
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.cmbBlender.currentIndexChanged.connect(self._on_blender_changed)
        self.btnBrowseBlender.clicked.connect(self._browse_blender)
        self.btnRescanBlender.clicked.connect(lambda: self.populate_blender(True))
        self.cmbSource.currentIndexChanged.connect(self._on_config_changed)
        self.edOutdir.textChanged.connect(self._on_config_changed)
        self.edTemplate.textChanged.connect(self._on_config_changed)
        self.btnBrowseOut.clicked.connect(self._browse_outdir)
        self.btnDefaultTemplate.clicked.connect(
            lambda: self.edTemplate.setText(DEFAULT_FILE_TEMPLATE))

    def _add_group(self, layout: QHBoxLayout, title: str,
                   items: list[tuple[str, str]]) -> None:
        lbl = QLabel(title)
        lbl.setStyleSheet("color:#808080;font-size:11px;")
        layout.addWidget(lbl)
        for text, key in items:
            btn = PushButton(text)
            setattr(self, f"btn_{key}", btn)
            layout.addWidget(btn)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setStyleSheet("color:#c0c0c0;")
        layout.addWidget(line)

    def _wire_action(self, key: str, slot) -> None:
        getattr(self, f"btn_{key}").clicked.connect(slot)
        self._action_buttons[key] = getattr(self, f"btn_{key}")

    def _on_save(self) -> None:
        if self._queue and self._queue.files:
            self.saveProjectRequested.emit()
        else:
            self.saveProjectAsRequested.emit()

    # ============================================================ Blender 配置
    def populate_blender(self, keep_current: bool = True) -> None:
        self._installs = blender_tools.blender_installs()
        current = self.blender_exe()
        self.cmbBlender.blockSignals(True)
        try:
            self.cmbBlender.clear()
            for inst in self._installs:
                label = f"Blender {inst.version_str or '（自定义）'}"
                self.cmbBlender.addItem(label, userData=inst.exe)
            if current:
                idx = self._blender_index_of(current)
                if idx >= 0:
                    self.cmbBlender.setCurrentIndex(idx)
                elif self._installs:
                    self.cmbBlender.addItem("自定义 Blender", userData=current)
                    self.cmbBlender.setCurrentIndex(self.cmbBlender.count() - 1)
            elif self._installs:
                self.cmbBlender.setCurrentIndex(0)
        finally:
            self.cmbBlender.blockSignals(False)
        self._on_blender_changed()

    def _blender_index_of(self, exe: str) -> int:
        for i in range(self.cmbBlender.count()):
            if str(self.cmbBlender.itemData(i) or "") == exe:
                return i
        return -1

    def blender_exe(self) -> str:
        return str(self.cmbBlender.currentData() or "")

    def _on_blender_changed(self) -> None:
        exe = self.blender_exe()
        self.lblBlenderPath.setText(exe)
        self.lblBlenderPath.setToolTip(exe)
        self._on_config_changed()

    def _browse_blender(self) -> None:
        if os.name == "nt":
            path, _ = QFileDialog.getOpenFileName(
                self, "选择 blender.exe", r"C:\Program Files\Blender Foundation",
                "Blender (blender.exe)")
        else:
            path, _ = QFileDialog.getOpenFileName(self, "选择 blender", "/", "Blender")
        if path:
            self.cmbBlender.addItem("自定义 Blender", userData=path)
            self.cmbBlender.setCurrentIndex(self.cmbBlender.count() - 1)

    def _browse_outdir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "选择全局输出目录", self.edOutdir.text() or os.path.expanduser("~"))
        if path:
            self.edOutdir.setText(path)

    # ============================================================ 模型
    def set_queue(self, queue: Queue) -> None:
        self._queue = queue
        self.refresh()

    def queue(self) -> Queue | None:
        return self._queue

    def refresh(self) -> None:
        self._loading = True
        self._rows = {}
        try:
            self.tree.clear()
            q = self._queue
            if q is None:
                return
            for f in q.files:
                shots_all = f.all_shots()
                ok = sum(1 for s in shots_all if s.app_status == "DONE")
                file_item = QTreeWidgetItem(
                    [os.path.basename(f.path), f"完成 {ok}/{len(shots_all)}",
                     "", f.path])
                file_item.setFlags(file_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                file_item.setCheckState(0, Qt.CheckState.Checked
                                        if any(s.selected for s in shots_all)
                                        else Qt.CheckState.Unchecked)
                file_item.setToolTip(0, f.path)
                file_item.setData(0, ROLE_TOKEN, ("file", f.path))
                self.tree.addTopLevelItem(file_item)
                for scene in f.scenes:
                    sc_item = QTreeWidgetItem(                        [scene.name, "", "", scene.output_dir or ""])
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
                            "",
                            shot.error or shot.output or shot.blend_output,
                        ])
                        sh_item.setFlags(sh_item.flags()
                                         | Qt.ItemFlag.ItemIsUserCheckable)
                        sh_item.setCheckState(0, Qt.CheckState.Checked
                                              if shot.selected
                                              else Qt.CheckState.Unchecked)
                        sh_item.setData(0, ROLE_TOKEN,
                                        ("shot", f.path, scene.name, shot.uid))
                        sh_item.setForeground(1, QBrush(
                            _STATUS_COLORS.get(shot.app_status,
                                               _STATUS_COLORS["PENDING"])))
                        sh_item.setToolTip(3, shot.output or shot.error or "")
                        sc_item.addChild(sh_item)
                        cell = _ShotProgressCell()
                        cell.set_fraction(1.0 if shot.app_status == "DONE" else 0.0,
                                          shot.app_status)
                        self.tree.setItemWidget(sh_item, 2, cell)
                        key = (_norm(f.path), scene.name, shot.uid)
                        self._rows[key] = (sh_item, cell)
                    sc_item.setExpanded(True)
                file_item.setExpanded(True)
            total = q.total_shots()
            done = sum(1 for f in q.files for s in f.all_shots()
                       if s.app_status == "DONE")
            self.countLabel.setText(f"{len(q.files)} 个文件 · {total} 个快照"
                                    + (f" · {done} 完成" if done else ""))
        finally:
            self._loading = False

    # ============================================================ 交互
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
        # 不要在 itemChanged 信号内同步重建树（删除信号源节点可能崩溃），
        # 延迟到事件循环安全时刻再 refresh
        QTimer.singleShot(0, self.refresh)

    def _set_all_selected(self, value: bool) -> None:
        if self._queue is None:
            return
        for f in self._queue.files:
            for shot in f.all_shots():
                shot.selected = value
        self.refresh()

    def _root_file_index(self, item: QTreeWidgetItem | None) -> int:
        if self._queue is None or item is None:
            return -1
        while item.parent() is not None:
            item = item.parent()
        idx = self.tree.indexOfTopLevelItem(item)
        return idx if 0 <= idx < len(self._queue.files) else -1

    def _move_file(self, delta: int) -> None:
        if self._queue is None:
            return
        idx = self._root_file_index(self.tree.currentItem())
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
        idx = self._root_file_index(self.tree.currentItem())
        if idx < 0:
            self.statusLabel.setText("请先选中要移除的文件")
            return
        f = self._queue.files[idx]

        def _do_remove() -> None:
            del self._queue.files[idx]
            self.refresh()
            self.statusLabel.setText(f"已移除 {os.path.basename(f.path)}")

        box = MessageBox("移除文件", f"从队列移除文件及其全部快照？\n{f.path}", self)
        box.yesButton.setText("移除")
        box.cancelButton.setText("取消")
        box.yesSignal.connect(_do_remove)
        box.exec()

    def _on_add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 .blend 文件", "", "Blender 文件 (*.blend)")
        if paths:
            self.filesAdded.emit(paths)

    def _on_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        menu = RoundMenu(self)
        act_copy = menu.addAction("复制输出路径")
        act_open = menu.addAction("打开所在文件夹")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        output = ""
        token = item.data(0, ROLE_TOKEN)
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

    # ============================================================ 拖放
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if any(u.isLocalFile() and u.toLocalFile().lower().endswith(".blend")
               for u in urls):
            self._dropHint.show_at(event.position())
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            self._dropHint.show_at(event.position())
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._dropHint.hide()
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        self._dropHint.hide()
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile() and u.toLocalFile().lower().endswith(".blend")]
        if paths:
            self.filesAdded.emit(paths)
            event.acceptProposedAction()

    # ============================================================ 渲染状态
    def set_busy(self, busy: bool) -> None:
        """渲染中：禁用结构性操作与选项编辑，但树保持可用（不冻结）。"""
        for key in ("open", "save", "add", "remove", "up", "down",
                    "all", "none"):
            self._action_buttons[key].setEnabled(not busy)
        self.btnRender.setVisible(not busy)
        self.btnStop.setVisible(busy)
        for w in (self.cmbBlender, self.cmbSource, self.edOutdir,
                  self.edTemplate, self.btnBrowseBlender,
                  self.btnBrowseOut, self.btnDefaultTemplate,
                  self.btnRescanBlender):
            w.setEnabled(not busy)
        if busy:
            self.workerLabel.setText("渲染中…")
        else:
            self.workerLabel.setText("")
            self.overall_mode("hidden")

    def overall_mode(self, mode: str) -> None:
        """mode: hidden（无任务）| busy（忙碌动画）| normal（数值进度）"""
        if mode == "hidden":
            self.progressOverall.hide()
            self.progressBusy.hide()
            self.lblPercent.hide()
        elif mode == "busy":
            self.progressOverall.hide()
            self.progressBusy.show()
            self.lblPercent.hide()
        else:  # normal
            self.progressOverall.show()
            self.progressBusy.hide()
            self.lblPercent.show()

    def set_overall(self, value, total: int) -> None:
        """总进度：value=已完成权重（含当前张部分进度，可为浮点），total=批次总数。"""
        if not total or total <= 0:
            return
        frac = max(0.0, min(float(value) / total, 1.0))
        # Fluent 条默认区间 0..100
        self.progressOverall.setVal(frac * 100)
        self.lblPercent.setText(f"{frac * 100:.1f}%")

    def set_worker_text(self, text: str) -> None:
        self.workerLabel.setText(text)

    def set_status(self, text: str) -> None:
        self.statusLabel.setText(text)

    def on_items_tick(self, file_path: str, items: list[dict], done: int,
                      failed: int, total: int) -> None:
        """把子进程逐快照状态/进度刷到对应行（不整树重建，避免闪烁）。"""
        for j in items:
            key = (_norm(file_path), j.get("scene", ""), j.get("uid", ""))
            row = self._rows.get(key)
            if row is None:
                continue
            item, cell = row
            status = j.get("status", "PENDING")
            # 状态列只显示稳定文字（采样/块细节放左下角状态行 + 悬停提示）
            item.setText(1, status_text(status))
            item.setForeground(1, QBrush(_STATUS_COLORS.get(
                status, _STATUS_COLORS["PENDING"])))
            samples = j.get("samples", 0)
            samples_total = j.get("samples_total", 0)
            if status == "RENDERING":
                item.setToolTip(3, f"采样 {samples}/{samples_total}"
                                if samples_total else "渲染中…")
            elif status == "FAILED":
                item.setText(3, j.get("error") or item.text(3))
                item.setToolTip(3, item.text(3))
            elif status == "DONE" and j.get("path"):
                item.setText(3, j.get("path"))
                item.setToolTip(3, j.get("path"))
            frac = 1.0 if status == "DONE" else float(j.get("progress") or 0.0)
            cell.set_fraction(frac, status)

    # ============================================================ 配置
    def _show_template_tips(self) -> None:
        """命名模板占位符说明：系统富文本 Tooltip（非自绘）。"""
        html = (
            "<div style='white-space:nowrap;'>"
            "<b>命名模板占位符</b><hr>"
            "<b>{file}</b>　当前 .blend 文件名（去扩展名）<br>"
            "<b>{scene}</b>　场景名<br>"
            "<b>{name}</b>　快照名<br>"
            "<b>{index}</b>　队列序号，从 1 起（可带格式，如 {index:02d}→07）<br>"
            "<b>{frame}</b>　渲染帧号（可带格式，如 {frame:04d}→0007）<br><hr>"
            "/ 会生成子文件夹；模板不含占位符时自动回退默认模板。</div>")
        pos = self.btnTemplateHelp.mapToGlobal(
            QPoint(0, self.btnTemplateHelp.height() + 8))
        QToolTip.showText(pos, html, self.btnTemplateHelp, msecShowTime=15000)

    def _on_config_changed(self) -> None:
        self.configChanged.emit()

    def config_get(self) -> dict:
        return {
            "blender_exe": self.blender_exe(),
            "output_dir": self.edOutdir.text().strip(),
            "output_source": str(self.cmbSource.currentData() or "global"),
            "file_template": self.edTemplate.text().strip() or DEFAULT_FILE_TEMPLATE,
        }

    def config_set(self, cfg: dict) -> None:
        if cfg.get("blender_exe"):
            self.populate_blender_keep_exe(cfg["blender_exe"])
        self.edOutdir.setText(cfg.get("output_dir", ""))
        if cfg.get("file_template"):
            self.edTemplate.setText(cfg["file_template"])
        for i in range(self.cmbSource.count()):
            if str(self.cmbSource.itemData(i) or "") == cfg.get("output_source", "global"):
                self.cmbSource.setCurrentIndex(i)
                break
        self._on_config_changed()

    def populate_blender_keep_exe(self, exe: str) -> None:
        self.populate_blender(keep_current=True)
        if self.blender_exe() != exe:
            idx = self._blender_index_of(exe)
            if idx >= 0:
                self.cmbBlender.setCurrentIndex(idx)
            else:
                self.cmbBlender.addItem("自定义 Blender", userData=exe)
                self.cmbBlender.setCurrentIndex(self.cmbBlender.count() - 1)
