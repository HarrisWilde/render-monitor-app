"""blender -b 子进程通用运行器 + 快照枚举探针。

任何需要调用 Blender 的功能（枚举、渲染）都经 run_blender_script：
把脚本内容写到临时 .py → blender -b <file> -P <script> -- <args>。
脚本内容以内嵌常量方式随应用分发（避免打包资源路径问题）。

探针脚本依赖 vendor 插件包：把 vendor 目录（含 render_monitor/）插入
sys.path 并 register()，使 Scene.rm_shots 等属性可用，从而读出各场景快照。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap

# ---------------------------------------------------------------------------
# 内嵌脚本
# ---------------------------------------------------------------------------

PROBE_SCRIPT = textwrap.dedent(
    """\
    # Render Monitor Queue - 快照枚举探针（blender -b 内运行）
    import json
    import os
    import sys

    try:
        marker = sys.argv.index("--")
    except ValueError:
        print("[probe] 缺少 '--'", file=sys.stderr)
        sys.exit(1)
    args = sys.argv[marker + 1:]
    if len(args) < 2:
        print(f"[probe] 参数不足: {args}", file=sys.stderr)
        sys.exit(1)
    vendor_dir, out_path = args[0], args[1]

    sys.path.insert(0, vendor_dir)
    # 清除可能残留的旧版本插件模块缓存，强制导入 vendor 同源代码
    for _name in ("render_monitor", "render_monitor.core",
                  "render_monitor.utils", "render_monitor.ops", "render_monitor.ui"):
        sys.modules.pop(_name, None)

    import bpy
    import render_monitor

    render_monitor.register()

    scenes = []
    for scene in bpy.data.scenes:
        shots = []
        for s in scene.rm_shots:
            shots.append({
                "uid": s.uid,
                "name": s.name,
                "status": s.status,
                "selected": bool(s.selected),
                "output": s.output_path,
                "error": getattr(s, "error", ""),
            })
        scenes.append({"name": scene.name, "shots": shots})

    payload = {
        "file": bpy.data.filepath,
        "blender_version": bpy.app.version_string,
        "scenes": scenes,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"[probe] ok file={bpy.data.filepath} scenes={len(scenes)} "
          f"shots={sum(len(s['shots']) for s in scenes)}")
    sys.exit(0)
    """
)


def run_blender_script(
    blender_exe: str,
    blend_file: str,
    script_text: str,
    args: list[str] | None = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess:
    """把脚本写入临时文件并 `blender -b <file> -P <script> -- <args>` 运行。"""
    args = list(args or [])
    script_path = None
    try:
        fd, script_path = tempfile.mkstemp(suffix=".py", prefix="rmq_script_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script_text)
        cmd = [blender_exe, "-b", blend_file, "-P", script_path, "--", *args]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    finally:
        if script_path:
            try:
                os.remove(script_path)
            except OSError:
                pass


def probe_blend(blender_exe: str, blend_file: str, vendor_dir: str,
                timeout: int = 240) -> dict:
    """枚举一个 .blend 的场景/快照。返回 dict：
    {ok, returncode, data(dict|None), message, stderr_tail}
    """
    result = {
        "ok": False,
        "returncode": None,
        "data": None,
        "message": "",
        "stderr_tail": "",
    }
    if not blender_exe or not os.path.isfile(blender_exe):
        result["message"] = f"Blender 不存在: {blender_exe!r}"
        return result
    if not os.path.isfile(blend_file):
        result["message"] = f".blend 文件不存在: {blend_file!r}"
        return result
    if not os.path.isdir(vendor_dir):
        result["message"] = f"vendor 插件目录不存在: {vendor_dir!r}"
        return result

    out_fd, out_path = tempfile.mkstemp(suffix=".json", prefix="rmq_probe_")
    os.close(out_fd)
    try:
        try:
            proc = run_blender_script(
                blender_exe, blend_file, PROBE_SCRIPT,
                [vendor_dir, out_path], timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            result["message"] = f"探针超时（>{timeout}s）"
            return result
        result["returncode"] = proc.returncode
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-8:])
        result["stderr_tail"] = tail
        if proc.returncode != 0:
            result["message"] = (
                f"探针失败（退出码 {proc.returncode}）\n{tail or '(无错误输出)'}"
            )
            return result
        with open(out_path, encoding="utf-8") as f:
            data = json.load(f)
        result["data"] = data
        result["ok"] = True
        result["message"] = (
            f"Blender {data.get('blender_version', '?')}："
            f"{len(data.get('scenes', []))} 个场景"
        )
        return result
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result["message"] = f"探针异常: {exc}"
        return result
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass


def find_vendor_dir() -> str:
    """定位 vendor 插件包目录（含 render_monitor/）。

    依次尝试：开发树项目根/vendor → PyInstaller _MEIPASS/vendor →
    包内 rmqueue/vendor（打包时把 vendor 拷入包目录的兜底）。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    meipass = getattr(sys, "_MEIPASS", None)
    candidates = []
    # 开发树：src/rmqueue/../.. = 项目根
    dev = os.path.join(os.path.dirname(os.path.dirname(here)), "vendor")
    candidates.append(dev)
    if meipass:
        candidates.append(os.path.join(meipass, "vendor"))
    # 包目录相邻（src 布局下 src/vendor 或打包复制形态）
    candidates.append(os.path.join(os.path.dirname(here), "vendor"))
    candidates.append(os.path.join(here, "vendor"))
    for cand in candidates:
        if os.path.isdir(os.path.join(cand, "render_monitor")):
            return cand
    raise FileNotFoundError(
        "找不到 vendor/render_monitor 插件包目录（尝试: "
        + ", ".join(candidates) + "）"
    )
