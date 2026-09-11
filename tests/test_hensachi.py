"""レース内偏差値。点差が大きいのか小さいのかを読めるようにするための表示。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.hensachi import CLEAR, deviations, spread_note


class TestDeviations(unittest.TestCase):
    def test_mean_becomes_fifty(self):
        devs = deviations([40.0, 50.0, 60.0])
        self.assertAlmostEqual(devs[1], 50.0)

    def test_higher_score_gets_higher_deviation(self):
        devs = deviations([40.0, 50.0, 60.0])
        self.assertLess(devs[0], devs[1])
        self.assertLess(devs[1], devs[2])

    def test_no_spread_gives_everyone_fifty(self):
        """全馬同点なら偏差値も全員50。0除算で落ちないこと。"""
        self.assertEqual(deviations([55.0] * 4), [50.0] * 4)

    def test_single_horse_is_fifty(self):
        self.assertEqual(deviations([61.2]), [50.0])

    def test_empty_is_empty(self):
        self.assertEqual(deviations([]), [])

    def test_same_gap_reads_differently_by_spread(self):
        """同じ2.6点差でも、散らばりが違えば偏差値差は変わる。
        これが偏差値を併記する理由そのもの。"""
        tight = deviations([60.0, 57.4, 57.0, 56.8])   # 団子
        loose = deviations([60.0, 57.4, 45.0, 30.0])   # ばらけている
        self.assertGreater(tight[0] - tight[1], loose[0] - loose[1])


class TestSpreadNote(unittest.TestCase):
    def test_clear_top(self):
        self.assertIn("抜けている", spread_note({1: CLEAR + 1, 2: 45.0}))

    def test_bunched_field(self):
        self.assertIn("混戦", spread_note({1: 52.0, 2: 50.0, 3: 48.0}))

    def test_empty_does_not_crash(self):
        self.assertIn("算出不能", spread_note({}))


if __name__ == "__main__":
    unittest.main()
