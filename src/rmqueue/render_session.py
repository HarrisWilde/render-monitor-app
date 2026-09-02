"""单 .blend 文件的串行渲染会话（纯逻辑 + 子进程编排，不含 Qt）。

- 每次会话：`blender -b <file> -P render_script.py -- ...`；
- 会话内按队列顺序遍历（可跨场景），每项应用快照 → 渲染 → 原子替换；
- 作业可携带各自 outdir（跟随项目内场景插件设置时按场景分别输出）；
- 渲染期间 render_stats 回调把采样/分块进度写回 mmap（0.5s 节流），
  供 UI 每个快照的进度条实时更新；
- 收尾做状态一致性修正（崩溃/致命/取消），与插件 _finish_session 一致。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap

from . import progress
from .queue import Queue

STATUS_PENDING = "PENDING"
STATUS_RENDERING = "RENDERING"
STATUS_DONE = "DONE"
STATUS_FAILED = "FAILED"

# ---------------------------------------------------------------------------
# 内嵌渲染脚本（blender -b 内运行）
# ---------------------------------------------------------------------------

RENDER_SCRIPT = textwrap.dedent(
    """\
    # Render Monitor Queue - 渲染脚本（blender -b 内运行）
    # 用法：blender -b <file> -P <本脚本> -- <vendor> <app_src> <outdir> \\
    #       <template> <use_snapshot_frame 1|0> <progress_path> <jobs_json>
    import json
    import os
    import sys
    import time
    import traceback

    def _main():
        try:
            marker = sys.argv.index("--")
        except ValueError:
            sys.stderr.write("rmq-render: 缺少 '--'\\n")
            return 1
        args = sys.argv[marker + 1:]
        if len(args) < 7:
            sys.stderr.write(f"rmq-render: 参数不足 {args}\\n")
            return 1
        vendor_dir, app_src, outdir, template, use_sf, progress_path, jobs_json = args[:7]

        sys.path.insert(0, vendor_dir)
        sys.path.insert(0, app_src)
        for _name in list(sys.modules):
            if _name == "render_monitor" or _name.startswith("render_monitor."):
                del sys.modules[_name]

        import bpy
        import render_monitor
        render_monitor.register()
        from render_monitor import core
        from render_monitor import utils as rm_utils
        from rmqueue import naming, progress as rprogress

        with open(jobs_json, encoding="utf-8") as f:
            jobs = json.load(f)
        reported = [
            {"scene": j["scene"], "uid": j["uid"], "index": j["index"],
             "name": j.get("name", ""), "status": "PENDING",
             "path": "", "error": "", "progress": 0.0,
             "samples": 0, "samples_total": 0}
            for j in jobs
        ]
        total = len(reported)

        def _write(state):
            rprogress.write_file(progress_path,
                                 {"state": state, "total": total, "jobs": reported})

        def _make_progress_handler(entry):
            # render_stats 回调：把采样/分块进度写入当前项（0.5s 节流）
            last = [0.0]

            def handler(stats_str):
                try:
                    parsed = rm_utils.parse_render_stats(stats_str)
                    cur = parsed.get("samples") or 0
                    ttl = parsed.get("samples_total") or 0
                    td = parsed.get("tiles_done") or 0
                    tt = parsed.get("tiles_total") or 1
                    entry["samples"] = cur
                    entry["samples_total"] = ttl
                    if ttl > 0:
                        if tt > 1 and tt >= td + 1:
                            entry["progress"] = min((td + cur / ttl) / tt, 1.0)
                        else:
                            entry["progress"] = min(cur / ttl, 1.0)
                    elif tt > 1 and td:
                        entry["progress"] = min(td / tt, 1.0)
                    if any(k in stats_str
                           for k in ("Finished", "Denoising", "Finishing")):
                        entry["progress"] = 1.0
                    now = time.monotonic()
                    if now - last[0] >= 0.5:
                        last[0] = now
                        _write("running")
                except Exception:
                    pass

            return handler

        _write("running")
        for job, entry in zip(jobs, reported):
            entry["status"] = "RENDERING"
            entry["progress"] = 0.0
            _write("running")
            actual_path = ""
            handler = None
            try:
                job_outdir = job.get("outdir") or outdir
                scene = bpy.data.scenes.get(job["scene"])
                if scene is None:
                    raise RuntimeError(f"场景不存在: {job['scene']}")
                shot = next((s for s in scene.rm_shots if s.uid == job["uid"]), None)
                if shot is None:
                    raise RuntimeError(f"快照不存在: uid={job['uid']}")
                data = json.loads(shot.data_json)
                frame_before = scene.frame_current
                core.apply_scene_state(scene, data)
                if use_sf != "1":
                    scene.frame_current = frame_before
                ext = (scene.render.file_extension or ".png").lstrip(".") or "png"
                rel = naming.format_output_relpath(
                    template, bpy.data.filepath, scene.name, shot.name,
                    int(job["index"]), frame=int(scene.frame_current),
                )
                path = naming.build_abs_output_path(job_outdir, rel, ext)
                os.makedirs(os.path.dirname(path) or job_outdir, exist_ok=True)
                # 原子替换防覆盖：先渲染到唯一临时文件，成功后再替换
                try:
                    scene.render.use_file_extension = True
                except Exception:
                    pass
                tmp_path = path + f".rmtmp{os.urandom(4).hex()}"
                actual_path = tmp_path + "." + ext
                scene.render.filepath = tmp_path
                handler = _make_progress_handler(entry)
                bpy.app.handlers.render_stats.append(handler)
                bpy.ops.render.render(scene=scene.name, write_still=True,
                                      use_viewport=False)
                entry["progress"] = 1.0
                if not (os.path.exists(actual_path)
                        and os.path.getsize(actual_path) > 0):
                    raise RuntimeError(f"渲染未生成输出文件（可能被取消或写盘失败）: {path}")
                os.replace(actual_path, path)
                entry["status"] = "DONE"
                entry["path"] = path
            except Exception as exc:  # noqa: BLE001
                entry["status"] = "FAILED"
                entry["error"] = str(exc)
                traceback.print_exc(file=sys.stderr)
                try:
                    if actual_path and os.path.exists(actual_path):
                        os.remove(actual_path)
                except OSError:
                    pass
            finally:
                if handler is not None:
                    try:
                        bpy.app.handlers.render_stats.remove(handler)
                    except (ValueError, TypeError):
                        pass
            _write("running")
        _write("done")
        print(f"[rmq-render] done ok={sum(1 for e in reported if e['status']=='DONE')} "
              f"fail={sum(1 for e in reported if e['status']=='FAILED')}")
        return 0

    if __name__ == "__main__":
        code = 1
        try:
            code = _main()
        except BaseException:  # noqa: BLE001
            traceback.print_exc()
            try:
                marker = sys.argv.index("--")
                args = sys.argv[marker + 1:]
                if len(args) >= 6:
                    from rmqueue import progress as rp
                    rp.write_file(args[5], {"state": "error", "total": 0,
                                            "jobs": [{"scene": "", "uid": "",
                                                      "index": 0, "name": "",
                                                      "status": "FAILED",
                                                      "path": "",
                                                      "error": traceback.format_exc()}]})
            except Exception:  # noqa: BLE001
                pass
            code = 1
        sys.exit(code)
    """
)


def app_src_dir() -> str:
    """返回可被子进程 import 的 rmqueue 源码父目录（src / 打包根）。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return meipass
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# 会话编排（进程生命周期）
# ---------------------------------------------------------------------------

