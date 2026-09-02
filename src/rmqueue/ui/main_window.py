"""主窗口：把队列页/设置页/后台 worker 编排起来（轻量控制器）。"""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QFileDialog, QMessageBox
from qfluentwidgets import (
    FluentIcon,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
)

from .. import blender_probe
from ..blender_tools import pick_default
from ..queue import Queue
from .queue_page import QueuePage
from .settings_page import SettingsPage
from .workers import ProbeWorker, RenderWorker

_APP_ORG = "RenderMonitorQueue"
_APP_NAME = "rmqueue"


class MainWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__()
        self.queue = Queue()
        self._busy = False
        self._probe: ProbeWorker | None = None
        self._render: RenderWorker | None = None
        self._prefs = QSettings(_APP_ORG, _APP_NAME)

        self.page = QueuePage(self)
        self.page.setObjectName("queueInterface")
        self.settings_page = SettingsPage(self)
        self.settings_page.setObjectName("settingsInterface")
        self.addSubInterface(self.page, FluentIcon.HOME, "队列")
        self.addSubInterface(self.settings_page, FluentIcon.SETTING, "设置")

        self.setWindowTitle("Render Monitor Queue 渲染排队器")
        self.resize(1180, 760)

        # 恢复应用级默认并接线
        self.settings_page.populate_blender(keep_current=False)
        self.settings_page.set_values(
            blender_exe=self._prefs.value("blender_exe", "") or
            (pick_default().exe if pick_default() else ""),
            outdir=self._prefs.value("output_dir", ""),
            template=self._prefs.value("file_template", ""),
        )
        self.page.set_queue(self.queue)

        # 页面信号
        self.page.filesAdded.connect(self._on_add_files)
        self.page.renderRequested.connect(self._start_render)
        self.page.cancelRequested.connect(self._cancel_render)
        self.page.openProjectRequested.connect(self._open_project)
        self.page.saveProjectRequested.connect(self._save_project)
        self.page.saveProjectAsRequested.connect(self._save_project_as)
        self.settings_page.settingsChanged.connect(self._persist_prefs)
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

    def _resolve_settings(self) -> tuple[str, str, str]:
        exe = self.settings_page.blender_exe()
        outdir = self.settings_page.outdir()
        template = self.settings_page.template()
        return exe, outdir, template

    def _persist_prefs(self) -> None:
        exe, outdir, template = self._resolve_settings()
        self._prefs.setValue("blender_exe", exe)
        self._prefs.setValue("output_dir", outdir)
        self._prefs.setValue("file_template", template)

    def _capture_project_settings(self) -> None:
        exe, outdir, template = self._resolve_settings()
        self.queue.settings.blender_exe = exe
        self.queue.settings.output_dir = outdir
        self.queue.settings.file_template = template

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.page.set_busy(busy)

    # ------------------------------------------------------ 添加/探针
    def _on_add_files(self, paths: list[str]) -> None:
        if self._busy:
            return
        exe, _out, _tpl = self._resolve_settings()
        if not exe or not os.path.isfile(exe):
            self._status("请先在「设置」中选择可用的 Blender", level="warn")
            return
        fresh = []
        for p in paths:
            if self.queue.file_by_path(p) is None:
                fresh.append(p)
        if fresh:
            self.page.set_status(f"正在枚举 {len(fresh)} 个文件（后台 Blender）…")
            self._start_probe(fresh, exe)
        else:
            self._status("所选文件已在队列中（如需刷新请移除后重新添加）", level="info")

    def _start_probe(self, paths: list[str], exe: str) -> None:
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
        added = stats["shots_added"]
        self._status(f"{os.path.basename(path)}：{data.get('blender_version', '?')}，"
                     f"新增 {added} 个快照", level="info")

    def _on_probe_finished(self) -> None:
        self.page.refresh()
        self._status("枚举完成")

    # ------------------------------------------------------ 渲染
    def _start_render(self) -> None:
        if self._busy or self._render is not None:
            return
        exe, outdir, template = self._resolve_settings()
        if not exe or not os.path.isfile(exe):
            self._status("请先在「设置」中配置 Blender", level="warn")
            return
        if not outdir or not os.path.isdir(outdir):
            self._status("请先在「设置」中选择存在的输出目录", level="warn")
            return
        self._capture_project_settings()
        total = len(self.queue.flatten_selected())
        if total == 0:
            self._status("没有勾选的快照（请先添加文件并勾选）", level="warn")
            return
        self._set_busy(True)
        self.page.set_status(f"开始渲染（{total} 张）…")
        self._render = RenderWorker(
            self.queue, exe, blender_probe.find_vendor_dir(), outdir, template, self,
        )
        self._render.fileStarted.connect(self._on_file_started)
        self._render.tick.connect(self._on_render_tick)
        self._render.runFinished.connect(self._on_render_finished)
        self._render.start()

    def _on_file_started(self, path: str, total: int) -> None:
        self.page.refresh()
        self.page.set_status(f"渲染中：{os.path.basename(path)}（{total} 张）")

    def _on_render_tick(self, current: str, done: int, failed: int, total: int) -> None:
        text = f"当前：{current or '启动中'} · {done + failed}/{total}"
        self.page.set_worker_text(text)

    def _on_render_finished(self, overview: dict) -> None:
        self.page.set_worker_text("")
        self._set_busy(False)
        self.page.refresh()
        cancelled = overview.get("cancelled")
        level = "ok" if not cancelled else "info"
        msg = overview.get("message", "")
        self._status(msg, level=level)
        if not cancelled:
            done = overview.get("done", 0)
            failed = overview.get("failed", 0)
            self._status(f"{msg} —— 输出目录：{self.settings_page.outdir()}",
                         level="ok" if failed == 0 else "warn")
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
        self.settings_page.set_values(
            blender_exe=q.settings.blender_exe, outdir=q.settings.output_dir,
            template=q.settings.file_template,
        )
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
        event.accept()
