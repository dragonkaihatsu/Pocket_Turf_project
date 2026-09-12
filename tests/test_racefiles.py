"""対象レース帯・期間の絞り込み（`keiba/racefiles.py`）。

ここが静かに壊れると「絞ったつもりで絞れていない」集計になり、
エラーは出ないまま違う数字が出る（CLAUDE.md）。特に1-8Rの収集が
月単位で進むあいだは、期間の偏りが集計にそのまま入る。
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from keiba.racefiles import (complete_months, month_coverage, parse_months,
                             parse_races, race_month, race_number, race_venue,
                             result_files)


class TestParseRaces(unittest.TestCase):
    def test_range_and_list(self):
        self.assertEqual(parse_races("9-12"), {9, 10, 11, 12})
        self.assertEqual(parse_races("1,3,5"), {1, 3, 5})
        self.assertEqual(parse_races("1-12"), set(range(1, 13)))

    def test_empty_means_no_filter(self):
        self.assertIsNone(parse_races(""))
        self.assertIsNone(parse_races(None))


class TestParseMonths(unittest.TestCase):
    def test_range_crosses_the_year(self):
        self.assertEqual(parse_months("2025-11..2026-02"),
                         {"2025-11", "2025-12", "2026-01", "2026-02"})

    def test_single_and_list(self):
        self.assertEqual(parse_months("2025-01"), {"2025-01"})
        self.assertEqual(parse_months("2025-01,2026-08"),
                         {"2025-01", "2026-08"})

    def test_separator_is_not_a_hyphen(self):
        """区切りに `-` を使うと日付のハイフンとぶつかる。"""
        self.assertEqual(parse_months("2025-01..2025-01"), {"2025-01"})

    def test_empty_means_no_filter(self):
        self.assertIsNone(parse_months(""))
        self.assertIsNone(parse_months(None))


class TestNameParsing(unittest.TestCase):
    NAME = "2025-02-15_小倉01R_3歳未勝利_結果.csv"

    def test_number_month_venue(self):
        self.assertEqual(race_number(self.NAME), 1)
        self.assertEqual(race_month(self.NAME), "2025-02")
        self.assertEqual(race_venue(self.NAME), "小倉")

    def test_venue_is_not_the_race_number(self):
        """場名のグループとレース番号のグループを取り違えないこと。

        `complete_months` を書いたとき、レース番号用の正規表現で場名を
        引いてしまい、全ての月が「未完了」と出た（グループ1は番号）。
        """
        self.assertEqual(race_venue("2026-09-12_中山11R_ラジオ日本賞_結果.csv"),
                         "中山")
        self.assertEqual(race_number("2026-09-12_中山11R_ラジオ日本賞_結果.csv"),
                         11)

    def test_unreadable_returns_none(self):
        self.assertIsNone(race_number("メモ.csv"))
        self.assertIsNone(race_month("メモ.csv"))


class TestResultFiles(unittest.TestCase):
    """実ファイルを置いて絞り込みを確認する。"""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.d = Path(self.tmp.name)
        for mo, day in (("2025-01", "05"), ("2025-02", "15")):
            for venue in ("中山", "小倉"):
                for r in range(1, 13):
                    (self.d / f"{mo}-{day}_{venue}{r:02d}R_レース_結果.csv"
                     ).write_text("", encoding="utf-8")
        # レース番号が読めないファイル。**通さない**
        (self.d / "メモ_結果.csv").write_text("", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_band_filter(self):
        self.assertEqual(len(result_files(self.d, "9-12")), 16)
        self.assertEqual(len(result_files(self.d, "1-12")), 48)

    def test_unreadable_number_is_dropped(self):
        names = [p.name for p in result_files(self.d, None)]
        self.assertNotIn("メモ_結果.csv", names)

    def test_month_filter(self):
        self.assertEqual(len(result_files(self.d, "9-12", "2025-01")), 8)
        self.assertEqual(len(result_files(self.d, "9-12",
                                          "2025-01..2025-02")), 16)
        self.assertEqual(len(result_files(self.d, "9-12", "2026-01")), 0)

    def test_coverage_and_complete_months(self):
        cov = month_coverage(self.d, "1-8")
        self.assertEqual(cov["2025-01"], (16, 16))   # 2場×8R
        self.assertEqual(complete_months(self.d, "1-8"),
                         ["2025-01", "2025-02"])

    def test_partial_month_is_not_complete(self):
        """収集途中の月は「そろった月」に入らない。"""
        for r in range(1, 9):
            (self.d / f"2025-03-01_中山{r:02d}R_レース_結果.csv"
             ).write_text("", encoding="utf-8")
        for r in range(9, 13):        # 9-12Rは1場ぶんしか無い
            (self.d / f"2025-03-01_中山{r:02d}R_レース_結果.csv"
             ).write_text("", encoding="utf-8")
        (self.d / "2025-03-01_小倉09R_レース_結果.csv").write_text(
            "", encoding="utf-8")
        # 小倉は9Rだけなので 1-8R のカバー率は 8/16 = 50%
        got, exp = month_coverage(self.d, "1-8")["2025-03"]
        self.assertEqual((got, exp), (8, 16))
        self.assertNotIn("2025-03", complete_months(self.d, "1-8"))


if __name__ == "__main__":
    unittest.main()
