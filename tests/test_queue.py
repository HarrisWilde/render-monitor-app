"""队列模型/持久化测试。"""

import os
import tempfile
import unittest

from rmqueue.queue import Queue, QueueFile, QueueScene, QueueShot


def make_queue() -> Queue:
    q = Queue()
    f1 = QueueFile(path=r"C:\a.blend")
    f1.scenes = [
        QueueScene(name="S1", shots=[
            QueueShot(uid="u1", name="a", selected=True),
            QueueShot(uid="u2", name="b", selected=False),
        ]),
        QueueScene(name="S2", shots=[QueueShot(uid="u3", name="c", selected=True)]),
    ]
    f2 = QueueFile(path=r"C:\b.blend")
    f2.scenes = [QueueScene(name="S1", shots=[QueueShot(uid="u4", name="d")])]
    q.files = [f1, f2]
    return q


class TestFlatten(unittest.TestCase):
    def test_order_and_index(self):
        jobs = make_queue().flatten_selected()
        self.assertEqual([(j.scene, j.name, j.index) for j in jobs],
                         [("S1", "a", 1), ("S2", "c", 2), ("S1", "d", 3)])

    def test_all_unselected_empty(self):
        q = make_queue()
        for f in q.files:
            for s in f.scenes:
                for shot in s.shots:
                    shot.selected = False
        self.assertEqual(q.flatten_selected(), [])


class TestPersistence(unittest.TestCase):
    def test_roundtrip_preserves_state(self):
        q = make_queue()
        q.shot_by(r"C:\a.blend", "S1", "u1").selected = False
        q.shot_by(r"C:\a.blend", "S1", "u1").app_status = "FAILED"
        q.shot_by(r"C:\a.blend", "S1", "u1").output = r"D:\out\a_1.png"
        q.shot_by(r"C:\a.blend", "S1", "u1").error = "boom"
        q.settings.output_dir = r"D:\out"
        q.settings.file_template = "{file}/{scene}/{name}"
        text = q.to_json()
        q2 = Queue.from_json(text)
        self.assertEqual(len(q2.files), 2)
        shot = q2.shot_by(r"C:\a.blend", "S1", "u1")
        self.assertIsNotNone(shot)
        self.assertFalse(shot.selected)
        self.assertEqual(shot.app_status, "FAILED")
        self.assertEqual(shot.output, r"D:\out\a_1.png")
        self.assertEqual(shot.error, "boom")
        self.assertEqual(q2.settings.output_dir, r"D:\out")
        self.assertEqual(q2.settings.file_template, "{file}/{scene}/{name}")

    def test_save_load_file(self):
        q = make_queue()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "queue.json")
            q.save(path)
            q2 = Queue.load(path)
            self.assertEqual(q2.total_shots(), 4)
            self.assertEqual(q2.flatten_selected()[0].name, "a")

    def test_missing_keys_tolerant(self):
        q = Queue.from_json('{"files": [], "settings": {}}')
        self.assertEqual(q.files, [])
        self.assertEqual(q.settings.output_dir, "")

    def test_path_lookup_normalizes_case(self):
        q = make_queue()
        self.assertIsNotNone(q.file_by_path(r"c:\A.BLEND"))
        self.assertIsNone(q.shot_by(r"C:\none.blend", "S1", "u1"))


class TestMergeProbe(unittest.TestCase):
    def test_new_file_adds_scenes_and_shots(self):
        q = Queue()
        stats = q.merge_probe(r"C:\a.blend", [
            {"name": "S1", "shots": [
                {"uid": "u1", "name": "a", "status": "DONE", "selected": True},
            ]},
        ])
        self.assertEqual(stats["scenes_added"], 1)
        self.assertEqual(stats["shots_added"], 1)
        self.assertEqual(q.total_shots(), 1)
        self.assertEqual(q.files[0].scenes[0].shots[0].blend_status, "DONE")

    def test_existing_keeps_app_state_refreshes_blend_fields(self):
        q = make_queue()
        shot = q.shot_by(r"C:\a.blend", "S1", "u1")
        shot.selected = False
        shot.app_status = "FAILED"
        shot.output = r"D:\old.png"
        shot.error = "boom"
        stats = q.merge_probe(r"C:\a.blend", [
            {"name": "S1", "shots": [
                {"uid": "u1", "name": "a-renamed", "status": "DONE",
                 "selected": True, "output": r"D:\inblend.png"},
                {"uid": "u-new", "name": "x", "status": "PENDING", "selected": False},
            ]},
            # S2 整个消失
        ])
        self.assertEqual(stats["shots_added"], 1)
        self.assertEqual(stats["shots_removed"], 1)  # u2 被移除
        self.assertEqual(stats["scenes_removed"], 1)  # S2 被移除
        kept = q.shot_by(r"C:\a.blend", "S1", "u1")
        self.assertEqual(kept.name, "a-renamed")       # 名称刷新
        self.assertFalse(kept.selected)                 # 应用层勾选保留
        self.assertEqual(kept.app_status, "FAILED")
        self.assertEqual(kept.output, r"D:\old.png")
        self.assertEqual(kept.blend_status, "DONE")     # 文件侧字段刷新
        self.assertEqual(kept.blend_output, r"D:\inblend.png")
        new = q.shot_by(r"C:\a.blend", "S1", "u-new")
        self.assertIsNotNone(new)
        self.assertFalse(new.selected)                  # 新项跟随探针初值
        self.assertIsNone(q.shot_by(r"C:\a.blend", "S2", "u3"))

    def test_merge_is_idempotent(self):
        q = Queue()
        scenes = [{"name": "S1", "shots": [{"uid": "u1", "name": "a"}]}]
        q.merge_probe(r"C:\a.blend", scenes)
        stats = q.merge_probe(r"C:\a.blend", scenes)
        self.assertEqual(stats["shots_added"], 0)
        self.assertEqual(q.total_shots(), 1)


if __name__ == "__main__":
    unittest.main()
