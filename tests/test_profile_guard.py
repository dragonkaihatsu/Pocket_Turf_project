"""入力データと出力先プロファイルの食い違いを止めるガードのテスト。

実際に踏んだ事故を固定する: `calibrate.py --out data/profiles/jra/...` を
既定の `--dir data/collected`（地方）で走らせ、**大井244レースの対応表を
中央のプロファイルに書き込んだ**。ヘッダには「大井9-12R 244レース」と
出るがエラーは出ないので、気づかずに通ってしまう。
"""
from __future__ import annotations

import unittest
from pathlib import Path

from keiba import profile


class TestProfileOfPath(unittest.TestCase):
    def test_reads_profile_from_output_path(self):
        self.assertEqual(
            profile.profile_of_path("data/profiles/jra/calibration.json"), "jra")
        self.assertEqual(
            profile.profile_of_path("data/profiles/nar/box_stats.json"), "nar")

    def test_unknown_path_is_none(self):
        self.assertIsNone(profile.profile_of_path("data/calibration.json"))


class TestProfileForDir(unittest.TestCase):
    def dir_with(self, tmp: Path, names: list[str]) -> Path:
        for n in names:
            (tmp / n).write_text("着順\n1\n", encoding="utf-8-sig")
        return tmp

    def test_venues_decide_the_profile(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            d = self.dir_with(Path(td), ["2026-09-13_中山11R_テスト_結果.csv",
                                         "2026-09-13_阪神09R_テスト_結果.csv"])
            self.assertEqual(profile.profile_for_dir(d), "jra")
        with tempfile.TemporaryDirectory() as td:
            d = self.dir_with(Path(td), ["2026-09-13_大井11R_テスト_結果.csv"])
            self.assertEqual(profile.profile_for_dir(d), "nar")

    def test_mixed_directory_is_none(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            d = self.dir_with(Path(td), ["2026-09-13_中山11R_テスト_結果.csv",
                                         "2026-09-13_大井11R_テスト_結果.csv"])
            self.assertIsNone(profile.profile_for_dir(d))


class TestAssertSameProfile(unittest.TestCase):
    def test_the_real_accident_is_stopped(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "2026-09-13_大井11R_テスト_結果.csv").write_text(
                "着順\n1\n", encoding="utf-8-sig")
            with self.assertRaises(SystemExit) as cm:
                profile.assert_same_profile(d, "data/profiles/jra/calibration.json")
            self.assertIn("食い違", str(cm.exception))

    def test_matching_pair_passes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "2026-09-13_中山11R_テスト_結果.csv").write_text(
                "着順\n1\n", encoding="utf-8-sig")
            profile.assert_same_profile(d, "data/profiles/jra/calibration.json")

    def test_undecidable_is_allowed(self):
        """判定できないときは通す。推測で止めると使えなくなる。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            profile.assert_same_profile(td, "data/profiles/jra/calibration.json")
            profile.assert_same_profile(td, "data/out.json")


class TestEveryTableBuilderHasTheGuard(unittest.TestCase):
    """実測表を書き出すスクリプトは全部ガードを通すこと。

    1本でも抜けると、そこから同じ事故が起きる。
    """

    SCRIPTS = ["calibrate", "boxstats", "single", "tanpuku", "build_ratings",
               "build_horse_records", "build_mochidokei"]

    def test_guard_is_wired(self):
        for name in self.SCRIPTS:
            src = Path(f"scripts/{name}.py").read_text(encoding="utf-8")
            self.assertIn("assert_same_profile", src, f"{name}.py にガードが無い")


if __name__ == "__main__":
    unittest.main()


class TestNoScriptReadsRecordsFromAmbientProfile(unittest.TestCase):
    """集計スクリプトが馬別戦績を既定プロファイル任せに読まないこと。

    `_load_horse_records()` を引数なしで呼ぶと `profile.active()`（既定 nar）
    の horse_records.csv を読む。集計スクリプトはプロファイルを切り替えない
    ので、**中央のレースに大井の戦績を当てる**。boxstats / single / tanpuku が
    実際にそうなっており、box_stats.json 等はその状態で作られていた。
    """

    SCRIPTS = ["boxstats", "single", "tanpuku", "calibrate", "accuracy"]

    def test_records_path_is_explicit(self):
        import re
        for name in self.SCRIPTS:
            src = Path(f"scripts/{name}.py").read_text(encoding="utf-8")
            self.assertNotRegex(
                src, r"_load_horse_records\(\s*\)",
                f"{name}.py が引数なしで戦績を読んでいる")
            if "_load_horse_records" in src or "--records" in src:
                self.assertIn("--records", src, f"{name}.py に --records が無い")
