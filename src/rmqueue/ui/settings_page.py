"""设置页 v2：通用设置（主题/更新）与关于信息。

渲染相关的 Blender/输出目录/模板已上移到首页「渲染选项」卡。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    PushButton,
    SubtitleLabel,
    SwitchButton,
)

from .. import __version__
from .theme import make_secondary_caption

THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_AUTO = "auto"


class SettingsPage(QWidget):
    themeChanged = Signal(str)  # "light" | "dark" | "auto"
    autoCheckChanged = Signal(bool)
    checkUpdateRequested = Signal()
    openReleaseRequested = Signal(str)

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
        form.addRow(BodyLabel("主题"), row)
        av.addLayout(form)
        root.addWidget(appearance)

        # ---- 更新
        update_card = CardWidget(self)
        uv = QVBoxLayout(update_card)
        uv.addWidget(BodyLabel("更新"))

        # 自动检查开关
        auto_row = QHBoxLayout()
        self.swAutoCheck = SwitchButton(self)
        self.swAutoCheck.setOnText("开")
        self.swAutoCheck.setOffText("关")
        auto_row.addWidget(BodyLabel("启动时自动检查更新"))
        auto_row.addStretch(1)
        auto_row.addWidget(self.swAutoCheck)
        uv.addLayout(auto_row)

        # 当前版本 / 最新状态
        uv.addWidget(self._make_info_form())

        # 操作按钮
        btn_row = QHBoxLayout()
        self.btnCheck = PushButton("立即检查")
        self.btnDownload = PushButton("前往下载")
        self.btnDownload.hide()
        btn_row.addWidget(self.btnCheck)
        btn_row.addWidget(self.btnDownload)
        btn_row.addStretch(1)
        uv.addLayout(btn_row)

        # 说明
        tip = make_secondary_caption(
            "每次启动会自动访问 GitHub Releases 检测新版本；"
            "发现新版本后可前往 Release 页面下载安装包。",
            self,
        )
        tip.setWordWrap(True)
        uv.addWidget(tip)

        root.addWidget(update_card)

        # ---- 关于
        about = CardWidget(self)
        bb = QVBoxLayout(about)
        bb.addWidget(BodyLabel("关于"))
        info = make_secondary_caption(
            "Render Monitor Queue 渲染排队器\n"
            f"版本：v{__version__}\n"
            "许可：GPL-2.0-or-later\n"
            "简介：把 Blender-Render-Monitor 插件建好的场景快照拖入排队，"
            "在后台 blender -b 子进程中严格串行批量渲染，UI 不冻结。\n"
            "渲染逻辑复用 vendor/render_monitor 插件包（同 GPL 许可，"
            "源自 github.com/HarrisWilde/Blender-Render-Monitor）。\n"
            "依赖：本机 Blender 4.2+；渲染设备/引擎跟随各快照保存的项目设置。")
        info.setWordWrap(True)
        bb.addWidget(info)
        root.addWidget(about)
        root.addStretch(1)

        # ---- 信号
        self.cmbTheme.currentIndexChanged.connect(self._on_theme)
        self.swAutoCheck.checkedChanged.connect(self._on_auto_check)
        self.btnCheck.clicked.connect(self.checkUpdateRequested)
        self.btnDownload.clicked.connect(self._on_download_clicked)

    # ---- 内部 ----
    def _make_info_form(self) -> QWidget:
        wrap = QWidget(self)
        form = QFormLayout(wrap)
        form.setContentsMargins(0, 0, 0, 0)
        self.lblCurrentVersion = make_secondary_caption(f"v{__version__}", self)
        self.lblUpdateStatus = make_secondary_caption("尚未检查", self)
        form.addRow(BodyLabel("当前版本"), self.lblCurrentVersion)
        form.addRow(BodyLabel("更新状态"), self.lblUpdateStatus)
        return wrap

    def _on_auto_check(self, enabled: bool) -> None:
        self.autoCheckChanged.emit(enabled)

    def _on_download_clicked(self) -> None:
        url = getattr(self, "_latest_url", "")
        if url:
            self.openReleaseRequested.emit(url)

    # ---- 对外状态 ----
    def set_auto_check(self, enabled: bool) -> None:
        self.swAutoCheck.blockSignals(True)
        self.swAutoCheck.setChecked(bool(enabled))
        self.swAutoCheck.blockSignals(False)

    def set_checking(self, checking: bool) -> None:
        self.btnCheck.setEnabled(not checking)
        if checking:
            self.lblUpdateStatus.setText("正在检查新版本…")

    def set_latest_result(self, result: dict) -> None:
        """刷新设置页更新状态。

        result 可来自 updater.check_latest_release() 或失败 dict。
        """
        self._latest_url = ""
        self.btnDownload.hide()
        self.btnCheck.setEnabled(True)
        if not result.get("ok"):
            error = str(result.get("error") or "未知错误")
            self.lblUpdateStatus.setText(f"检查失败：{error}")
            return
        latest = result.get("latest_version") or result.get("latest_tag") or ""
        if result.get("update_available"):
            self.lblUpdateStatus.setText(f"发现新版本 v{latest}")
            self.btnDownload.show()
            self._latest_url = str(result.get("html_url") or "")
        else:
            self.lblUpdateStatus.setText(f"已是最新版本 v{__version__}")

    def current_auto_check(self) -> bool:
        return self.swAutoCheck.isChecked()

    def _on_theme(self, _index: int = 0) -> None:
        self.themeChanged.emit(self.cmbTheme.currentData())

    def set_theme(self, theme: str) -> None:
        for i in range(self.cmbTheme.count()):
            if str(self.cmbTheme.itemData(i) or "") == theme:
                self.cmbTheme.setCurrentIndex(i)
                break

    def current_theme(self) -> str:
        return str(self.cmbTheme.currentData() or THEME_AUTO)
