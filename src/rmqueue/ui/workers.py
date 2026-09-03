"""QThread 后台任务：探针（枚举）与渲染调度。

- ProbeWorker：串行对多个 .blend 跑 blender -b 探针，逐个发回结果；
- RenderWorker：严格串行渲染——按文件分组，逐文件 spawn/poll/finish，
  轮询 mmap 进度并通过 itemsTick 把每个快照的最新状态/进度回传 UI，
  支持中途取消（终止当前进程、已完成保留、未开始保持待渲染）；
- UpdateCheckWorker：后台请求 GitHub Releases，检查是否有新版本。
"""

from __future__ import annotations

import time
from collections import OrderedDict

from PySide6.QtCore import QThread, Signal

from .. import blender_probe, render_session, updater
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


class UpdateCheckWorker(QThread):
    """后台检查 GitHub 最新 Release。checkFinished(result_dict)"""

    checkFinished = Signal(object)

    def __init__(self, current_version: str, parent=None,
                 repo: str = updater.GITHUB_REPO) -> None:
        super().__init__(parent)
        self._current_version = current_version
        self._repo = repo

    def run(self) -> None:  # noqa: D102
        try:
            result = updater.check_latest_release(
                self._current_version, repo=self._repo
            )
        except Exception as exc:  # noqa: BLE001 - 后台检查失败不应中断主线程
            result = {
                "ok": False,
                "current_version": self._current_version,
                "error": str(exc),
            }
        self.checkFinished.emit(result)


class RenderWorker(QThread):
    """严格串行渲染调度（单 worker，一次一个 blender 子进程）。

    fileStarted(path, total_jobs)
    itemsTick(path, jobs_payload, done, failed, total)   # 逐快照状态/进度
    fileFinished(path, summary_dict)
    runFinished(overview_dict)  # {cancelled, message, done, failed, details}
    """

    fileStarted = Signal(str, int)
    itemsTick = Signal(str, object, int, int, int)
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
        use_project_out = queue.settings.output_source == "project"
        groups: "OrderedDict[str, list[dict]]" = OrderedDict()
        for job in queue.flatten_selected():
            item = {
                "scene": job.scene,
                "uid": job.uid,
                "index": job.index,
                "name": job.name,
            }
            if use_project_out:
                scene_obj = self._scene_of(queue, job.file_path, job.scene)
                if scene_obj is not None and scene_obj.output_dir:
                    item["outdir"] = scene_obj.resolve_output_dir(
                        job.file_path, outdir)
            groups.setdefault(job.file_path, []).append(item)
        self._groups = groups
        self._total_jobs = sum(len(v) for v in groups.values())

    @staticmethod
    def _scene_of(queue: Queue, file_path: str, scene_name: str):
        f = queue.file_by_path(file_path)
        if f is None:
            return None
        for sc in f.scenes:
            if sc.name == scene_name:
                return sc
        return None

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
                        cur_items = payload.get("jobs", [])
                        done = sum(1 for e in cur_items
                                   if e.get("status") == render_session.STATUS_DONE)
                        failed = sum(1 for e in cur_items
                                     if e.get("status") == render_session.STATUS_FAILED)
                        self.itemsTick.emit(
                            path, cur_items, done, failed, payload.get("total", 0))
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
