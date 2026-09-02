"""端到端渲染冒烟（需要本机已装 Blender）：

fixture（多场景/快照，低分辨率）→ 探针 → 队列 → 串行渲染会话 →
断言：3 张图按模板落盘（含子目录）、无 .rmtmp 残留、状态 DONE/FAILED 正确。

用法：
    python tests/render_e2e.py [blender_exe]      # 缺省取最高版本
    python tests/render_e2e.py --all
"""

from __future__ import annotations

import glob
import os
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from rmqueue import blender_probe, blender_tools, render_session  # noqa: E402
from rmqueue.queue import Queue  # noqa: E402
from tests.fixture_builder import build_fixture  # noqa: E402

VENDOR_DIR = os.path.join(_ROOT, "vendor")


def run_one(exe: str) -> None:
    print(f"\n===== Blender: {exe} =====")
    tmp = tempfile.TemporaryDirectory(prefix="rmq_e2e_")
    try:
        fixture = os.path.join(tmp.name, "job_scene.blend")
        proc = build_fixture(exe, fixture, VENDOR_DIR)
        if proc.returncode != 0 or not os.path.isfile(fixture):
            print("[FAIL] fixture 未落盘 rc=", proc.returncode,
                  "exists=", os.path.isfile(fixture))
            print("stdout tail:\n",
                  "\n".join((proc.stdout or "").splitlines()[-20:]))
            print("stderr tail:\n",
                  "\n".join((proc.stderr or "").splitlines()[-20:]))
            raise SystemExit(1)

        probe = blender_probe.probe_blend(exe, fixture, VENDOR_DIR)
        assert probe["ok"], probe["message"]

        q = Queue()
        q.merge_probe(fixture, probe["data"]["scenes"])
        outdir = os.path.join(tmp.name, "out")
        os.makedirs(outdir)
        q.settings.output_dir = outdir
        q.settings.file_template = "{file}/{scene}/{name} {index}"
        jobs = q.flatten_selected()
        assert len(jobs) == 3, [(j.scene, j.name) for j in jobs]

        # 模拟 Qt worker 的驱动循环：标记 → spawn → 轮询 → finish
        handle = render_session.spawn_session(
            exe, fixture, VENDOR_DIR,
            [j.__dict__ for j in jobs],  # 简易转换：RenderJob 字段即所需键
            outdir, q.settings.file_template,
        )
        # 上面把 RenderJob dataclass 转 dict 会含 index 等，保持与 spawn 契约一致
        for j in jobs:
            q.shot_by(fixture, j.scene, j.uid).app_status = "RENDERING"

        deadline = time.monotonic() + 240
        last = None
        while render_session.session_running(handle):
            last = render_session.poll_session(handle)
            time.sleep(0.5)
            assert time.monotonic() < deadline, "渲染超时"
        proc = handle["process"]
        rc = proc.poll()
        last = render_session.poll_session(handle)
        summary = render_session.finish_session(q, fixture, handle, last, rc)
        print("summary:", summary)
        assert summary["returncode"] == 0
        assert summary["done"] == 3, summary
        assert summary["failed"] == 0, summary

        for j in jobs:
            shot = q.shot_by(fixture, j.scene, j.uid)
            assert shot.app_status == "DONE", (j, shot.app_status)
            assert os.path.isfile(shot.output), shot.output

        pngs = glob.glob(os.path.join(outdir, "**", "*.png"), recursive=True)
        assert len(pngs) == 3, pngs
        leftovers = glob.glob(os.path.join(outdir, "**", "*.rmtmp*"), recursive=True)
        assert not leftovers, leftovers
        # 模板子目录生效：job_scene/Scene_A/... 与 job_scene/Scene_B/...
        rels = sorted(os.path.relpath(p, outdir) for p in pngs)
        print("outputs:", rels)
        assert any(p.startswith("job_scene" + os.sep + "Scene_A") for p in rels)
        assert any(p.startswith("job_scene" + os.sep + "Scene_B") for p in rels)
        print("E2E RENDER OK (3 outputs, atomic, statuses clean)")
    finally:
        tmp.cleanup()


def main(argv: list[str]) -> int:
    if "--all" in argv:
        installs = blender_tools.blender_installs()
    elif len(argv) > 1:
        installs = [blender_tools.BlenderInstall(exe=os.path.abspath(argv[1]))]
    else:
        picked = blender_tools.pick_default()
        installs = [picked] if picked else []
    if not installs:
        print("未发现 Blender")
        return 1
    for inst in installs:
        print(f"[BlenderInstall] {inst.exe} (v{inst.version_str or '?'})")
        run_one(inst.exe)
    print("\nALL RENDER E2E PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
