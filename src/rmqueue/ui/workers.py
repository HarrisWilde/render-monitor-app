"""QThread 后台任务：探针（枚举）与渲染调度。

- ProbeWorker：串行对多个 .blend 跑 blender -b 探针，逐个发回结果；
- RenderWorker：严格串行渲染——按文件分组，逐文件 spawn/poll/finish，
  轮询 mmap 进度发 tick，支持中途取消（终止当前进程、已完成的保留、
  未开始的保持待渲染）。
"""

from __future__ import annotations

import time
from collections import OrderedDict

from PySide6.QtCore import QThread, Signal

from .. import blender_probe, render_session
from ..queue import Queue

_STATUS_TEXT = {
    render_session.STATUS_PENDING: "待渲染",
    render_session.STATUS_RENDERING: "渲染中",
    render_session.STATUS_DONE: "已完成",
    render_session.STATUS_FAILED: "失败",
}


def status_text(status: str) -> str:
    return _STATUS_TEXT.get(status, status or "待渲染")


class ProbeWorker(QThread):
    """fileProbed(path, data_or_None, message)"""

    fileProbed = Signal(str, object, str)

    def __init__(self, paths: list[str], blender_exe: str, vendor_dir: str,
                 parent=None) -> None:
        super().__init__(parent)
        self._paths = list(paths)
        self._exe = blender_exe
        self._vendor = vendor_dir

    def run(self) -> None:  # noqa: D102
        for path in self._paths:
            result = blender_probe.probe_blend(self._exe, path, self._vendor)
            self.fileProbed.emit(path, result.get("data"), result.get("message", ""))


class RenderWorker(QThread):
    """严格串行渲染调度（单 worker，一次一个 blender 子进程）。

    fileStarted(path, total_jobs)
    tick(current_name, done, failed, total)
    fileFinished(path, summary_dict)
    runFinished(overview_dict)  # {cancelled, message, done, failed, details}
    """

    fileStarted = Signal(str, int)
    tick = Signal(str, int, int, int)
    fileFinished = Signal(str, object)
    runFinished = Signal(object)

    def __init__(self, queue: Queue, blender_exe: str, vendor_dir: str,
                 outdir: str, template: str, parent=None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._exe = blender_exe
        self._vendor = vendor_dir
        self._outdir = outdir
        self._template = template
        self._cancel = False
        # 渲染开始时快照勾选状态 → 按文件分组的作业清单（全局扁平序号）
        groups: "OrderedDict[str, list[dict]]" = OrderedDict()
        for job in queue.flatten_selected():
            groups.setdefault(job.file_path, []).append({
                "scene": job.scene,
                "uid": job.uid,
                "index": job.index,
                "name": job.name,
            })
        self._groups = groups
        self._total_jobs = sum(len(v) for v in groups.values())

    def cancel(self) -> None:
        self._cancel = True

    def total_jobs(self) -> int:
        return self._total_jobs

    # -- 内部工具 ----------------------------------------------------------
    def _set_status(self, path: str, jobs: list[dict], status: str,
                    error: str = "") -> None:
        for j in jobs:
            shot = self._queue.shot_by(path, j["scene"], j["uid"])
            if shot is not None:
                shot.app_status = status
                if error:
                    shot.error = error

    def run(self) -> None:  # noqa: D102
        done_tot = failed_tot = 0
        messages: list[str] = []
        cancelled = False
        try:
            for path, jobs in self._groups.items():
                if self._cancel:
                    cancelled = True
                    break
                self.fileStarted.emit(path, len(jobs))
                self._set_status(path, jobs, render_session.STATUS_RENDERING)
                handle = render_session.spawn_session(
                    self._exe, path, self._vendor, jobs,
                    self._outdir, self._template,
                )
                # 轮询循环：0.5s 节奏，兼顾取消响应
                while render_session.session_running(handle):
                    if self._cancel:
                        render_session.stop_session(handle)
                        break
                    payload = render_session.poll_session(handle)
                    if payload:
                        cur = ""
                        done = failed = 0
                        for e in payload.get("jobs", []):
                            if e.get("status") == render_session.STATUS_RENDERING:
                                cur = e.get("name", "")
                            elif e.get("status") == render_session.STATUS_DONE:
                                done += 1
                            elif e.get("status") == render_session.STATUS_FAILED:
                                failed += 1
                        self.tick.emit(cur, done, failed, payload.get("total", 0))
                    time.sleep(0.5)
                rc = handle["process"].poll()
                payload = render_session.poll_session(handle)
                summary = render_session.finish_session(
                    self._queue, path, handle, payload, rc,
                    cancelled=self._cancel,
                )
                self.fileFinished.emit(path, summary)
                done_tot += summary["done"]
                failed_tot += summary["failed"]
                messages.append(f"{path}: {summary['message']}")
                if self._cancel:
                    cancelled = True
                    break
        except Exception as exc:  # noqa: BLE001 - 调度异常兜底
            for path, jobs in self._groups.items():
                self._set_status(path, jobs, render_session.STATUS_PENDING)
            self.runFinished.emit({
                "cancelled": False, "message": f"调度异常: {exc}",
                "done": done_tot, "failed": failed_tot, "details": messages,
            })
            return

        overview_message = (
            "已停止渲染（未完成快照保持待渲染）" if cancelled
            else f"渲染完成：成功 {done_tot}，失败 {failed_tot}"
        )
        self.runFinished.emit({
            "cancelled": cancelled, "message": overview_message,
            "done": done_tot, "failed": failed_tot, "details": messages,
        })