def spawn_session(
    blender_exe: str,
    blend_file: str,
    vendor_dir: str,
    jobs: list[dict],
    outdir: str,
    template: str,
    use_snapshot_frame: bool = True,
    log_dir: str | None = None,
) -> dict:
    """启动一次单文件渲染会话。jobs 形如 [{scene,uid,index,name,outdir?}]。

    返回句柄：{process, tmpdir, progress_path, jobs_json, log_path,
    blend_file, jobs, outdir, template, vendor_dir, app_src}
    """
    tmpdir = tempfile.mkdtemp(prefix="rmq_render_")
    progress_path = os.path.join(tmpdir, "progress.bin")
    jobs_json_path = os.path.join(tmpdir, "jobs.json")
    log_path = os.path.join(tmpdir, "render.log")
    with open(jobs_json_path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False)

    log_f = open(log_path, "w", encoding="utf-8", errors="replace")
    script_path = os.path.join(tmpdir, "render_script.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(RENDER_SCRIPT)
    cmd = [
        blender_exe, "-b", blend_file, "-P", script_path, "--",
        vendor_dir, app_src_dir(), outdir, template,
        "1" if use_snapshot_frame else "0",
        progress_path, jobs_json_path,
    ]
    proc = subprocess.Popen(cmd, stdout=log_f, stderr=log_f)
    log_f.close()
    return {
        "process": proc,
        "tmpdir": tmpdir,
        "progress_path": progress_path,
        "jobs_json": jobs_json_path,
        "log_path": log_path,
        "blend_file": blend_file,
        "jobs": jobs,
        "outdir": outdir,
        "template": template,
        "vendor_dir": vendor_dir,
        "app_src": app_src_dir(),
    }


def session_running(handle: dict) -> bool:
    proc = handle["process"]
    return proc is not None and proc.poll() is None


def poll_session(handle: dict):
    """读一次会话进度（无则 None）。"""
    return progress.read_file(handle["progress_path"])


def stop_session(handle: dict) -> None:
    """终止子进程（terminate → 宽限 → kill）。"""
    proc = handle["process"]
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
    except OSError:
        pass
    try:
        proc.wait(timeout=8)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _session_shot_statuses(queue: Queue, file_path: str, jobs: list[dict]) -> dict:
    """收集会话涉及的快照引用：{(scene, uid): QueueShot}。"""
    out = {}
    for j in jobs:
        shot = queue.shot_by(file_path, j["scene"], j["uid"])
        if shot is not None:
            out[(j["scene"], j["uid"])] = shot
    return out


def _apply_terminal_from_payload(queue: Queue, file_path: str, payload) -> None:
    if not payload:
        return
    for j in payload.get("jobs", []):
        if j.get("status") not in (STATUS_DONE, STATUS_FAILED):
            continue
        shot = queue.shot_by(file_path, j.get("scene", ""), j.get("uid", ""))
        if shot is None:
            continue
        shot.app_status = j["status"]
        shot.output = j.get("path") or shot.output
        if j["status"] == STATUS_FAILED:
            shot.error = j.get("error") or shot.error


def finish_session(
    queue: Queue,
    file_path: str,
    handle: dict,
    payload,
    returncode: int,
    cancelled: bool = False,
) -> dict:
    """会话结束收尾：状态一致性修正 + 计数 + 消息 + 清理。返回摘要。"""
    jobs = handle["jobs"]
    shots = _session_shot_statuses(queue, file_path, jobs)
    try:
        if cancelled:
            for shot in shots.values():
                if shot.app_status == STATUS_RENDERING:
                    shot.app_status = STATUS_PENDING
                    shot.error = ""
        else:
            crashed = returncode != 0
            crashed_early = crashed and (
                payload is None or payload.get("state") == "error"
            )
            if crashed:
                for shot in shots.values():
                    if shot.app_status == STATUS_RENDERING:
                        shot.app_status = STATUS_FAILED
                        if not shot.error:
                            shot.error = "渲染进程异常退出，该快照被中断"
                    elif shot.app_status == STATUS_PENDING and crashed_early:
                        shot.app_status = STATUS_FAILED
                        if not shot.error:
                            shot.error = "渲染进程在开始前异常退出"
            _apply_terminal_from_payload(queue, file_path, payload)

        done = sum(1 for s in shots.values() if s.app_status == STATUS_DONE)
        failed = sum(1 for s in shots.values() if s.app_status == STATUS_FAILED)

        if cancelled:
            message = "已停止渲染（未完成的快照保持待渲染状态）"
        else:
            errors = []
            if payload:
                for j in payload.get("jobs", []):
                    err = (j.get("error") or "").strip()
                    if err:
                        errors.append(f"{j.get('name') or j.get('uid')}: {err}")
            message = f"渲染完成：成功 {done}，失败 {failed}"
            if errors:
                message += "；" + "；".join(errors[:3])
                if len(errors) > 3:
                    message += f"（还有 {len(errors) - 3} 条错误）"
            if returncode != 0 and not errors:
                message += f"（渲染进程异常退出，代码 {returncode}，日志：{handle['log_path']}）"
        return {"done": done, "failed": failed, "message": message,
                "returncode": returncode, "cancelled": cancelled}
    finally:
        import shutil

        shutil.rmtree(handle["tmpdir"], ignore_errors=True)
