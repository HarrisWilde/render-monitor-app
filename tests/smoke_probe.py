"""端到端 smoke（需要本机已装 Blender）：

1. 用真实 Blender 无头生成 fixture（2 场景 / 3 快照，含 DONE、未勾选、旧输出）
2. 用 blender_probe.probe_blend 枚举
3. 合并进队列并断言结构、勾选、应用层状态保留语义

用法：
    python tests/smoke_probe.py [blender_exe]      # 缺省取最高版本
    python tests/smoke_probe.py --all              # 用全部发现的 Blender
"""

from __future__ import annotations

import os
import sys
import tempfile

# 允许直接以脚本运行（不用先安装包）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from rmqueue import blender_probe, blender_tools  # noqa: E402
from rmqueue.queue import Queue  # noqa: E402
from tests.fixture_builder import build_fixture  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
VENDOR_DIR = os.path.join(PROJECT_ROOT, "vendor")
FIXTURE = os.path.join(HERE, "data", "fixture.blend")


def run_one(exe: str) -> None:
    name = os.path.basename(os.path.dirname(exe))
    print(f"\n===== Blender: {exe} ({name}) =====")
    os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
    # 每次用独立临时文件，避免上次残留
    with tempfile.NamedTemporaryFile(suffix=".blend", delete=False,
                                     dir=os.path.dirname(FIXTURE)) as f:
        fixture_path = f.name
    try:
        proc = build_fixture(exe, fixture_path, VENDOR_DIR)
        if proc.returncode != 0:
            print("[FAIL] fixture 生成失败\n", proc.stderr[-3000:])
            raise SystemExit(1)
        print("fixture:", [ln for ln in proc.stdout.splitlines() if "fixture]" in ln])

        probe = blender_probe.probe_blend(exe, fixture_path, VENDOR_DIR)
        if not probe["ok"]:
            print("[FAIL] probe:", probe["message"])
            raise SystemExit(1)
        data = probe["data"]
        scenes = {s["name"]: s for s in data["scenes"]}
        assert set(scenes) == {"Scene A", "Scene B"}, scenes.keys()
        shots_a = {s["name"]: s for s in scenes["Scene A"]["shots"]}
        assert set(shots_a) == {"A1", "A2", "A3"}, shots_a.keys()
        assert shots_a["A1"]["status"] == "DONE"
        assert shots_a["A1"]["output"].endswith("A1.png")
        assert shots_a["A2"]["selected"] is False
        assert [s["name"] for s in scenes["Scene B"]["shots"]] == ["B1"]
        print("probe OK:", probe["message"])

        q = Queue()
        stats = q.merge_probe(fixture_path, data["scenes"])
        assert stats == {"scenes_added": 2, "scenes_removed": 0,
                         "shots_added": 4, "shots_removed": 0}, stats
        jobs = q.flatten_selected()
        assert [(j.scene, j.name) for j in jobs] == [
            ("Scene A", "A1"), ("Scene A", "A3"),
            ("Scene B", "B1")], jobs  # A2 未勾选不入列
        shot_a1 = q.shot_by(fixture_path, "Scene A", shots_a["A1"]["uid"])
        assert shot_a1.blend_status == "DONE"
        # 应用层标记失败后重新 merge，状态应保留
        shot_a1.app_status = "FAILED"
        shot_a1.selected = False
        q.merge_probe(fixture_path, data["scenes"])
        assert q.shot_by(fixture_path, "Scene A", shots_a["A1"]["uid"]).app_status == "FAILED"
        assert q.shot_by(fixture_path, "Scene A", shots_a["A1"]["uid"]).selected is False
        print("merge OK (retention semantics)")
    finally:
        try:
            os.remove(fixture_path)
        except OSError:
            pass


def main(argv: list[str]) -> int:
    if "--all" in argv:
        installs = blender_tools.blender_installs()
        if not installs:
            print("未发现任何 Blender 安装")
            return 1
    elif len(argv) > 1:
        installs = [blender_tools.BlenderInstall(exe=os.path.abspath(argv[1]))]
    else:
        picked = blender_tools.pick_default()
        if picked is None:
            print("未发现任何 Blender 安装（可用参数指定 exe 或 --all）")
            return 1
        installs = [picked]
    for inst in installs:
        print(f"[BlenderInstall] {inst.exe} (version={inst.version_str or '?'})")
    for inst in installs:
        run_one(inst.exe)
    print("\nALL SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
