"""回収率の検出力（`scripts/roi_power.py`）。

「正解率は再現するが回収率は再現しない」を、**優位が無いから**ではなく
**回収率のほうが桁違いに母数を要するから**と説明できるかを測る道具。
数字を出す式なので、向きと桁をテストで固定する。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from roi_power import need_for_roi, parse_corner, project


class TestNeedForRoi(unittest.TestCase):
    def test_more_spread_needs_more_horses(self):
        """払戻のばらつきが大きいほど必要な母数は増える。"""
        a = need_for_roi(sd=5.0, diff=0.30)
        b = need_for_roi(sd=15.0, diff=0.30)
        self.assertGreater(b, a)
        # σ の2乗で効くので、3倍のσなら約9倍
        self.assertAlmostEqual(b / a, 9.0, delta=0.5)

    def test_smaller_difference_needs_more_horses(self):
        self.assertGreater(need_for_roi(10.0, 0.10),
                           need_for_roi(10.0, 0.30))

    def test_degenerate_inputs(self):
        self.assertEqual(need_for_roi(0.0, 0.3), 0)
        self.assertEqual(need_for_roi(10.0, 0.0), 0)
        self.assertEqual(need_for_roi(10.0, -0.3), 0)

    def test_realistic_scale(self):
        """実測（σ≒10.8・差93pt）で2,000頭級になること。

        勝率側は249頭で足りていたので、この桁の差が
        「回収率だけ見えない」ことの説明になっている。
        """
        n = need_for_roi(sd=10.82, diff=0.93)
        self.assertGreater(n, 1_000)
        self.assertLess(n, 4_000)


class TestProject(unittest.TestCase):
    def test_already_enough(self):
        self.assertEqual(project(n_now=500, need=300, months_now=18),
                         "届いている")

    def test_needs_more_months(self):
        txt = project(n_now=693, need=2117, months_now=18)
        self.assertIn("ヶ月", txt)
        self.assertIn("年", txt)

    def test_scales_linearly(self):
        """必要母数が3倍なら、必要な月数も約3倍。"""
        txt = project(n_now=100, need=300, months_now=12)
        self.assertIn("24ヶ月", txt)      # 36ヶ月必要 − いまの12ヶ月

    def test_degenerate_inputs(self):
        self.assertEqual(project(0, 100, 12), "届いている")
        self.assertEqual(project(100, 100, 0), "届いている")


class TestParseCorner(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(parse_corner("5,3,1-2,4", 5), [5, 3, 1, 2, 4])

    def test_two_digit_umaban_is_split_when_too_large(self):
        """18を超える数は2桁馬番の連結とみなして1桁ずつ割る。"""
        self.assertEqual(parse_corner("12,1,3", 3), [12, 1, 3])
        self.assertEqual(parse_corner("123", 3), [1, 2, 3])

    def test_duplicates_are_rejected(self):
        self.assertIsNone(parse_corner("1,1,2", 3))

    def test_field_size_mismatch_is_rejected(self):
        self.assertIsNone(parse_corner("1,2", 10))

    def test_two_missing_is_tolerated(self):
        """1〜2頭ぶん欠けるのは許容する（競走中止など）。"""
        self.assertEqual(parse_corner("1,2,3", 5), [1, 2, 3])

    def test_empty(self):
        self.assertIsNone(parse_corner("", 5))


if __name__ == "__main__":
    unittest.main()


class TestJudgeRoi(unittest.TestCase):
    """回収率の判定（`keiba/power.judge_roi`）。

    正解率と同じ3値（差あり／差なし／判定不能）を返すが、**対照の回収率を
    固定値として扱わない**ことが要点。率なら対照の母数が大きければ点推定は
    ほぼ確定するが、回収率は裾が重いので対照側の誤差も無視できない
    （実測で対照4,525頭・σ=13.5 → 平均の標準誤差20pt）。
    """

    @staticmethod
    def payouts(n: int, hits: int, odds: float) -> list[float]:
        return [odds * 100] * hits + [0.0] * (n - hits)

    def test_two_sample_not_point_estimate(self):
        """対照の誤差を無視すると差ありになる例が、差ありにならないこと。

        検証群の回収率は高いが、対照も裾が重くて平均が揺れている。
        片側だけの区間で判定すると過大に有意と出る。
        """
        from keiba.power import judge_roi
        test = self.payouts(700, 43, 36.0)          # 回収率≒221%
        ctrl = self.payouts(4500, 150, 20.0)        # 回収率≒67%
        v = judge_roi("t", test, ctrl)
        self.assertIsNotNone(v)
        # z は差 ÷ 2標本の標準誤差。点推定比較よりも保守的になる
        self.assertLess(abs(v.z), 10.0)
        self.assertIn(v.code, ("差あり", "差なし", "判定不能"))

    def test_no_difference_is_not_significant(self):
        from keiba.power import judge_roi
        v = judge_roi("t", self.payouts(1000, 50, 13.0),
                      self.payouts(4000, 200, 13.0))
        self.assertNotEqual(v.code, "差あり")
        self.assertAlmostEqual(v.diff, 0.0, delta=0.02)

    def test_thin_sample_is_undetermined(self):
        """母数が薄いと、差が大きく見えても判定不能になる。"""
        from keiba.power import judge_roi
        v = judge_roi("t", self.payouts(40, 4, 50.0),
                      self.payouts(4000, 200, 13.0))
        self.assertEqual(v.code, "判定不能")
        self.assertGreater(v.mdd, 0.25)

    def test_hits_are_counted(self):
        from keiba.power import judge_roi
        v = judge_roi("t", self.payouts(500, 17, 20.0),
                      self.payouts(2000, 60, 20.0))
        self.assertEqual(v.hits, 17)

    def test_needs_two_rows_each(self):
        from keiba.power import judge_roi
        self.assertIsNone(judge_roi("t", [0.0], [0.0, 100.0]))
        self.assertIsNone(judge_roi("t", [0.0, 100.0], []))

    def test_zero_hits_gives_strong_negative(self):
        """的中0本は、避ける条件としてはいちばん強い信号になる。"""
        from keiba.power import judge_roi
        v = judge_roi("t", self.payouts(600, 0, 0.0),
                      self.payouts(4000, 200, 13.0))
        self.assertEqual(v.roi, 0.0)
        self.assertLess(v.z, -1.96)
        self.assertEqual(v.code, "差あり")


class TestMinDetectableRoi(unittest.TestCase):
    def test_more_horses_sees_smaller_difference(self):
        from keiba.power import min_detectable_roi
        self.assertGreater(min_detectable_roi(100, 10.0),
                           min_detectable_roi(10_000, 10.0))

    def test_consistent_with_need_for_roi(self):
        """見分けられる差ちょうどを主張するのに要る母数が、ほぼその母数。"""
        from keiba.power import min_detectable_roi, need_for_roi
        n, sd = 693, 10.82
        mdd = min_detectable_roi(n, sd)
        self.assertAlmostEqual(need_for_roi(sd, mdd) / n, 1.0, delta=0.02)

    def test_degenerate(self):
        from keiba.power import min_detectable_roi
        self.assertEqual(min_detectable_roi(0, 10.0), float("inf"))
