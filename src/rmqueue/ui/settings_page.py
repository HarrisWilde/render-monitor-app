"""设置页 v2：通用设置（主题）与关于信息。

渲染相关的 Blender/输出目录/模板已上移到首页「渲染选项」卡。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, CardWidget, ComboBox, SubtitleLabel

from .. import __version__

THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_AUTO = "auto"


class SettingsPage(QWidget):
    themeChanged = Signal(str)  # "light" | "dark" | "auto"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addWidget(SubtitleLabel("设置"))

        # ---- 外观
        appearance = CardWidget(self)
        av = QVBoxLayout(appearance)
        av.addWidget(BodyLabel("外观"))
        form = QFormLayout()
        row = QHBoxLayout()
        self.cmbTheme = ComboBox()
        self.cmbTheme.addItem("跟随系统（默认）", userData=THEME_AUTO)
        self.cmbTheme.addItem("浅色", userData=THEME_LIGHT)
        self.cmbTheme.addItem("深色", userData=THEME_DARK)
        row.addWidget(self.cmbTheme)
        row.addStretch(1)
        form.addRow("主题", row)
        av.addLayout(form)
        root.addWidget(appearance)

        # ---- 关于
        about = CardWidget(self)
        bb = QVBoxLayout(about)
        bb.addWidget(BodyLabel("关于"))
        info = QLabel(
            "Render Monitor Queue 渲染排队器\n"
            f"版本：v{__version__}\n"
            "许可：GPL-2.0-or-later\n"
            "简介：把 Blender-Render-Monitor 插件建好的场景快照拖入排队，"
            "在后台 blender -b 子进程中严格串行批量渲染，UI 不冻结。\n"
            "渲染逻辑复用 vendor/render_monitor 插件包（同 GPL 许可，"
            "源自 github.com/HarrisWilde/Blender-Render-Monitor）。\n"
            "依赖：本机 Blender 4.2+；渲染设备/引擎跟随各快照保存的项目设置。")
        info.setWordWrap(True)
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info.setStyleSheet("color:#606060;font-size:12px;")
        bb.addWidget(info)
        root.addWidget(about)
        root.addStretch(1)

        self.cmbTheme.currentIndexChanged.connect(self._on_theme)

    def _on_theme(self, _index: int = 0) -> None:
        self.themeChanged.emit(self.cmbTheme.currentData())

    def set_theme(self, theme: str) -> None:
        for i in range(self.cmbTheme.count()):
            if str(self.cmbTheme.itemData(i) or "") == theme:
                self.cmbTheme.setCurrentIndex(i)
                break

    def current_theme(self) -> str:
        return str(self.cmbTheme.currentData() or THEME_AUTO)
