"""連闘の参考注記のテスト（`scripts/rento.py` の実測に対応）。

測れた区分（差あり＋2024/2025/2026の3年で符号一致）にだけ出す:

    1-3番人気   勝率 −5.4p（複勝率は −1.6p で判定不能）
    6-9番人気   複勝率 −2.5p
    10番人気以下 複勝率 −1.3p
    6-9番人気 × 前走二桁  複勝率 −3.9p

4-5番人気は差なし／判定不能なので**出さない**。測っていない区分に
注記を出すと、CLAUDE.mdが繰り返し戒めている「もっともらしい間違い」になる。
"""
import csv
import unittest
from pathlib import Path

from keiba.models import Horse
from keiba.sanko import rento_note


class TestRentoNote(unittest.TestCase):
    def test_measured_bands_fire(self):
        self.assertIn("勝ち切り", rento_note("連闘", 1, 2))
        self.assertIn("勝ち切り", rento_note("連闘", 3, 1))
        self.assertIn("−2.5p", rento_note("連闘", 8, 3))
        self.assertIn("−1.3p", rento_note("連闘", 12, 3))

    def test_mid_band_is_silent(self):
        """4-5番人気は差なし／判定不能。出してはいけない。"""
        for nk in (4, 5):
            self.assertIsNone(rento_note("連闘", nk, 2), f"{nk}番人気で出ている")

    def test_zenso_niketa_takes_priority_in_6_9(self):
        self.assertIn("前走二桁", rento_note("連闘", 7, 15))
        # 1-3番人気では前走二桁でも人気帯の注記を出す（そこは測っていない）
        self.assertIn("勝ち切り", rento_note("連闘", 2, 15))

    def test_only_rento(self):
        for lab in ("中1週", "中2週", "", None, "連闘 "):
            got = rento_note(lab, 1, 2)
            if lab == "連闘 ":          # 前後の空白は許す
                self.assertIsNotNone(got)
            else:
                self.assertIsNone(got, f"{lab!r} で出ている")

    def test_unknown_popularity_is_silent(self):
        self.assertIsNone(rento_note("連闘", None, 2))


class TestHorseReadsLabel(unittest.TestCase):
    """馬柱の `間隔表記` を Horse が読むこと（読めないと注記が一度も出ない）。"""

    def test_from_row(self):
        h = Horse.from_row({"馬番": "1", "枠番": "1", "馬名": "テスト",
                            "性齢": "牡4", "斤量": "56", "騎手": "テスト騎手",
                            "前走着順": "2", "前走レース名": "テスト特別",
                            "上がり3F": "35.0", "調教評価": "",
                            "間隔表記": "連闘", "人気": "1"})
        self.assertEqual(h.kankaku, "連闘")
        self.assertIsNotNone(rento_note(h.kankaku, h.ninki, h.zenso_chakujun))

    def test_missing_column_is_empty(self):
        h = Horse.from_row({"馬番": "1", "枠番": "1", "馬名": "テスト",
                            "性齢": "牡4", "斤量": "56", "騎手": "テスト騎手",
                            "前走着順": "2", "前走レース名": "", "上がり3F": "",
                            "調教評価": ""})
        self.assertEqual(h.kankaku, "")


class TestRealEntries(unittest.TestCase):
    """収集した馬柱に実際にラベルが入っていること（列名の取り違え防止）。"""

    def test_labels_exist_in_corpus(self):
        d = Path("data/collected_jra")
        files = sorted(d.glob("2026-09-22_中山*_出走馬.csv"))
        if not files:
            self.skipTest("2026-09-22 の出走馬CSVが無い")
        labels = set()
        # **(レース, 馬番) で数える。** `--force` で収集し直すと、結果ページの
        # レース名が馬柱の `<title>` 由来の名前と違うレースだけ出走馬CSVが
        # 2本になる（2026-09-22は9R/10R/11Rがそれ。朝のオッズ版と確定オッズ版）。
        # 行を数えると同じ馬を二重に数えて静かにずれる
        rento = set()
        for f in files:
            race = f.name.split("R_", 1)[0]
            for r in csv.DictReader(open(f, encoding="utf-8-sig")):
                lab = (r.get("間隔表記") or "").strip()
                if lab:
                    labels.add(lab)
                if lab == "連闘":
                    rento.add((race, (r.get("馬番") or "").strip()))
        self.assertTrue(any(l.startswith("中") for l in labels), labels)
        self.assertEqual(len(rento), 4, f"2026-09-22 中山の連闘は4頭: {sorted(rento)}")


if __name__ == "__main__":
    unittest.main()


class TestLayoffColumn(unittest.TestCase):
    """長期休養明け −3点が発火すること（列名の取り違えで0%だった）。

    収集CSVの列名は `前走間隔日数`（`keiba/collect.py` の ENTRY_COLUMNS）。
    `休養日数` という列は存在しないので、そこだけを読んでいると
    `correction_hatsu_course` が延べ2,736頭で一度も発火しない。
    """

    def base(self, **extra) -> dict:
        row = {"馬番": "1", "枠番": "1", "馬名": "テスト", "性齢": "牡6",
               "斤量": "56", "騎手": "テスト騎手", "前走着順": "5",
               "前走レース名": "テスト特別", "上がり3F": "35.0",
               "調教評価": ""}
        row.update(extra)
        return row

    def test_reads_zenso_interval(self):
        h = Horse.from_row(self.base(前走間隔日数="200"))
        self.assertEqual(h.kyusoku_days, 200)

    def test_penalty_fires_over_180_days(self):
        from keiba.scoring import correction_hatsu_course
        it = correction_hatsu_course(Horse.from_row(self.base(前走間隔日数="200")), None)
        self.assertEqual(it.points, -3.0)
        self.assertIn("長期休養明け", it.note)

    def test_no_penalty_at_or_below_180(self):
        from keiba.scoring import correction_hatsu_course
        for d in ("180", "30", "7"):
            it = correction_hatsu_course(
                Horse.from_row(self.base(前走間隔日数=d)), None)
            self.assertEqual(it.points, 0.0, f"{d}日で減点している")

    def test_explicit_column_still_wins(self):
        """`休養日数` を明示で渡せばそちらを使う（手入力CSV向け）。"""
        h = Horse.from_row(self.base(休養日数="300", 前走間隔日数="10"))
        self.assertEqual(h.kyusoku_days, 300)

    def test_collect_writes_the_column(self):
        from keiba.collect import ENTRY_COLUMNS
        self.assertIn("前走間隔日数", ENTRY_COLUMNS)
        self.assertNotIn("休養日数", ENTRY_COLUMNS,
                         "収集側が休養日数を書くなら models 側の優先順を見直す")
