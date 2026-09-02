"""设置页：Blender 可执行文件、输出目录、文件命名模板。

值保存在 ProjectSettings（随项目）与 QSettings（应用级默认，由 MainWindow
持久化）；本页只负责展示与编辑，任何变更发 settingsChanged 信号。
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    LineEdit,
    PushButton,
    SubtitleLabel,
)

from .. import blender_tools
from ..naming import DEFAULT_FILE_TEMPLATE

_TEMPLATE_HINT = ("占位符：{file} {scene} {name} {index} {frame}；"
                  "如 {file}/{scene}/{name} {index}，/ 表示子目录")


class SettingsPage(QWidget):
    settingsChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(SubtitleLabel("设置"))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Blender（QComboBox 可编辑：支持从探测列表选，也支持手输路径）
        row = QHBoxLayout()
        self.cmbBlender = QComboBox()
        self.cmbBlender.setEditable(True)
        self.cmbBlender.setPlaceholderText("选择或输入 blender 可执行文件路径")
        self.btnBrowseBlender = PushButton("浏览…")
        self.btnRefreshBlender = PushButton("重新探测")
        row.addWidget(self.cmbBlender, 1)
        row.addWidget(self.btnBrowseBlender)
        row.addWidget(self.btnRefreshBlender)
        form.addRow("Blender", row)
        self.lblVersion = BodyLabel("")
        form.addRow("版本", self.lblVersion)

        # 输出目录
        row2 = QHBoxLayout()
        self.edOutdir = LineEdit()
        self.edOutdir.setPlaceholderText("渲染输出目录（绝对路径）")
        self.btnBrowseOut = PushButton("浏览…")
        row2.addWidget(self.edOutdir, 1)
        row2.addWidget(self.btnBrowseOut)
        form.addRow("输出目录", row2)

        # 模板
        self.edTemplate = LineEdit()
        form.addRow("文件模板", self.edTemplate)
        tpl_row = QHBoxLayout()
        hint = BodyLabel(_TEMPLATE_HINT)
        hint.setWordWrap(True)
        tpl_row.addWidget(hint, 1)
        self.btnDefaultTemplate = PushButton("恢复默认")
        tpl_row.addWidget(self.btnDefaultTemplate)
        form.addRow("", tpl_row)

        root.addLayout(form)
        root.addStretch(1)

        self.cmbBlender.currentTextChanged.connect(self._on_blender_text)
        self.cmbBlender.currentIndexChanged.connect(self.settingsChanged)
        self.btnBrowseBlender.clicked.connect(self._browse_blender)
        self.btnRefreshBlender.clicked.connect(self._refresh)
        self.btnBrowseOut.clicked.connect(self._browse_outdir)
        self.btnDefaultTemplate.clicked.connect(self._reset_template)
        self.edOutdir.textChanged.connect(self.settingsChanged)
        self.edTemplate.textChanged.connect(self.settingsChanged)
    # ---------------------------------------------------------- 数据访问
    def blender_exe(self) -> str:
        return self.cmbBlender.currentText().strip().strip('"')

    def outdir(self) -> str:
        return self.edOutdir.text().strip()

    def template(self) -> str:
        return self.edTemplate.text().strip() or DEFAULT_FILE_TEMPLATE

    def set_values(self, blender_exe: str = "", outdir: str = "",
                   template: str = "") -> None:
        if template:
            self.edTemplate.setText(template)
        if outdir:
            self.edOutdir.setText(outdir)
        if blender_exe:
            self.cmbBlender.setCurrentText(blender_exe)
        self._on_blender_text(blender_exe or self.blender_exe())

    # ------------------------------------------------------------ 内部
    def _on_blender_text(self, text: str) -> None:
        ver = blender_tools.parse_blender_version(
            os.path.dirname(text) + os.sep + os.path.basename(text))
        if ver and ver != (0, 0, 0):
            self.lblVersion.setText(f"Blender {'.'.join(map(str, ver))}")
        else:
            self.lblVersion.setText("未识别（渲染时将以子进程方式运行）")
        self.settingsChanged.emit()

    def _browse_blender(self) -> None:
        if os.name == "nt":
            path, _ = QFileDialog.getOpenFileName(
                self, "选择 blender.exe", r"C:\Program Files\Blender Foundation",
                "Blender (blender.exe)")
        else:
            path, _ = QFileDialog.getOpenFileName(self, "选择 blender", "/", "Blender")
        if path:
            self.cmbBlender.setCurrentText(path)
            self._on_blender_text(path)

    def _browse_outdir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "选择输出目录", self.outdir() or os.path.expanduser("~"))
        if path:
            self.edOutdir.setText(path)

    def _reset_template(self) -> None:
        self.edTemplate.setText(DEFAULT_FILE_TEMPLATE)

    def _refresh(self) -> None:
        self.populate_blender(keep_current=True)

    def populate_blender(self, keep_current: bool = True) -> None:
        """用探测结果填充下拉（保留当前选择文本）。"""
        current = self.blender_exe()
        installs = blender_tools.blender_installs()
        self.cmbBlender.blockSignals(True)
        try:
            self.cmbBlender.clear()
            for inst in installs:
                # 条目文本即 exe 路径本身（blender_exe() 直接读 currentText）
                self.cmbBlender.addItem(inst.exe)
            if current:
                self.cmbBlender.setCurrentText(current)
            elif installs:
                self.cmbBlender.setCurrentIndex(0)
        finally:
            self.cmbBlender.blockSignals(False)
        self._on_blender_text(self.blender_exe())
