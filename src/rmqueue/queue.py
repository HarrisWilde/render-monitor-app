"""队列模型与项目 JSON 持久化（纯逻辑，不依赖 Qt）。

层级：Queue → QueueFile(blend 文件) → QueueScene → QueueShot。
渲染顺序 = 扁平化顺序：文件按 UI 顺序 → 场景按文件内顺序 → 快照按
场景内顺序（勾选的才渲染）。{index} 用扁平序号（从 1 开始）。

状态语义：
- shot.selected       是否参与本次渲染（UI 勾选，随项目保存）
- shot.app_status     应用层渲染结果：PENDING/DONE/FAILED（随项目保存）
- shot.blend_status   文件内插件状态（枚举时的只读快照，仅展示）
- shot.output         应用渲染成功后记录的绝对输出路径
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class QueueShot:
    uid: str
    name: str = "快照"
    selected: bool = True
    app_status: str = "PENDING"  # PENDING | RENDERING | DONE | FAILED
    output: str = ""
    error: str = ""
    blend_status: str = "PENDING"  # 文件内插件状态（只读参考）
    blend_output: str = ""  # 文件内插件记录的输出（只读参考）

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "name": self.name,
            "selected": self.selected,
            "app_status": self.app_status,
            "output": self.output,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QueueShot":
        return cls(
            uid=str(d.get("uid", "")),
            name=str(d.get("name", "快照")),
            selected=bool(d.get("selected", True)),
            app_status=str(d.get("app_status", "PENDING")),
            output=str(d.get("output", "")),
            error=str(d.get("error", "")),
        )


@dataclass
class QueueScene:
    name: str
    shots: list[QueueShot] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "shots": [s.to_dict() for s in self.shots]}

    @classmethod
    def from_dict(cls, d: dict) -> "QueueScene":
        return cls(
            name=str(d.get("name", "")),
            shots=[QueueShot.from_dict(s) for s in d.get("shots", [])],
        )


@dataclass
class QueueFile:
    path: str
    scenes: list[QueueScene] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"path": self.path, "scenes": [s.to_dict() for s in self.scenes]}

    @classmethod
    def from_dict(cls, d: dict) -> "QueueFile":
        return cls(
            path=str(d.get("path", "")),
            scenes=[QueueScene.from_dict(s) for s in d.get("scenes", [])],
        )

    def all_shots(self) -> list[QueueShot]:
        return [s for scene in self.scenes for s in scene.shots]


@dataclass
class ProjectSettings:
    output_dir: str = ""
    file_template: str = "{file}/{scene}/{name} {index}"
    blender_exe: str = ""

    def to_dict(self) -> dict:
        return {
            "output_dir": self.output_dir,
            "file_template": self.file_template,
            "blender_exe": self.blender_exe,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "ProjectSettings":
        d = d or {}
        return cls(
            output_dir=str(d.get("output_dir", "")),
            file_template=str(d.get("file_template", "{file}/{scene}/{name} {index}")),
            blender_exe=str(d.get("blender_exe", "")),
        )


@dataclass
class RenderJob:
    """扁平化后的单个渲染任务。"""

    file_path: str
    scene: str
    uid: str
    name: str
    index: int  # 1-based 扁平序号


@dataclass
class Queue:
    files: list[QueueFile] = field(default_factory=list)
    settings: ProjectSettings = field(default_factory=ProjectSettings)

    # ---- 查询 ----
    def file_by_path(self, path: str) -> QueueFile | None:
        for f in self.files:
            if os.path.normcase(os.path.abspath(f.path)) == os.path.normcase(os.path.abspath(path)):
                return f
        return None

    def total_shots(self) -> int:
        return sum(len(f.all_shots()) for f in self.files)

    def flatten_selected(self) -> list[RenderJob]:
        """按 UI/文件顺序扁平化勾选的快照；index 从 1 起。"""
        jobs: list[RenderJob] = []
        for f in self.files:
            for scene in f.scenes:
                for s in scene.shots:
                    if s.selected:
                        jobs.append(
                            RenderJob(f.path, scene.name, s.uid, s.name, len(jobs) + 1)
                        )
        return jobs

    def shot_by(self, file_path: str, scene: str, uid: str) -> QueueShot | None:
        f = self.file_by_path(file_path)
        if f is None:
            return None
        for scene_obj in f.scenes:
            if scene_obj.name == scene:
                for s in scene_obj.shots:
                    if s.uid == uid:
                        return s
        return None

    def merge_probe(self, file_path: str, scenes_data: list[dict]) -> dict:
        """把探针（权威）场景/快照清单合并进队列。

        - 已有快照：保留应用层 selected/app_status/output/error，
          刷新 name/blend_status/blend_output；
        - 新快照：按探针 selected 初值加入（无则默认勾选）；
        - 已消失的快照/场景：从队列移除。
        返回 {"scenes_added", "scenes_removed", "shots_added", "shots_removed"}。
        """
        qf = self.file_by_path(file_path)
        if qf is None:
            qf = QueueFile(path=file_path)
            self.files.append(qf)

        stats = {"scenes_added": 0, "scenes_removed": 0,
                 "shots_added": 0, "shots_removed": 0}
        new_scenes: list[QueueScene] = []
        probe_names = set()
        for sd in scenes_data:
            scene_name = str(sd.get("name", ""))
            if not scene_name:
                continue
            probe_names.add(scene_name)
            old_scene = next((s for s in qf.scenes if s.name == scene_name), None)
            if old_scene is None:
                old_scene = QueueScene(name=scene_name)
                stats["scenes_added"] += 1
            old_by_uid = {s.uid: s for s in old_scene.shots}
            new_shots: list[QueueShot] = []
            probe_uids = set()
            for raw in sd.get("shots", []):
                uid = str(raw.get("uid", ""))
                if not uid:
                    continue
                probe_uids.add(uid)
                old = old_by_uid.get(uid)
                if old is not None:
                    # 应用层状态保留；文件侧字段刷新
                    old.name = str(raw.get("name") or old.name)
                    old.blend_status = str(raw.get("status") or old.blend_status)
                    old.blend_output = str(raw.get("output") or old.blend_output)
                    new_shots.append(old)
                else:
                    new_shots.append(QueueShot(
                        uid=uid,
                        name=str(raw.get("name") or "快照"),
                        selected=bool(raw.get("selected", True)),
                        blend_status=str(raw.get("status") or "PENDING"),
                        blend_output=str(raw.get("output") or ""),
                    ))
                    stats["shots_added"] += 1
            if old_scene is not None:
                stats["shots_removed"] += sum(
                    1 for s in old_scene.shots if s.uid not in probe_uids
                )
            old_scene.shots = new_shots
            new_scenes.append(old_scene)
        stats["scenes_removed"] = sum(
            1 for s in qf.scenes if s.name not in probe_names
        )
        qf.scenes = new_scenes
        return stats

    # ---- 持久化 ----
    def to_dict(self) -> dict:
        return {
            "version": 1,
            "settings": self.settings.to_dict(),
            "files": [f.to_dict() for f in self.files],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "Queue":
        files = [QueueFile.from_dict(f) for f in d.get("files", [])]
        # 仅保留仍存在的文件？不：路径可能暂时离线，保留并让 UI 标红。
        return cls(files=files, settings=ProjectSettings.from_dict(d.get("settings")))

    @classmethod
    def from_json(cls, text: str) -> "Queue":
        return cls.from_dict(json.loads(text))

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(self.to_json())

    @classmethod
    def load(cls, path: str) -> "Queue":
        with open(path, encoding="utf-8") as fp:
            return cls.from_json(fp.read())
