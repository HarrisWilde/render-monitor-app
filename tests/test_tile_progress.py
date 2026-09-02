"""分块进度插值逻辑测试（与插件 rm_job 算法对齐的纯函数）。"""

import unittest

from rmqueue.tile_progress import shot_progress


class TestSingleTile(unittest.TestCase):
    def test_sample_ratio(self):
        p = shot_progress(25, 100, 0, 1, [], prev=-1)
        self.assertAlmostEqual(p, 0.25)

    def test_monotonic_none_when_stale(self):
        p = shot_progress(25, 100, 0, 1, [], prev=-1)
        # 更小或相等的进度不应回退
        self.assertIsNone(shot_progress(20, 100, 0, 1, [], prev=p))


class TestMultiTileWeights(unittest.TestCase):
    def test_weighted_accumulation(self):
        # 3 块：权重 0.5 / 0.25 / 0.25（模拟边缘块更小）
        weights = [0.5, 0.25, 0.25]
        # 第一块渲染一半 → 0.5 * 0.5
        p1 = shot_progress(50, 100, 0, 3, weights, prev=-1)
        self.assertAlmostEqual(p1, 0.25)
        # 第一块完成、第二块进行到一半 → 0.5 + 0.25*0.5
        p2 = shot_progress(50, 100, 1, 3, weights, prev=p1)
        self.assertAlmostEqual(p2, 0.625)
        # 第二块也完成、第三块进行中 → 0.75 + 0.25*0.5
        p3 = shot_progress(50, 100, 2, 3, weights, prev=p2)
        self.assertAlmostEqual(p3, 0.875)

    def test_tile_switch_no_double_count(self):
        """块完成瞬间（cur==total 残留满格）不应重复计入刚完成的块。"""
        weights = [0.5, 0.25, 0.25]
        prev = 0.5  # 第一块已完成
        # 第二块 stats：td=1, cur=100 == ttl=100（残留上一块满值）
        self.assertIsNone(shot_progress(100, 100, 1, 3, weights, prev=prev))
        # 随后第二块真正开始：cur=1 应推进到 0.5 + 0.25*(1/100)
        p = shot_progress(1, 100, 1, 3, weights, prev=prev)
        self.assertAlmostEqual(p, 0.5025)

    def test_equal_weight_fallback_when_no_weights(self):
        p = shot_progress(50, 100, 1, 2, [], prev=-1)
        self.assertAlmostEqual(p, 0.75)  # (1 + 0.5) / 2

    def test_no_samples_tiles_only(self):
        p = shot_progress(0, 0, 2, 4, [], prev=-1)
        self.assertAlmostEqual(p, 0.5)
        # 再次报相同块数不应回退/前进
        self.assertIsNone(shot_progress(0, 0, 2, 4, [], prev=p))

    def test_clamped(self):
        # 第二块起全部按 0.01 权重：99/100 采样 → 0.99 + 0.01*0.99
        p = shot_progress(99, 100, 99, 100, [0.01] * 100, prev=-1)
        self.assertAlmostEqual(p, 0.9999)


if __name__ == "__main__":
    unittest.main()
