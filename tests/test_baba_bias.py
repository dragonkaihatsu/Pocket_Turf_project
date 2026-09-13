"""当日の脚質傾向の測り方（`scripts/baba_bias.py`）。

前半→後半の予測力を測る前に、**距離の構造差を除く**のが要点。
1-8Rは短距離・下級条件が多く9-12Rは長距離が多いので、生の平均を比べると
「時間帯の差」を「馬場の差」と読み違える。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from baba_bias import dist_band


class TestDistBand(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(dist_band(1200), "~1400")
        self.assertEqual(dist_band(1400), "~1400")
        self.assertEqual(dist_band(1401), "1401-1800")
        self.assertEqual(dist_band(1800), "1401-1800")
        self.assertEqual(dist_band(1801), "1801-2200")
        self.assertEqual(dist_band(2200), "1801-2200")
        self.assertEqual(dist_band(2201), "2201~")

    def test_todays_races_land_in_different_bands(self):
        """今日の中山9R(芝1800)と11R(芝2200)は別の帯になる。

        同じ日の同じ芝でも距離帯が違えば前残りのしやすさが違うので、
        基準（全期間平均）も別に取る必要がある。
        """
        self.assertNotEqual(dist_band(1800), dist_band(2200))


if __name__ == "__main__":
    unittest.main()
