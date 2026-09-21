"""前走不利補正（代理B: 脚質×4角位置）のテスト。

実測（中央9-12R・前走ペア1,341組・2024込み最終測定）で確認できたのは
**勝率**の差あり・期間再現（+1.4〜1.8pt）だけで、複勝率では差が消える
（CLAUDE.md「収集完了後の最終測定」）。測れた条件（脚質=逃げ/先行 かつ
4角6番手以下）にしか点を付けないこと、データが欠けたときは「該当なし」
ではなく「判定不能」として0点にとどめることを固定する。
"""
import unittest

from keiba.scoring import correction_zenso_furi, zenso_furi_b
from keiba.models import Horse


def horse(zenso_furi_manual: bool = False) -> Horse:
    h = Horse.from_row({
        "馬番": "1", "枠番": "1", "馬名": "テスト馬", "性齢": "牡4",
        "斤量": "56", "騎手": "テスト騎手",
        "前走着順": "12", "前走レース名": "テスト特別",
        "上がり3F": "35.0", "調教評価": "", "脚質": "差し",
    })
    h.zenso_furi = zenso_furi_manual
    return h


def records(kyaku: str, pos4: str, name: str = "テスト馬") -> dict:
    return {name: [{"馬名": name, "日付": "2026-08-01", "場": "中山",
                    "R": "10", "着順": "12", "騎手": "テスト騎手",
                    "距離": "1800", "馬場種別": "ダート",
                    "脚質": kyaku, "通過": pos4}]}


class TestZensoFuriB(unittest.TestCase):
    def test_senko_and_back_of_the_field_hits(self):
        hit, note = zenso_furi_b(records("先行", "8"), horse(), "2026-09-12")
        self.assertTrue(hit)
        self.assertIn("先行", note)
        self.assertIn("4角8番手", note)

    def test_nige_and_back_of_the_field_hits(self):
        hit, _ = zenso_furi_b(records("逃げ", "6"), horse(), "2026-09-12")
        self.assertTrue(hit)

    def test_senko_but_stayed_forward_does_not_hit(self):
        """脚質が逃げ/先行でも4角5番手以内なら不利の痕跡ではない。"""
        hit, _ = zenso_furi_b(records("先行", "5"), horse(), "2026-09-12")
        self.assertFalse(hit)

    def test_sashi_does_not_hit_regardless_of_position(self):
        """差し/追込は『前に行くはずが後ろにいた』の前提を満たさない。"""
        hit, _ = zenso_furi_b(records("差し", "10"), horse(), "2026-09-12")
        self.assertFalse(hit)

    def test_missing_kyaku_is_undetermined(self):
        hit, note = zenso_furi_b(records("", "8"), horse(), "2026-09-12")
        self.assertIsNone(hit)
        self.assertIn("判定不能", note)

    def test_missing_pos4_is_undetermined(self):
        hit, note = zenso_furi_b(records("先行", ""), horse(), "2026-09-12")
        self.assertIsNone(hit)
        self.assertIn("判定不能", note)

    def test_no_records_is_undetermined(self):
        hit, note = zenso_furi_b(None, horse(), "2026-09-12")
        self.assertIsNone(hit)
        self.assertIn("判定不能", note)

    def test_no_previous_race_is_undetermined(self):
        hit, note = zenso_furi_b({}, horse(), "2026-09-12")
        self.assertIsNone(hit)
        self.assertIn("判定不能", note)

    def test_information_leakage_guard(self):
        """as_ofより後の走りは見ない（前走が今走の後に来ないこと）。"""
        recs = records("先行", "8")
        hit, note = zenso_furi_b(recs, horse(), "2026-07-01")  # 前走(8/1)より前
        self.assertIsNone(hit)
        self.assertIn("判定不能", note)


class TestCorrectionZensoFuri(unittest.TestCase):
    def test_manual_flag_takes_priority(self):
        it = correction_zenso_furi(horse(zenso_furi_manual=True),
                                   records("差し", "1"), "2026-09-12")
        self.assertEqual(it.points, 2.0)
        self.assertIn("展開・コース適性", it.note)

    def test_computed_hit_gets_points(self):
        it = correction_zenso_furi(horse(), records("先行", "7"), "2026-09-12")
        self.assertEqual(it.points, 2.0)
        self.assertIn("代理B", it.note)

    def test_computed_miss_gets_nothing(self):
        it = correction_zenso_furi(horse(), records("差し", "7"), "2026-09-12")
        self.assertEqual(it.points, 0.0)

    def test_undetermined_gets_nothing(self):
        it = correction_zenso_furi(horse(), None, "2026-09-12")
        self.assertEqual(it.points, 0.0)
        self.assertIn("判定不能", it.note)


if __name__ == "__main__":
    unittest.main()
