"""単勝・複勝1点買い。当てにいかず、損を小さく保って回収率を取るための1点。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.tanpuku import MIN_HITS, MIN_RETURN, MIN_WIN_PROB, best_tanpuku


def _stats(**over):
    base = {"n": 100, "的中率": 0.28, "回収率": 1.08, "区間下": 0.69,
            "区間上": 1.51, "黒字確率": 0.60, "最大連敗": 13, "最大DD": -1820}
    base.update(over)
    return base


ORDER = [3, 14, 8, 2, 4, 12]


class TestBestTanpuku(unittest.TestCase):
    def test_picks_the_highest_return_rank_and_maps_to_umaban(self):
        stats = {"単複": {"2倍台": {
            "単勝1": _stats(回収率=1.02),
            "複勝3": _stats(回収率=1.08),
        }}}
        p = best_tanpuku(ORDER, favorite_odds=2.5, stats=stats)
        self.assertEqual((p.kind, p.rank), ("複勝", 3))
        self.assertEqual(p.umaban, 8)   # スコア3位の馬番
        self.assertTrue(p.recommended)

    def test_below_break_even_is_not_recommended(self):
        stats = {"単複": {"2倍台": {"単勝1": _stats(回収率=0.99)}}}
        p = best_tanpuku(ORDER, favorite_odds=2.5, stats=stats)
        self.assertFalse(p.recommended)
        self.assertIn("損益分岐に届かない", p.reason)

    def test_low_profit_probability_is_not_recommended(self):
        stats = {"単複": {"2倍台": {
            "単勝1": _stats(回収率=1.5, 黒字確率=MIN_WIN_PROB - 0.05)}}}
        p = best_tanpuku(ORDER, favorite_odds=2.5, stats=stats)
        self.assertFalse(p.recommended)
        self.assertIn("当たり外れが大きい", p.reason)

    def test_too_few_actual_hits_is_not_recommended(self):
        """母数が多くても実際の的中が数本なら、それは推定ではなく偶然の記録。"""
        stats = {"単複": {"3倍以上": {
            "単勝3": _stats(n=43, 的中率=0.09, 回収率=2.5, 黒字確率=0.60)}}}
        p = best_tanpuku(ORDER, favorite_odds=3.5, stats=stats)
        self.assertFalse(p.recommended)
        self.assertIn("偶然の記録", p.reason)
        self.assertLess(round(43 * 0.09), MIN_HITS)

    def test_falls_back_to_overall_when_the_tier_is_missing(self):
        stats = {"単複": {"全体": {"複勝1": _stats()}}}
        p = best_tanpuku(ORDER, favorite_odds=3.5, stats=stats)
        self.assertIsNotNone(p)
        self.assertEqual((p.kind, p.rank), ("複勝", 1))

    def test_no_stats_yields_none(self):
        self.assertIsNone(best_tanpuku(ORDER, favorite_odds=2.5, stats={}))

    def test_short_field_yields_none(self):
        stats = {"単複": {"2倍台": {"複勝6": _stats()}}}
        self.assertIsNone(best_tanpuku([1, 2, 3], favorite_odds=2.5, stats=stats))

    def test_break_even_threshold_is_one(self):
        self.assertEqual(MIN_RETURN, 1.0)


if __name__ == "__main__":
    unittest.main()
