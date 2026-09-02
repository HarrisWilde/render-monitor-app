"""mmap 进度协议往返测试（协议双端唯一实现的一致性保障）。"""

import os
import tempfile
import unittest

from rmqueue import progress


class TestProgressProtocol(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "p.bin")
            payload = {"state": "running", "total": 3, "jobs": [
                {"scene": "S1", "uid": "u1", "status": "DONE", "path": "x.png"},
            ]}
            progress.write_file(path, payload)
            got = progress.read_file(path)
            self.assertEqual(got, payload)

    def test_rewrite_shorter(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "p.bin")
            progress.write_file(path, {"state": "running", "jobs": [{"x": "y" * 500}]})
            progress.write_file(path, {"state": "done", "jobs": []})
            self.assertEqual(progress.read_file(path), {"state": "done", "jobs": []})

    def test_read_missing_or_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "none.bin")
            self.assertIsNone(progress.read_file(path))
            empty = os.path.join(td, "empty.bin")
            with open(empty, "wb") as f:
                f.write(b"")
            self.assertIsNone(progress.read_file(empty))
            tiny = os.path.join(td, "tiny.bin")
            with open(tiny, "wb") as f:
                f.write(b"\x00\x00")
            self.assertIsNone(progress.read_file(tiny))

    def test_corrupt_payload_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "p.bin")
            progress.write_file(path, {"a": 1})
            with open(path, "r+b") as f:
                f.seek(progress.HEADER)
                f.write(b"{not-json")
            self.assertIsNone(progress.read_file(path))


if __name__ == "__main__":
    unittest.main()
