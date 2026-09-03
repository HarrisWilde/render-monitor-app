"""回归：qfluentwidgets ProgressBar 构造期残留动画会把已满进度异步拉回 0。

旧写法 `ProgressBar(...)` 默认 useAni=True，构造里 setValue(0) 会启动一条
结束值为 0 的 QPropertyAnimation；随后 `setUseAni(False)` 并不会停止它，
若此时立刻 setVal(100)，这条残留动画可能在事件循环里把条拉回 0（百分比文字
仍是 100%）。本测试确保进度条用 useAni=False 构造时不会出现该回退。
"""

from __future__ import annotations

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from qfluentwidgets import ProgressBar  # noqa: E402


class TestProgressBarKeepsValue(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_no_animation_does_not_reset_set_val(self) -> None:
        bar = ProgressBar(useAni=False)
        bar.setVal(100.0)
        # 给事件循环留足 150ms（旧写法动画时长），确认值不被异步覆盖。
        deadline = time.monotonic() + 0.25
        while time.monotonic() < deadline:
            self.app.processEvents()
        self.assertEqual(bar.val, 100.0)


if __name__ == "__main__":
    unittest.main()
