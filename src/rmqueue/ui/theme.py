"""UI 小字号/次要文字的主题工具。

持久控件优先使用 QFluentWidgets 自带的 CaptionLabel + setTextColor()，
CaptionLabel 会监听 qconfig.themeChanged 自动切换亮暗色。
本模块只集中管理“次要/说明文字”的亮暗色，并给临时 QSS（如 Flyout）
提供取值。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from qfluentwidgets import CaptionLabel
from qfluentwidgets.common.style_sheet import isDarkTheme

# 与 QFluentWidgets 内部 SecondaryText/CaptionLabel 常见取色一致
SECONDARY_TEXT_LIGHT = QColor("#606060")
SECONDARY_TEXT_DARK = QColor("#cecece")

TEXT_LIGHT = QColor("#252525")
TEXT_DARK = QColor("#e6e6e6")

CHIP_BORDER_LIGHT = QColor("#d0d0d0")
CHIP_BORDER_DARK = QColor("#5a5a5a")


def make_secondary_caption(
        text: str = "", parent=None) -> CaptionLabel:
    """创建只读的 Fluent CaptionLabel（默认不可鼠标选中、无右击菜单）。"""
    label = CaptionLabel(text, parent)
    label.setTextColor(SECONDARY_TEXT_LIGHT, SECONDARY_TEXT_DARK)
    label.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    return label


def current_text_hex() -> str:
    return TEXT_DARK.name() if isDarkTheme() else TEXT_LIGHT.name()


def current_secondary_text_hex() -> str:
    return SECONDARY_TEXT_DARK.name() if isDarkTheme() else SECONDARY_TEXT_LIGHT.name()


def current_chip_border_hex() -> str:
    return CHIP_BORDER_DARK.name() if isDarkTheme() else CHIP_BORDER_LIGHT.name()
