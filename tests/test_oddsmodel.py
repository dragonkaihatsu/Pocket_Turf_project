import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.oddsmodel import (
    estimate_umaren,
    estimate_wide,
    quinella_prob,
    win_probabilities,
    wide_prob,
)

ODDS = {1: 2.0, 2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0, 6: 50.0}


class TestOddsModel(unittest.TestCase):
    def setUp(self):
        self.p = win_probabilities(ODDS)

    def test_win_probabilities_sum_to_one(self):
        self.assertAlmostEqual(sum(self.p.values()), 1.0)

    def test_favorite_has_the_highest_probability(self):
        self.assertEqual(max(self.p, key=self.p.get), 1)

    def test_quinella_probabilities_sum_to_one(self):
        """1・2着に入る組はちょうど1通りなので、全ペアの確率は1になる。"""
        total = sum(quinella_prob(self.p, a, b)
                    for a in ODDS for b in ODDS if a < b)
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_wide_probabilities_sum_to_three(self):
        """3着以内の2頭組は3通りあるので、全ペアの確率は3になる。"""
        total = sum(wide_prob(self.p, a, b) for a in ODDS for b in ODDS if a < b)
        self.assertAlmostEqual(total, 3.0, places=6)

    def test_longshot_pair_has_longer_odds(self):
        near = estimate_umaren(ODDS, 1, 2)
        far = estimate_umaren(ODDS, 5, 6)
        self.assertLess(near, far)

    def test_wide_is_cheaper_than_umaren_for_the_same_pair(self):
        # 3着以内でよいワイドの方が当たりやすい＝配当は安い
        self.assertLess(estimate_wide(ODDS, 1, 3), estimate_umaren(ODDS, 1, 3))

    def test_missing_odds_are_ignored(self):
        odds = dict(ODDS)
        odds[7] = 0.0
        self.assertNotIn(7, win_probabilities(odds))


class TestAllocation(unittest.TestCase):
    """均等払戻し配分＝人気薄に薄く、人気馬に厚く。"""

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from gosei import allocate, select_for_target
        self.allocate = allocate
        self.select = select_for_target
        self.chosen = [(frozenset({1, 2}), 2.0),
                       (frozenset({1, 3}), 5.0),
                       (frozenset({2, 3}), 10.0)]

    def test_stake_is_larger_for_the_shorter_odds(self):
        st = self.allocate(self.chosen, 5000)
        self.assertGreater(st[frozenset({1, 2})], st[frozenset({1, 3})])
        self.assertGreater(st[frozenset({1, 3})], st[frozenset({2, 3})])

    def test_every_hit_returns_roughly_the_same(self):
        """どれが当たっても払戻がほぼ揃うのが均等払戻し方式の要件。

        ただし賭け金は100円単位なので完全には揃わない。予算5,000円・
        オッズ2/5/10倍だと 3,100円/1,300円/600円 となり、払戻は
        6,200円/6,500円/6,000円で約8%ばらつく。これは丸めによる
        実際の制約であり、隠さずに許容幅として持つ。
        """
        st = self.allocate(self.chosen, 5000)
        payouts = [st[c] * o for c, o in self.chosen]
        self.assertLess((max(payouts) - min(payouts)) / max(payouts), 0.10)

    def test_synthetic_odds_falls_as_tickets_are_added(self):
        cands = [(frozenset({1, 2}), 2.0), (frozenset({1, 3}), 5.0),
                 (frozenset({2, 3}), 10.0), (frozenset({1, 4}), 20.0)]
        wide_set, g_low = self.select(cands, 1.0)
        narrow_set, g_high = self.select(cands, 3.0)
        self.assertGreater(len(wide_set), len(narrow_set))
        self.assertGreater(g_high, g_low)

    def test_selection_keeps_at_least_one_ticket(self):
        # 目標が高すぎても、いちばん来やすい1点は残す
        chosen, _ = self.select(self.chosen, 100.0)
        self.assertEqual(len(chosen), 1)


if __name__ == "__main__":
    unittest.main()
