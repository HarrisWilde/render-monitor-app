"""主窗口：编排队列页/设置页与后台 worker（轻量控制器）。

- 渲染配置（Blender/输出目录/来源/模板）在首页「渲染选项」卡，随项目与
  QSettings 双持久化；
- 渲染期间维护整体进度（已完成文件累计 + 当前文件实时计数）；
- 逐快照 tick 直接刷队列页行内进度条（不整树重建）。
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QFileDialog, QMessageBox
from qfluentwidgets import (
    FluentIcon,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    setTheme,
    Theme,
)

from .. import blender_probe
from ..queue import Queue
from .queue_page import QueuePage
from .settings_page import (
    THEME_AUTO,
    THEME_DARK,
    THEME_LIGHT,
    SettingsPage,
)
from .taskbar_progress import TaskbarProgress
from .workers import ProbeWorker, RenderWorker

_APP_ORG = "RenderMonitorQueue"
_APP_NAME = "rmqueue"
_THEME_QT = {
    THEME_LIGHT: Theme.LIGHT,
    THEME_DARK: Theme.DARK,
    THEME_AUTO: Theme.AUTO,
}


class MainWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__()
        self.queue = Queue()
        self._busy = False
        self._probe: ProbeWorker | None = None
        self._render: RenderWorker | None = None
        self._prefs = QSettings(_APP_ORG, _APP_NAME)
        self._tb = TaskbarProgress()  # Windows 任务栏进度（不可用时静默）
        # 整体进度：已完成文件累计 + 批次总数
        self._prev_done = 0
        self._prev_failed = 0
        self._grand_total = 0

        self.page = QueuePage(self)
        self.page.setObjectName("queueInterface")
        self.settings_page = SettingsPage(self)
        self.settings_page.setObjectName("settingsInterface")
        self.addSubInterface(self.page, FluentIcon.HOME, "队列")
        self.addSubInterface(self.settings_page, FluentIcon.SETTING, "设置")

        self.setWindowTitle("Render Monitor Queue 渲染排队器")
        self.resize(1200, 820)

        # 主题恢复
        theme = self._prefs.value("theme", THEME_LIGHT)
        self._apply_theme(str(theme))
        self.settings_page.set_theme(str(theme))

        # 首页渲染选项：默认值 = QSettings → 自动探测兜底
        self.page.populate_blender(keep_current=False)
        exe = self._prefs.value("blender_exe", "")
        if not exe:
            from ..blender_tools import pick_default
            picked = pick_default()
            exe = picked.exe if picked else ""
        self.page.config_set({
            "blender_exe": exe,
            "output_dir": self._prefs.value("output_dir", ""),
            "output_source": self._prefs.value("output_source", "global"),
            "file_template": self._prefs.value(
                "file_template", "{file}/{scene}/{name} {index}"),
        })
        self.page.set_queue(self.queue)

        # 信号
        self.page.filesAdded.connect(self._on_add_files)
        self.page.renderRequested.connect(self._start_render)
        self.page.cancelRequested.connect(self._cancel_render)
        self.page.openProjectRequested.connect(self._open_project)
        self.page.saveProjectRequested.connect(self._save_project)
        self.page.saveProjectAsRequested.connect(self._save_project_as)
        self.page.configChanged.connect(self._persist_prefs)
        self.settings_page.themeChanged.connect(self._apply_theme)
        self._status("就绪：拖入 .blend 文件，或点「添加文件」")

    # ---------------------------------------------------------- 基础工具
    def _status(self, text: str, level: str = "info") -> None:
        self.page.set_status(text)
        if level == "ok":
            InfoBar.success("完成", text, duration=4000, parent=self)
        elif level == "warn":
            InfoBar.warning("提示", text, duration=5000, parent=self)
        elif level == "err":
            InfoBar.error("错误", text, duration=8000, parent=self)

    def _config(self) -> dict:
        return self.page.config_get()

    def _apply_theme(self, theme: str) -> None:
        setTheme(_THEME_QT.get(theme, Theme.LIGHT))
        self._prefs.setValue("theme", theme)

    def _persist_prefs(self) -> None:
        cfg = self._config()
        self._prefs.setValue("blender_exe", cfg["blender_exe"])
        self._prefs.setValue("output_dir", cfg["output_dir"])
        self._prefs.setValue("output_source", cfg["output_source"])
        self._prefs.setValue("file_template", cfg["file_template"])

    def _capture_project_settings(self) -> None:
        cfg = self._config()
        self.queue.settings.blender_exe = cfg["blender_exe"]
        self.queue.settings.output_dir = cfg["output_dir"]
        self.queue.settings.output_source = cfg["output_source"]
        self.queue.settings.file_template = cfg["file_template"]

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.page.set_busy(busy)

    def _taskbar(self, mode: str, fraction: float | None = None) -> None:
        """同步 Windows 任务栏进度：mode ∈ indeterminate|normal|clear。"""
        if sys.platform != "win32" or not self._tb.available():
            return
        try:
            hwnd = int(self.winId())
        except Exception:  # noqa: BLE001
            return
        if mode == "indeterminate":
            self._tb.indeterminate(hwnd)
        elif mode == "normal" and fraction is not None:
            self._tb.normal(hwnd, fraction)
        elif mode == "clear":
            self._tb.clear(hwnd)

    # ------------------------------------------------------ 添加/探针
    def _on_add_files(self, paths: list[str]) -> None:
        if self._busy:
            return
        exe = self._config()["blender_exe"]
        if not exe or not os.path.isfile(exe):
            self._status("请先在上方「渲染选项」中选择可用的 Blender", level="warn")
            return
        fresh = [p for p in paths if self.queue.file_by_path(p) is None]
        if fresh:
            self.page.set_status(f"正在枚举 {len(fresh)} 个文件（后台 Blender）…")
            self._start_probe(fresh, exe)
        else:
            self._status("所选文件已在队列中（如需刷新请移除后重新添加）")

    def _start_probe(self, paths: list[str], exe: str) -> None:
        if self._probe is not None and self._probe.isRunning():
            return
        self.page.overall_mode("busy")  # 忙碌动画：明确“正在加载”，避免以为卡死
        self.page.set_worker_text(f"正在枚举 {len(paths)} 个文件…")
        self._taskbar("indeterminate")
        self._probe = ProbeWorker(paths, exe, blender_probe.find_vendor_dir(), self)
        self._probe.fileProbed.connect(self._on_file_probed)
        self._probe.finished.connect(self._on_probe_finished)
        self._probe.start()

    def _on_file_probed(self, path: str, data, message: str) -> None:
        if data is None:
            self._status(f"枚举失败：{os.path.basename(path)} — {message}", level="err")
            return
        stats = self.queue.merge_probe(path, data.get("scenes", []))
        self.page.refresh()
        self._status(f"{os.path.basename(path)}：{data.get('blender_version', '?')}，"
                     f"新增 {stats['shots_added']} 个快照")

    def _on_probe_finished(self) -> None:
        self.page.refresh()
        self.page.overall_mode("hidden")
        self._taskbar("clear")
        self._status("枚举完成")

    # ------------------------------------------------------ 渲染
    def _start_render(self) -> None:
        if self._busy or self._render is not None:
            return
        cfg = self._config()
        exe, outdir = cfg["blender_exe"], cfg["output_dir"]
        template = cfg["file_template"]
        if not exe or not os.path.isfile(exe):
            self._status("请先在首页「渲染选项」中配置 Blender", level="warn")
            return
        if not outdir or not os.path.isdir(outdir):
            self._status("请先在首页「渲染选项」中设置存在的全局输出目录", level="warn")
            return
        if cfg["output_source"] == "project":
            # 项目模式仅要求各场景有目录/或全局兜底；全局仍需存在作为兜底
            pass
        self._capture_project_settings()
        total = len(self.queue.flatten_selected())
        if total == 0:
            self._status("没有勾选的快照（请先添加文件并勾选）", level="warn")
            return
        self._prev_done = self._prev_failed = 0
        self._grand_total = total
        self._set_busy(True)
        self.page.set_status(f"开始渲染（{total} 张）…")
        self._render = RenderWorker(
            self.queue, exe, blender_probe.find_vendor_dir(), outdir, template, self,
        )
        self._render.fileStarted.connect(self._on_file_started)
        self._render.itemsTick.connect(self._on_items_tick)
        self._render.fileFinished.connect(self._on_file_finished)
        self._render.runFinished.connect(self._on_run_finished)
        self._render.start()

    def _on_file_started(self, path: str, total: int) -> None:
        self.page.refresh()  # 重建行/进度条注册表并保持全展开
        self.page.overall_mode("normal")
        self.page.set_status(f"渲染中：{os.path.basename(path)}（{total} 张）")
        prev = self._prev_done + self._prev_failed
        self.page.set_overall(prev, self._grand_total)
        self._taskbar("normal", prev / max(self._grand_total, 1))

    def _on_items_tick(self, path: str, items, done: int, failed: int,
                       total: int) -> None:
        self.page.on_items_tick(path, items, done, failed, total)
        # 总进度平滑混算：已完成张（DONE/FAILED）按整张计 1，当前张按自身
        # 进度（0..1，分块加权）映射到它的份额区间，避免“0%→10%”跳变
        terminal = sum(1 for e in items
                       if e.get("status") in ("DONE", "FAILED"))
        partial = 0.0
        current = ""
        for e in items:
            if e.get("status") == "RENDERING":
                current = e.get("name", "")
                partial = float(e.get("progress") or 0.0)
                break
        value = (self._prev_done + self._prev_failed + terminal + partial)
        self.page.set_overall(value, self._grand_total)
        self._taskbar("normal", value / max(self._grand_total, 1))
        # 左下角状态行：当前快照 + 采样/块细节 + 批次计数
        running = next((e for e in items if e.get("status") == "RENDERING"), None)
        details = f"当前：{current or '启动中'}"
        if running is not None:
            s, st = running.get("samples", 0), running.get("samples_total", 0)
            td, tt = running.get("tiles_done", 0), running.get("tiles_total", 0)
            if st:
                details += f" · 采样 {s}/{st}"
            if tt and tt > 1:
                details += f" · 块 {min(int(td) + 1, int(tt))}/{tt}"
        done_all = self._prev_done + done + self._prev_failed + failed
        self.page.set_status(f"{details} ｜ 批次 {done_all}/{self._grand_total}")

    def _on_file_finished(self, path: str, summary: dict) -> None:
        self._prev_done += summary["done"]
        self._prev_failed += summary["failed"]
        self.page.refresh()
        self.page.set_overall(self._prev_done + self._prev_failed, self._grand_total)

    def _on_run_finished(self, overview: dict) -> None:
        self.page.set_worker_text("")
        self._taskbar("clear")
        self._set_busy(False)  # 会隐藏总进度条（无任务状态）
        self.page.refresh()
        cancelled = overview.get("cancelled")
        msg = overview.get("message", "")
        if not cancelled:
            done, failed = overview.get("done", 0), overview.get("failed", 0)
            self._status(f"{msg} —— 输出见各快照「输出」列",
                         level="ok" if failed == 0 else "warn")
        else:
            self._status(msg, level="info")
        self._render = None

    def _cancel_render(self) -> None:
        if self._render is not None:
            self._render.cancel()
            self.page.set_status("正在停止（等待当前张退出）…")

    # ------------------------------------------------------ 项目文件
    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开队列项目", "", "Render Monitor Queue (*.rmq.json);;JSON (*.json)")
        if not path:
            return
        try:
            q = Queue.load(path)
        except Exception as exc:  # noqa: BLE001
            self._status(f"打开项目失败：{exc}", level="err")
            return
        self.queue = q
        self.page.set_queue(q)
        self.page.config_set({
            "blender_exe": q.settings.blender_exe,
            "output_dir": q.settings.output_dir,
            "output_source": q.settings.output_source,
            "file_template": q.settings.file_template,
        })
        self.page.refresh()
        self._status(f"已打开项目：{os.path.basename(path)}")

    def _save_project(self) -> None:
        if self.queue.files:
            self._save_project_as()

    def _save_project_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "保存队列项目", "queue.rmq.json",
            "Render Monitor Queue (*.rmq.json);;JSON (*.json)")
        if not path:
            return
        self._capture_project_settings()
        try:
            self.queue.save(path)
            self._status(f"已保存项目：{path}", level="ok")
        except OSError as exc:
            self._status(f"保存失败：{exc}", level="err")

    # ------------------------------------------------------ 生命周期
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._render is not None and self._busy:
            answer = QMessageBox.question(
                self, "退出",
                "渲染正在进行，确定退出？（将停止当前渲染，未完成的快照保留待渲染）")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._render.cancel()
            self._render.wait(5000)
        self._taskbar("clear")
        event.accept()
