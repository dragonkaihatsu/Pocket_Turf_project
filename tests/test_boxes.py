"""点数別の買い目候補。買う人が幅を選べるようにするための表示。

9/4の12Rで1着がスコア4位・2着が6位だったように、幅を広げれば拾える
ケースがある。一方で広げるほど回収率は下がる。両方を並べて出す。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.boxes import BoxOption, build_options, tier_of

STATS = {
    "レース数": 241,
    "点数別": {
        "馬連": {
            "4": {"1倍台": {"n": 108, "点数": 6, "的中率": 0.48, "回収率": 1.14,
                           "区間下": 0.64, "区間上": 1.76, "黒字確率": 0.64},
                  "全体": {"n": 241, "点数": 6, "的中率": 0.44, "回収率": 1.35,
                          "区間下": 0.82, "区間上": 2.05, "黒字確率": 0.82}},
            "6": {"全体": {"n": 241, "点数": 15, "的中率": 0.64, "回収率": 0.77,
                          "区間下": 0.55, "区間上": 1.05, "黒字確率": 0.08}},
        },
    },
}


class TestTier(unittest.TestCase):
    def test_tier_boundaries(self):
        self.assertEqual(tier_of(1.9), "1倍台")
        self.assertEqual(tier_of(2.0), "2倍台")
        self.assertEqual(tier_of(2.9), "2倍台")
        self.assertEqual(tier_of(3.0), "3倍以上")
        self.assertEqual(tier_of(None), "全体")


class TestBuildOptions(unittest.TestCase):
    ORDER = [3, 14, 8, 2, 4, 12, 10, 6]

    def test_widths_take_the_top_n_in_score_order(self):
        opts = {(o.kind, o.width): o for o in build_options(self.ORDER, stats=STATS)}
        self.assertEqual(opts[("馬連", 4)].umaban, [3, 14, 8, 2])
        self.assertEqual(opts[("馬連", 6)].umaban, [3, 14, 8, 2, 4, 12])

    def test_point_counts_are_combinations(self):
        opts = {(o.kind, o.width): o for o in build_options(self.ORDER, stats=STATS)}
        self.assertEqual(opts[("馬連", 3)].points, 3)
        self.assertEqual(opts[("馬連", 4)].points, 6)
        self.assertEqual(opts[("馬連", 5)].points, 10)
        self.assertEqual(opts[("馬連", 6)].points, 15)

    def test_tier_specific_stats_are_used_when_available(self):
        opts = {(o.kind, o.width): o for o in
                build_options(self.ORDER, favorite_odds=1.5, stats=STATS)}
        self.assertEqual(opts[("馬連", 4)].stats["回収率"], 1.14)   # 1倍台の値

    def test_falls_back_to_overall_when_the_tier_is_missing(self):
        opts = {(o.kind, o.width): o for o in
                build_options(self.ORDER, favorite_odds=3.5, stats=STATS)}
        self.assertEqual(opts[("馬連", 4)].stats["回収率"], 1.35)   # 全体の値

    def test_missing_stats_yield_no_numbers(self):
        opts = {(o.kind, o.width): o for o in build_options(self.ORDER, stats=STATS)}
        self.assertEqual(opts[("ワイド", 3)].stats, {})
        self.assertEqual(opts[("ワイド", 3)].stat_text(), "実測データなし")

    def test_recommended_option_is_flagged_exactly_once(self):
        opts = build_options(self.ORDER, recommended=("馬連", 4), stats=STATS)
        self.assertEqual(sum(1 for o in opts if o.recommended), 1)

    def test_short_field_skips_wider_boxes(self):
        opts = build_options([1, 2, 3], stats=STATS)
        self.assertEqual({o.width for o in opts}, {3})

    def test_wider_box_is_not_always_better(self):
        """広げるほど的中率は上がるが回収率は下がる、という関係を固定する。"""
        opts = {(o.kind, o.width): o for o in build_options(self.ORDER, stats=STATS)}
        four, six = opts[("馬連", 4)].stats, opts[("馬連", 6)].stats
        self.assertGreater(six["的中率"], four["的中率"])
        self.assertLess(six["回収率"], four["回収率"])

    def test_combos_are_all_pairs(self):
        o = BoxOption(kind="馬連", width=4, umaban=[1, 2, 3, 4], points=6)
        self.assertEqual(len(o.combos), 6)


if __name__ == "__main__":
    unittest.main()
