"""渲染会话收尾/状态一致性逻辑测试（不启动真实 Blender）。

通过直接构造 payload 与队列状态，验证：
- 正常完成：DONE/FAILED 落回队列并带输出路径；
- 崩溃（非 0）：RENDERING → FAILED（中断），未开始 PENDING 保留；
- 早退（无 payload / state=error）：全部 PENDING → FAILED；
- 用户取消：RENDERING → PENDING，已完成的保留。
"""

import os
import unittest

from rmqueue.queue import Queue, QueueFile, QueueScene, QueueShot
from rmqueue import render_session


def make_handle(jobs):
    return {
        "process": None,
        "tmpdir": os.devnull,  # 不会真正清理
        "progress_path": "",
        "jobs": jobs,
        "log_path": r"C:\log.txt",
    }


def make_queue() -> Queue:
    q = Queue()
    f = QueueFile(path=r"C:\a.blend")
    f.scenes = [
        QueueScene(name="S1", shots=[
            QueueShot(uid="u1", name="a"),
            QueueShot(uid="u2", name="b"),
            QueueShot(uid="u3", name="c"),
        ]),
    ]
    q.files = [f]
    return q


JOBS = [
    {"scene": "S1", "uid": "u1", "index": 1, "name": "a"},
    {"scene": "S1", "uid": "u2", "index": 2, "name": "b"},
    {"scene": "S1", "uid": "u3", "index": 3, "name": "c"},
]


def mark_all_rendering(q, fpath):
    for j in JOBS:
        shot = q.shot_by(fpath, "S1", j["uid"])
        shot.app_status = render_session.STATUS_RENDERING


class TestFinishNormal(unittest.TestCase):
    def test_all_done(self):
        q = make_queue()
        fpath = r"C:\a.blend"
        mark_all_rendering(q, fpath)
        payload = {"state": "done", "total": 3, "jobs": [
            {"scene": "S1", "uid": "u1", "status": "DONE", "path": r"D:\o\a.png"},
            {"scene": "S1", "uid": "u2", "status": "DONE", "path": r"D:\o\b.png"},
            {"scene": "S1", "uid": "u3", "status": "FAILED", "error": "boom"},
        ]}
        summary = render_session.finish_session(q, fpath, make_handle(JOBS),
                                                payload, 0)
        self.assertEqual(summary["done"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(q.shot_by(fpath, "S1", "u1").output, r"D:\o\a.png")
        self.assertEqual(q.shot_by(fpath, "S1", "u3").error, "boom")
        self.assertIn("成功 2", summary["message"])

    def test_failed_job_keeps_going(self):
        q = make_queue()
        fpath = r"C:\a.blend"
        mark_all_rendering(q, fpath)
        payload = {"state": "done", "total": 3, "jobs": [
            {"scene": "S1", "uid": "u1", "status": "DONE", "path": "x.png"},
            {"scene": "S1", "uid": "u2", "status": "FAILED", "error": "no file"},
            {"scene": "S1", "uid": "u3", "status": "DONE", "path": "z.png"},
        ]}
        summary = render_session.finish_session(q, fpath, make_handle(JOBS),
                                                payload, 0)
        self.assertEqual((summary["done"], summary["failed"]), (2, 1))


class TestFinishCrash(unittest.TestCase):
    def test_mid_render_crash_marks_current_failed(self):
        q = make_queue()
        fpath = r"C:\a.blend"
        mark_all_rendering(q, fpath)
        # u1 已完成，u2 渲染中被杀，u3 尚未开始
        q.shot_by(fpath, "S1", "u1").app_status = render_session.STATUS_DONE
        q.shot_by(fpath, "S1", "u3").app_status = render_session.STATUS_PENDING
        payload = {"state": "running", "total": 3, "jobs": [
            {"scene": "S1", "uid": "u1", "status": "DONE", "path": "x.png"},
            {"scene": "S1", "uid": "u2", "status": "RENDERING"},
            {"scene": "S1", "uid": "u3", "status": "PENDING"},
        ]}
        summary = render_session.finish_session(q, fpath, make_handle(JOBS),
                                                payload, 1)
        self.assertEqual(q.shot_by(fpath, "S1", "u2").app_status,
                         render_session.STATUS_FAILED)
        self.assertIn("中断", q.shot_by(fpath, "S1", "u2").error)
        # u3 未开始且非早退：保留 PENDING
        self.assertEqual(q.shot_by(fpath, "S1", "u3").app_status,
                         render_session.STATUS_PENDING)
        self.assertEqual((summary["done"], summary["failed"]), (1, 1))

    def test_crash_early_no_payload_marks_all_pending_failed(self):
        q = make_queue()
        fpath = r"C:\a.blend"
        mark_all_rendering(q, fpath)
        summary = render_session.finish_session(q, fpath, make_handle(JOBS),
                                                None, 3)
        for uid in ("u1", "u2", "u3"):
            self.assertEqual(q.shot_by(fpath, "S1", uid).app_status,
                             render_session.STATUS_FAILED)
        self.assertEqual((summary["done"], summary["failed"]), (0, 3))

    def test_fatal_error_payload_marks_all_failed(self):
        q = make_queue()
        fpath = r"C:\a.blend"
        mark_all_rendering(q, fpath)
        payload = {"state": "error", "total": 0, "jobs": [
            {"scene": "", "uid": "", "status": "FAILED", "error": "trace..."}]}
        summary = render_session.finish_session(q, fpath, make_handle(JOBS),
                                                payload, 1)
        for uid in ("u1", "u2", "u3"):
            self.assertEqual(q.shot_by(fpath, "S1", uid).app_status,
                             render_session.STATUS_FAILED)
        self.assertEqual(summary["failed"], 3)


class TestFinishCancel(unittest.TestCase):
    def test_cancel_resets_rendering_to_pending(self):
        q = make_queue()
        fpath = r"C:\a.blend"
        mark_all_rendering(q, fpath)
        q.shot_by(fpath, "S1", "u1").app_status = render_session.STATUS_DONE
        payload = {"state": "running", "total": 3, "jobs": [
            {"scene": "S1", "uid": "u1", "status": "DONE", "path": "x.png"},
            {"scene": "S1", "uid": "u2", "status": "RENDERING"},
        ]}
        summary = render_session.finish_session(q, fpath, make_handle(JOBS),
                                                payload, -15, cancelled=True)
        self.assertEqual(q.shot_by(fpath, "S1", "u1").app_status,
                         render_session.STATUS_DONE)
        self.assertEqual(q.shot_by(fpath, "S1", "u2").app_status,
                         render_session.STATUS_PENDING)
        self.assertIn("已停止", summary["message"])


if __name__ == "__main__":
    unittest.main()
