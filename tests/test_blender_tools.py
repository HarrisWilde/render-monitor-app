"""Blender 探测/版本解析测试（纯函数部分，不依赖真实安装）。"""

import unittest

from rmqueue.blender_tools import (
    BlenderInstall,
    blender_installs,
    discover_blender_exes,
    parse_blender_version,
    pick_default,
)


class TestParseVersion(unittest.TestCase):
    def test_directory_name(self):
        self.assertEqual(parse_blender_version(r"C:\Program Files\Blender Foundation\Blender 4.5"),
                         (4, 5, 0))
        self.assertEqual(parse_blender_version(r"/Applications/Blender 5.0.app/Contents/MacOS/Blender"),
                         (5, 0, 0))

    def test_three_part(self):
        self.assertEqual(parse_blender_version("Blender 4.2.1"), (4, 2, 1))

    def test_takes_last_number(self):
        # "Blender 4.5" 路径里其他数字不干扰：取最后一段 x.y
        self.assertEqual(parse_blender_version(r"D:\blender42\Blender Foundation\Blender 5.1"),
                         (5, 1, 0))

    def test_none(self):
        self.assertIsNone(parse_blender_version("nothing here"))


class TestPick(unittest.TestCase):
    def test_pick_highest_version(self):
        picked = pick_default([
            r"C:\PF\Blender Foundation\Blender 4.5\blender.exe",
            r"C:\PF\Blender Foundation\Blender 5.0\blender.exe",
        ])
        self.assertIsNotNone(picked)
        self.assertEqual(picked.version, (5, 0, 0))
        self.assertIn("5.0", picked.exe)

    def test_pick_unknown_version_first_given(self):
        picked = pick_default([r"D:\custom\blender.exe"])
        self.assertEqual(picked.version, (0, 0, 0))

    def test_sorted_desc(self):
        installs = blender_installs([
            r"C:\x\Blender 4.2\blender.exe",
            r"C:\x\Blender 5.2\blender.exe",
            r"C:\x\Blender 4.5\blender.exe",
        ])
        self.assertEqual([i.version for i in installs],
                         [(5, 2, 0), (4, 5, 0), (4, 2, 0)])


class TestDiscover(unittest.TestCase):
    def test_returns_list(self):
        found = discover_blender_exes()
        self.assertIsInstance(found, list)
        for exe in found:
            self.assertIsInstance(exe, str)
            self.assertTrue(exe)


class TestBlenderInstallRepr(unittest.TestCase):
    def test_str(self):
        self.assertIn("4.5", str(BlenderInstall(exe="x", version=(4, 5, 0))))


if __name__ == "__main__":
    unittest.main()
