"""ペース指標と4コーナー隊列のテスト。

固定したいのは**向き**である。符号を取り違えると「ハイペースを差した馬」と
「スローを差した馬」が入れ替わり、エラーは出ないまま結論が反転する。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from keiba.tenkai import (GAP, field_spread, last_corner_ranks, pace_raw,
                           parse_corner, spread_per_horse)

PACE = Path("data/profiles/jra/pace.json")
TAIRE = Path("data/profiles/jra/taire.json")


class TestFieldSpread(unittest.TestCase):
    def test_all_abreast_is_zero(self):
        self.assertEqual(field_spread("(1,2,3,4,5,6)"), (0.0, 6))

    def test_brackets_do_not_add_gap(self):
        """括弧の中の「,」は併走なので馬身差に数えない。"""
        a = field_spread("(1,2)(3,4)(5,6)")[0]
        b = field_spread("1,2,3,4,5,6")[0]
        self.assertLess(a, b)

    def test_symbols_are_ordered(self):
        self.assertLess(GAP[","], GAP["-"])
        self.assertLess(GAP["-"], GAP["="])
        self.assertLess(field_spread("1,2,3,4,5")[0], field_spread("1-2-3-4-5")[0])
        self.assertLess(field_spread("1-2-3-4-5")[0], field_spread("1=2=3=4=5")[0])

    def test_inner_mark_is_ignored(self):
        self.assertEqual(field_spread("(*1,2)3,4,5,6"), field_spread("(1,2)3,4,5,6"))

    def test_short_field_is_none(self):
        self.assertIsNone(field_spread("1,2,3"))
        self.assertIsNone(field_spread(""))

    def test_per_horse_divides_by_field(self):
        """頭数が違っても比べられるよう1頭あたりにする。"""
        few = spread_per_horse("1-2-3-4-5")
        many = spread_per_horse("1-2-3-4-5-6-7-8-9-10")
        self.assertAlmostEqual(few, many, places=6)


class TestParseCorner(unittest.TestCase):
    def test_simple_order(self):
        self.assertEqual(parse_corner("4(11,12)(2,13,7,16)-(3,9,10)5,14(8,15)-1,6", 16),
                          [4, 11, 12, 2, 13, 7, 16, 3, 9, 10, 5, 14, 8, 15, 1, 6])

    def test_glued_single_digits_are_split(self):
        # "123"は18を超えるので、1頭ずつの単勝馬番(1,2,3)の連結とみなして割る
        self.assertEqual(parse_corner("123", 3), [1, 2, 3])

    def test_field_size_mismatch_is_none(self):
        self.assertIsNone(parse_corner("1,2,3", 16))

    def test_unreadable_is_none(self):
        self.assertIsNone(parse_corner("", 8))


class TestLastCornerRanks(unittest.TestCase):
    def test_rank_by_umaban(self):
        ranks = last_corner_ranks("3,1-2", 3)
        self.assertEqual(ranks, {3: 1, 1: 2, 2: 3})

    def test_unreadable_is_empty(self):
        self.assertEqual(last_corner_ranks("", 8), {})
        self.assertEqual(last_corner_ranks("1,2", 8), {})  # 頭数と合わない


class TestPaceRaw(unittest.TestCase):
    def test_slow_first_half_is_positive(self):
        """前半が遅く上がりが速い＝スロー＝正。ここが逆だと結論が反転する。"""
        # 1600m・走破95.0秒・上がり33.0秒 → 前半1000mを62.0秒(12.4/200m)、
        # 上がりは11.0/200m なのでスロー寄り
        self.assertGreater(pace_raw(95.0, 33.0, 1600), 0)

    def test_fast_first_half_is_negative(self):
        # 同じ距離で上がりが遅い＝前半が速かった＝ハイ寄り
        self.assertLess(pace_raw(95.0, 37.0, 1600), 0)

    def test_unusable_input_is_none(self):
        self.assertIsNone(pace_raw(None, 33.0, 1600))
        self.assertIsNone(pace_raw(95.0, None, 1600))
        self.assertIsNone(pace_raw(95.0, 33.0, 600))     # 前半が無い
        self.assertIsNone(pace_raw(33.0, 35.0, 1600))    # タイム < 上がり


@unittest.skipUnless(PACE.exists() and TAIRE.exists(), "指標が未生成")
class TestRealIndices(unittest.TestCase):
    """実データで作った指標のカバー率と向きを固定する。"""

    @classmethod
    def setUpClass(cls):
        cls.pace = json.loads(PACE.read_text(encoding="utf-8"))
        cls.taire = json.loads(TAIRE.read_text(encoding="utf-8"))

    def test_coverage(self):
        self.assertGreater(len(self.pace), 5000)
        self.assertGreater(len(self.taire), 5000)

    def test_high_pace_races_have_longer_field(self):
        """ハイペースほど隊列が縦長になる（物理的に正しい向き）。

        これが崩れたら、どちらかのパースが壊れている。
        """
        import statistics
        pairs = [(self.pace[k], self.taire[k]["縦長"])
                 for k in self.pace if k in self.taire]
        pairs.sort()
        k = len(pairs) // 3
        high = statistics.median(t for _, t in pairs[:k])
        slow = statistics.median(t for _, t in pairs[2 * k:])
        self.assertGreater(high, slow, f"ハイ{high:.2f} ≦ スロー{slow:.2f}")


if __name__ == "__main__":
    unittest.main()
