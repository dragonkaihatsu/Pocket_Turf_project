"""ワイド1点買い。当てにいかず、損を小さく保って回収率を取るための1点。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.single import MIN_HITS, MIN_RETURN, MIN_WIN_PROB, best_single


def _stats(**over):
    base = {"n": 100, "的中率": 0.28, "回収率": 1.08, "区間下": 0.69,
            "区間上": 1.51, "黒字確率": 0.60, "最大連敗": 13, "最大DD": -1820}
    base.update(over)
    return base


ORDER = [3, 14, 8, 2, 4, 12]


class TestBestSingle(unittest.TestCase):
    def test_picks_the_highest_return_pair_and_maps_to_umaban(self):
        stats = {"1点買い": {"2倍台": {
            "ワイド1-2": _stats(回収率=1.02),
            "ワイド1-3": _stats(回収率=1.08),
        }}}
        p = best_single(ORDER, favorite_odds=2.5, stats=stats)
        self.assertEqual((p.rank_a, p.rank_b), (1, 3))
        self.assertEqual(p.umaban, (3, 8))   # スコア1位と3位の馬番
        self.assertEqual(p.combo, "3-8")
        self.assertTrue(p.recommended)

    def test_below_break_even_is_not_recommended(self):
        stats = {"1点買い": {"2倍台": {"ワイド1-2": _stats(回収率=0.99)}}}
        p = best_single(ORDER, favorite_odds=2.5, stats=stats)
        self.assertFalse(p.recommended)
        self.assertIn("損益分岐に届かない", p.reason)

    def test_low_profit_probability_is_not_recommended(self):
        """回収率が100%を超えていても、当たり外れが大きすぎる区分は勧めない。"""
        stats = {"1点買い": {"2倍台": {
            "ワイド1-2": _stats(回収率=1.5, 黒字確率=MIN_WIN_PROB - 0.05)}}}
        p = best_single(ORDER, favorite_odds=2.5, stats=stats)
        self.assertFalse(p.recommended)
        self.assertIn("当たり外れが大きい", p.reason)

    def test_too_few_actual_hits_is_not_recommended(self):
        """的中が数本しかない区分の高回収率は、推定ではなく偶然の記録。

        大井3倍以上のワイド3-4位は43レース中5本の的中で回収率296%だった。
        これを推奨すると、当たらない1点を買い続けることになる。
        """
        stats = {"1点買い": {"3倍以上": {
            "ワイド3-4": _stats(n=43, 的中率=0.12, 回収率=2.96, 黒字確率=0.73)}}}
        p = best_single(ORDER, favorite_odds=3.5, stats=stats)
        self.assertFalse(p.recommended)
        self.assertIn("偶然の記録", p.reason)
        self.assertLess(round(43 * 0.12), MIN_HITS)

    def test_falls_back_to_overall_when_the_tier_is_missing(self):
        stats = {"1点買い": {"全体": {"ワイド1-2": _stats()}}}
        p = best_single(ORDER, favorite_odds=3.5, stats=stats)
        self.assertIsNotNone(p)
        self.assertEqual((p.rank_a, p.rank_b), (1, 2))

    def test_no_stats_yields_none(self):
        self.assertIsNone(best_single(ORDER, favorite_odds=2.5, stats={}))

    def test_umaren_is_excluded_by_default(self):
        """馬連1点は当たれば大きいが90連敗級が出る。既定ではワイドのみ見る。"""
        stats = {"1点買い": {"2倍台": {
            "馬連2-3": _stats(回収率=2.10, 最大連敗=90),
            "ワイド1-3": _stats(回収率=1.08),
        }}}
        p = best_single(ORDER, favorite_odds=2.5, stats=stats)
        self.assertEqual(p.kind, "ワイド")

    def test_short_field_yields_none(self):
        stats = {"1点買い": {"2倍台": {"ワイド1-5": _stats()}}}
        self.assertIsNone(best_single([1, 2, 3], favorite_odds=2.5, stats=stats))

    def test_break_even_threshold_is_one(self):
        self.assertEqual(MIN_RETURN, 1.0)
