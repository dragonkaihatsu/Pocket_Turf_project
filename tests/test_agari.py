"""上がり3Fの妥当性判定を固定する。

障害レースの馬柱・結果ページは、この列に3Fではない値（12.8〜15.2秒）を
入れる。3F＝600mなので物理的にあり得ない。しかも基礎能力は**レース内で
最小〜最大に正規化**するので、1頭混ざるとそれが「最速」の基準になり、
同じレースで上がり3Fに落ちている他の馬まで不当に低くなる。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.models import AGARI_3F_MAX, AGARI_3F_MIN, Horse, parse_agari_3f
from keiba.scoring import score_kiso_nouryoku


def horse(umaban, agari, name=None):
    return Horse.from_row({
        "馬番": str(umaban), "枠番": "1", "馬名": name or f"馬{umaban}",
        "性齢": "牡4", "騎手": "テスト", "前走着順": "5", "前走レース名": "X",
        "上がり3F": agari, "調教評価": "", "脚質": "先行",
    })


class TestParse(unittest.TestCase):
    def test_jump_race_values_are_rejected(self):
        """障害由来の13〜15秒台は欠損として扱う。"""
        for v in ("12.8", "13.4", "13.9", "14.5", "15.2"):
            self.assertIsNone(parse_agari_3f(v), v)

    def test_zero_means_no_previous_run_not_infinite_speed(self):
        """0.0 は「前走が無い」の意味（新馬・転入初戦）。最速ではない。"""
        self.assertIsNone(parse_agari_3f("0.0"))

    def test_plausible_values_pass(self):
        for v in ("30.0", "32.6", "34.3", "38.6", "43.4", "48.0"):
            self.assertEqual(parse_agari_3f(v), float(v))

    def test_garbage_on_the_slow_side_is_rejected(self):
        for v in ("48.1", "55.0", "75.7", "94.3"):
            self.assertIsNone(parse_agari_3f(v), v)

    def test_missing_and_non_numeric(self):
        for v in ("", None, "—", "あ"):
            self.assertIsNone(parse_agari_3f(v))

    def test_the_observed_gap_justifies_the_lower_bound(self):
        """収集データは 15.2秒と30.0秒のあいだが完全に空だった。

        閾値をこの隙間の中に置いているので、平地の実測値を1件も
        切り落とさない。
        """
        self.assertGreater(AGARI_3F_MIN, 15.2)
        self.assertLessEqual(AGARI_3F_MIN, 30.0)
        self.assertGreaterEqual(AGARI_3F_MAX, 48.0)


class TestHorseDropsTheBadValue(unittest.TestCase):
    def test_from_row_stores_none(self):
        self.assertIsNone(horse(1, "13.4").agari_3f)
        self.assertEqual(horse(2, "34.3").agari_3f, 34.3)


class TestRangeIsNotPoisoned(unittest.TestCase):
    """1頭の壊れた値が、同じレースの他馬の評価を壊さない。"""

    def test_one_jump_horse_does_not_become_the_fastest(self):
        field = [horse(1, "13.4", "障害から"), horse(2, "34.3", "速い"),
                 horse(3, "41.0", "遅い"), horse(4, "43.4", "もっと遅い")]
        by = {h.name: score_kiso_nouryoku(h, field) for h in field}
        # 34.3 がこのレースの最速として扱われ、満点になる
        self.assertIn("最速34.3", by["速い"].note)
        self.assertAlmostEqual(by["速い"].points, 25.0, places=1)
        # 壊れた値の馬はデータなし＝中立値（最速でも最遅でもない）
        self.assertIn("データなし", by["障害から"].note)
        self.assertLess(by["障害から"].points, by["速い"].points)
        self.assertGreater(by["障害から"].points, by["もっと遅い"].points)

    def test_without_the_gate_the_fast_horse_would_be_underrated(self):
        """ゲートが無い状態を再現して、被害の向きを記録しておく。"""
        field = [horse(2, "34.3", "速い"), horse(3, "41.0", "遅い"),
                 horse(4, "43.4", "もっと遅い")]
        clean = score_kiso_nouryoku(field[0], field).points
        poisoned = [horse(1, "13.4", "障害から")] + field
        poisoned[0].agari_3f = 13.4          # ゲートを迂回して毒を入れる
        hurt = score_kiso_nouryoku(field[0], poisoned).points
        self.assertGreater(clean, hurt)      # 速い馬が不当に下がる


if __name__ == "__main__":
    unittest.main()
