"""自绘 UI 小部件：富两行下拉选择器 + 卡片风格浮窗/提示。

qfluentwidgets 的 ComboBox 只支持单行文本项，无法做「主行简短名 + 灰字全路径」；
这里用 Fluent PushButton + Qt.Popup 实现等价交互（观感一致的富下拉），
并提供「? 帮助浮窗」的卡片容器与占位符说明内容。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, PushButton
from qfluentwidgets.common.style_sheet import isDarkTheme

_ACCENT = "#0078d4"


def card_colors() -> tuple[str, str, str]:
    """返回 (卡片背景, 主文字, 次文字) 依当前深浅主题。"""
    if isDarkTheme():
        return "#2b2b2b", "#e6e6e6", "#8f8f8f"
    return "#ffffff", "#242424", "#808080"


def apply_card_style(widget: QWidget) -> None:
    bg, text, sub = card_colors()
    widget.setStyleSheet(
        f"QWidget#card {{ background: {bg}; border: 1px solid rgba(127,127,127,60%);"
        f" border-radius: 8px; }}"
        f"QLabel {{ color: {text}; }}"
        f"QLabel[cls='sub'] {{ color: {sub}; font-size: 11px; }}")
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    widget.setObjectName("card")
    # 去掉顶层默认背景，仅保留 #card 样式
    widget.setStyleSheet(widget.styleSheet())


class _PopupCard(QWidget):
    """Qt.Popup 无边框圆角卡片：点击外部自动关闭。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup
                         | Qt.WindowType.FramelessWindowHint)
        apply_card_style(self)


class RichComboBox(QWidget):
    """两行富下拉（主行简短名 + 灰字路径），接口对齐 ComboBox 常用用法。

    信号：currentIndexChanged(int)。支持 addItem(text, userData=…, subtitle=…)，
    未传 subtitle 时默认用 userData 文本作为灰字（即路径）。
    """

    currentIndexChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[dict] = []
        self._index = -1
        self._block = False
        self._min_w = 220
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._button = PushButton("")
        self._button.setMinimumWidth(220)
        self._button.clicked.connect(self._open_menu)
        lay.addWidget(self._button)
        self.setMinimumWidth(220)

    # ---- 与 ComboBox 近似的方法 ----
    def setMinimumWidth(self, w: int) -> None:  # noqa: N802
        self._min_w = int(w)
        self._button.setMinimumWidth(self._min_w)
        super().setMinimumWidth(self._min_w)

    def blockSignals(self, flag: bool):  # noqa: N802
        self._block = flag

    def clear(self) -> None:
        self._items = []
        self._index = -1
        self._button.setText("")

    def count(self) -> int:
        return len(self._items)

    def addItem(self, text: str, icon=None, userData: str | None = None,
                subtitle: str | None = None):  # noqa: N802
        del icon  # 不使用图标
        self._items.append({
            "text": str(text),
            "data": "" if userData is None else str(userData),
            "subtitle": str(userData) if subtitle is None else str(subtitle),
        })
        if self._index < 0 and len(self._items) == 1:
            self._set_index(0)

    def currentIndex(self) -> int:  # noqa: N802
        return self._index

    def currentData(self):
        if 0 <= self._index < len(self._items):
            return self._items[self._index]["data"]
        return None

    def itemData(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]["data"]
        return None

    def itemText(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]["text"]
        return ""

    def setCurrentIndex(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            self._set_index(index)

    def _set_index(self, index: int) -> None:
        old = self._index
        self._index = index
        item = self._items[index]
        self._button.setText(f"{item['text']}  ▾")
        if not self._block and index != old:
            self.currentIndexChanged.emit(index)

    # ---- 弹层 ----
    def _open_menu(self) -> None:
        if not self._items:
            return
        menu = _PopupCard(self.window())
        bg, text, sub = card_colors()
        lay = QVBoxLayout(menu)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(2)
        for i, item in enumerate(self._items):
            row = QPushButton()
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setStyleSheet(
                "QPushButton { background: transparent; border: none;"
                f" border-radius: 6px; padding: 6px 10px; text-align: left; }}"
                "QPushButton:hover { background: rgba(0,120,212,0.15); }")
            rl = QVBoxLayout(row)
            rl.setContentsMargins(4, 2, 4, 2)
            rl.setSpacing(1)
            name = QLabel(item["text"])
            name.setStyleSheet(f"color:{text}; font-size:13px;")
            path = QLabel(item["subtitle"])
            path.setStyleSheet(f"color:{sub}; font-size:11px;")
            rl.addWidget(name)
            rl.addWidget(path)
            row.clicked.connect(lambda _=False, idx=i: self._on_chosen(menu, idx))
            lay.addWidget(row)
        lay.addStretch(0)
        # 锚定到按钮下方
        pos = self.mapToGlobal(self.rect().bottomLeft())
        menu.adjustSize()
        w = max(self._min_w, menu.sizeHint().width())
        menu.resize(w, menu.sizeHint().height())
        menu.move(pos.x(), pos.y() + 6)
        menu.show()
        menu.raise_()

    def _on_chosen(self, menu: QWidget, index: int) -> None:
        menu.close()
        self._set_index(index)


class PlaceholderHelpPopover(QWidget):
    """命名模板 '?' 帮助浮窗：结构化列出每个占位符。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup
                         | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("card")
        self._build()

    def _build(self) -> None:
        apply_card_style(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(4)
        title = QLabel("命名模板占位符")
        title.setStyleSheet("font-size:14px; font-weight:600;")
        root.addWidget(title)
        root.addSpacing(4)
        bg, text, sub = card_colors()
        examples = {
            "{file}": ("当前 .blend 文件名（去扩展名）", "job_scene"),
            "{scene}": ("场景名", "产品白底"),
            "{name}": ("快照名", "正面"),
            "{index}": ("队列序号（从 1 开始，可带格式）", "{index:02d} → 07"),
            "{frame}": ("渲染帧号（可带格式）", "{frame:04d} → 0007"),
        }
        for token, (desc, example) in examples.items():
            box = QWidget()
            box.setStyleSheet(
                f"background: transparent; border: 1px solid rgba(127,127,127,80%);"
                f" border-radius: 6px;")
            row = QHBoxLayout(box)
            row.setContentsMargins(8, 4, 8, 4)
            chip = QLabel(token)
            chip.setStyleSheet(
                f"background: rgba(0,120,212,0.15); color:{_ACCENT};"
                f" border-radius: 4px; padding: 1px 7px; font-weight:600;")
            row.addWidget(chip)
            col = QVBoxLayout()
            col.setSpacing(0)
            d = QLabel(desc)
            d.setStyleSheet(f"color:{text};")
            e = QLabel(f"例：{example}")
            e.setStyleSheet(f"color:{sub}; font-size:11px;")
            col.addWidget(d)
            col.addWidget(e)
            row.addLayout(col, 1)
            root.addWidget(box)
        note = QLabel("提示：模板中的 / 会生成子文件夹；不含任何占位符时会自动回退默认模板。")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{sub}; font-size:11px;")
        root.addWidget(note)
        self.adjustSize()

    def show_below(self, anchor: QWidget) -> None:
        pos = anchor.mapToGlobal(anchor.rect().bottomRight())
        self.move(pos.x() - self.width(), pos.y() + 6)
        self.show()
        self.raise_()
