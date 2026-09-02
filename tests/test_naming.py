"""命名/输出路径逻辑测试。"""

import unittest

from rmqueue import naming


class TestSanitizeSegment(unittest.TestCase):
    def test_invalid_chars_replaced(self):
        self.assertEqual(naming.sanitize_segment('a/b\\c:d*e?"f<g>h|i'), "a_b_c_d_e_f_g_h_i")

    def test_space_to_underscore(self):
        self.assertEqual(naming.sanitize_segment("hello world"), "hello_world")

    def test_empty_and_dots(self):
        self.assertEqual(naming.sanitize_segment(""), "shot")
        self.assertEqual(naming.sanitize_segment("."), "shot")
        self.assertEqual(naming.sanitize_segment(".."), "shot")


class TestSanitizeRelpath(unittest.TestCase):
    def test_keeps_slash_but_normalizes_backslash(self):
        self.assertEqual(naming.sanitize_relpath("a\\b/c"), "a/b/c")

    def test_traversal_blocked(self):
        self.assertEqual(naming.sanitize_relpath("../..//etc"), "etc")
        self.assertEqual(naming.sanitize_relpath(".."), "shot")

    def test_empty(self):
        self.assertEqual(naming.sanitize_relpath(""), "shot")


class TestFormatOutputRelpath(unittest.TestCase):
    def test_default_template(self):
        rel = naming.format_output_relpath(
            "{file}/{scene}/{name} {index}",
            r"C:\work\my_shot.blend", "Scene 01", "快照 01", index=3,
        )
        self.assertEqual(rel, "my_shot/Scene_01/快照_01_3")

    def test_index_zero_padding(self):
        rel = naming.format_output_relpath(
            "{file}/{name} {index:02d}", "a.blend", "S", "n", index=7,
        )
        self.assertEqual(rel, "a/n_07")

    def test_frame_padding(self):
        rel = naming.format_output_relpath(
            "{name}_{frame:04d}", "a.blend", "S", "n", frame=17,
        )
        self.assertEqual(rel, "n_0017")

    def test_constant_template_falls_back(self):
        rel = naming.format_output_relpath("fixed.png", "a.blend", "S", "n", index=2)
        self.assertEqual(rel, "a/S/n_2")  # 回退默认，避免互相覆盖

    def test_name_slash_makes_subfolder(self):
        rel = naming.format_output_relpath("{name}", "a.blend", "S", "dir/shot1", index=1)
        self.assertEqual(rel, "dir/shot1")

    def test_frame_none_uses_zero(self):
        rel = naming.format_output_relpath("{name} {frame:02d}", "a.blend", "S", "n")
        self.assertTrue(rel.endswith("00"))


class TestBuildAbsOutputPath(unittest.TestCase):
    def test_ext_normalized(self):
        out = naming.build_abs_output_path(r"C:\out", "a/b", ".PNG")
        self.assertTrue(out.endswith(r"a\b.png") or out.endswith("a/b.png"))

    def test_default_ext(self):
        out = naming.build_abs_output_path(r"C:\out", "x", "")
        self.assertTrue(out.endswith("x.png"))


class TestCollisionPairs(unittest.TestCase):
    def test_duplicates_found(self):
        pairs = naming.collision_pairs(["a", "b", "a", "c", "b"])
        self.assertEqual(sorted(pairs), [(0, 2), (1, 4)])

    def test_empty_and_unique(self):
        self.assertEqual(naming.collision_pairs([]), [])
        self.assertEqual(naming.collision_pairs(["a", "b"]), [])


if __name__ == "__main__":
    unittest.main()
