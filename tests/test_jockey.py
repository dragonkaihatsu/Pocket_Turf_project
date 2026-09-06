import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from jockey import AREAS, band_of, tally


class TestBands(unittest.TestCase):
    def test_distance_bands(self):
        self.assertEqual(band_of(1200), "〜1400")
        self.assertEqual(band_of(1400), "〜1400")
        self.assertEqual(band_of(1600), "1401-1800")
        self.assertEqual(band_of(1800), "1401-1800")
        self.assertEqual(band_of(2000), "1801〜")
        self.assertEqual(band_of(None), "")

    def test_areas_cover_the_ten_jra_courses(self):
        allv = {v for names in AREAS.values() for v in names}
        self.assertEqual(len(allv), 10)
        self.assertIn("東京", AREAS["関東"])
        self.assertIn("阪神", AREAS["関西"])
        self.assertIn("札幌", AREAS["北海道"])


class TestTally(unittest.TestCase):
    """回収率の計算を間違えると、判断を丸ごと誤らせる。"""

    def _rows(self):
        # 3騎乗。1着1回(単勝5.0倍=500円)、3着1回(複勝200円)、着外1回
        return [{"着順": 1, "オッズ": 5.0, "複勝": 180},
                {"着順": 3, "オッズ": 8.0, "複勝": 200},
                {"着順": 7, "オッズ": 20.0, "複勝": None}]

    def test_rates(self):
        t = tally(self._rows())
        self.assertEqual(t["n"], 3)
        self.assertAlmostEqual(t["勝率"], 1 / 3)
        self.assertAlmostEqual(t["複勝率"], 2 / 3)

    def test_win_return_uses_odds_only_for_winners(self):
        # 500円 ÷ (3騎乗 × 100円) = 166.7%
        self.assertAlmostEqual(tally(self._rows())["単回収"], 500 / 300)

    def test_place_return_uses_the_actual_payout(self):
        # (180 + 200) ÷ 300 = 126.7%
        self.assertAlmostEqual(tally(self._rows())["複回収"], 380 / 300)

    def test_empty(self):
        self.assertEqual(tally([]), {"n": 0})
