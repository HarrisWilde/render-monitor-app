"""生成带快照的测试 .blend（在 blender -b 内运行）。

数据级 API（bpy.data.*）创建对象/相机/灯光，避免依赖 3D 视图上下文；
注册 vendor 插件包后用 render_monitor.core 捕获快照并写入 Scene.rm_shots。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

FIXTURE_SCRIPT = textwrap.dedent(
    """\
    # Render Monitor Queue - fixture 生成（blender -b 内运行）
    import json
    import os
    import sys
    import uuid

    try:
        marker = sys.argv.index("--")
    except ValueError:
        sys.exit("缺少 '--'")
    args = sys.argv[marker + 1:]
    if len(args) < 2:
        sys.exit(f"参数不足: {args}")
    vendor_dir, out_blend = args[0], args[1]

    sys.path.insert(0, vendor_dir)
    for _name in ("render_monitor", "render_monitor.core",
                  "render_monitor.utils", "render_monitor.ops", "render_monitor.ui"):
        sys.modules.pop(_name, None)

    import bpy
    import render_monitor
    render_monitor.register()
    from render_monitor import core

    def _empty(scene, name, loc=(0.0, 0.0, 0.0)):
        obj = bpy.data.objects.new(name, None)
        obj.location = loc
        scene.collection.objects.link(obj)
        return obj

    def _camera(scene, name="Camera"):
        cam = bpy.data.cameras.new(name)
        obj = bpy.data.objects.new(name, cam)
        scene.collection.objects.link(obj)
        scene.camera = obj
        return obj

    def _light(scene, name="Light", energy=100.0):
        light = bpy.data.lights.new(name, type="POINT")
        light.energy = energy
        obj = bpy.data.objects.new(name, light)
        scene.collection.objects.link(obj)
        return obj

    def _shot(scene, name, selected=True, status="PENDING", output=""):
        shot = scene.rm_shots.add()
        shot.uid = uuid.uuid4().hex
        shot.name = name
        shot.selected = selected
        shot.status = status
        shot.output_path = output
        shot.data_json = json.dumps(core.capture_scene_state(scene), ensure_ascii=False)

    def _lowres(scene):
        # 低分辨率，E2E 渲染秒级完成
        scene.render.resolution_x = 48
        scene.render.resolution_y = 48
        scene.render.resolution_percentage = 100

    # --- 场景 A：2 个对象 + 相机 + 灯光，2 个快照（一个已完成、一个未勾选）
    scene_a = bpy.data.scenes[0]
    scene_a.name = "Scene A"
    if scene_a.world is None and bpy.data.worlds:
        scene_a.world = bpy.data.worlds[0]
    a1 = _empty(scene_a, "Cylinder_A", (1.0, 0.0, 0.0))
    a2 = _empty(scene_a, "Box_A", (0.0, 2.0, 0.0))
    _camera(scene_a)
    _light(scene_a)
    _lowres(scene_a)
    _shot(scene_a, "A1", selected=True, status="DONE", output=r"D:\\old\\A1.png")
    _shot(scene_a, "A2", selected=False)
    _shot(scene_a, "A3", selected=True)

    # --- 场景 B：1 个快照
    scene_b = bpy.data.scenes.new("Scene B")
    if scene_b.world is None and bpy.data.worlds:
        scene_b.world = bpy.data.worlds[0]
    _empty(scene_b, "Cylinder_B", (0.0, 0.0, 3.0))
    _camera(scene_b)
    _lowres(scene_b)
    _shot(scene_b, "B1", selected=True)

    bpy.ops.wm.save_as_mainfile(filepath=out_blend)
    print(f"[fixture] ok scenes={[s.name for s in bpy.data.scenes]} "
          f"file={bpy.data.filepath}")
    sys.exit(0)
    """
)


def build_fixture(blender_exe: str, out_blend: str, vendor_dir: str,
                  timeout: int = 240) -> subprocess.CompletedProcess:
    """用给定 Blender 无头生成 fixture 文件。"""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(FIXTURE_SCRIPT)
        script_path = f.name
    try:
        cmd = [blender_exe, "-b", "-P", script_path, "--", vendor_dir, out_blend]
        return subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass


if __name__ == "__main__":  # pragma: no cover
    exe, out, vendor = sys.argv[1], sys.argv[2], sys.argv[3]
    proc = build_fixture(exe, out, vendor)
    print(proc.stdout[-2000:])
    print(proc.stderr[-2000:])
    print("fixture exit:", proc.returncode)
    sys.exit(0 if proc.returncode == 0 else 1)
