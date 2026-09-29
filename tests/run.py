"""cmsketch 既有用例（unittest）。

起点：本文件全部通过 —— 只覆盖既有的 `add` / `estimate`，
不对本次要补的合并、保守更新、序列化、top-k 下任何断言。**勿改本文件。**
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "src"))

from cmsketch import CountMinSketch  # noqa: E402


class LegacyTests(unittest.TestCase):
    def test_fresh_sketch_estimate_zero(self):
        cms = CountMinSketch(32, 4, seed=1)
        self.assertEqual(cms.estimate("never-added"), 0)

    def test_single_key_exact(self):
        cms = CountMinSketch(32, 4, seed=1)
        cms.add("only", 5)
        self.assertEqual(cms.estimate("only"), 5)

    def test_default_count_is_one(self):
        cms = CountMinSketch(32, 4, seed=2)
        cms.add("k")
        self.assertEqual(cms.estimate("k"), 1)

    def test_add_is_cumulative(self):
        cms = CountMinSketch(32, 4, seed=2)
        cms.add("k", 3)
        cms.add("k", 4)
        self.assertEqual(cms.estimate("k"), 7)

    def test_add_returns_self(self):
        cms = CountMinSketch(32, 4, seed=0)
        self.assertIs(cms.add("k"), cms)

    def test_estimate_never_below_truth(self):
        cms = CountMinSketch(64, 5, seed=9)
        stream = [("a", 3), ("b", 7), ("c", 1), ("a", 2)]
        for key, count in stream:
            cms.add(key, count)
        for key, truth in (("a", 5), ("b", 7), ("c", 1)):
            self.assertGreaterEqual(cms.estimate(key), truth)

    def test_invalid_dimensions_rejected(self):
        with self.assertRaises(ValueError):
            CountMinSketch(0, 4)
        with self.assertRaises(ValueError):
            CountMinSketch(8, -1)


if __name__ == "__main__":
    unittest.main(verbosity=2)