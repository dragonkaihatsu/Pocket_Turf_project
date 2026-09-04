"""地方版・中央版の取り違えを防ぐ仕組みのテスト。

中央のレースを大井の対応表で採点しても、エラーは出ない。もっともらしい
間違った予想が出るだけで、これがいちばん危ない失敗の仕方なので、
プロファイルの解決を固定しておく。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import profile


class TestVenueResolution(unittest.TestCase):
    def test_local_venues_map_to_nar(self):
        for v in ("大井", "船橋", "川崎", "浦和", "門別", "高知"):
            self.assertEqual(profile.profile_for_venue(v), profile.NAR, v)

    def test_central_venues_map_to_jra(self):
        for v in ("東京", "中山", "阪神", "京都", "札幌", "函館", "新潟", "中京", "小倉", "福島"):
            self.assertEqual(profile.profile_for_venue(v), profile.JRA, v)

    def test_group_names_are_accepted(self):
        self.assertEqual(profile.profile_for_venue("中央"), profile.JRA)
        self.assertEqual(profile.profile_for_venue("地方"), profile.NAR)

    def test_unknown_venue_falls_back_to_the_default(self):
        self.assertEqual(profile.profile_for_venue("架空競馬場"), profile.DEFAULT_PROFILE)
        self.assertEqual(profile.profile_for_venue(None), profile.DEFAULT_PROFILE)

    def test_sapporo_is_central_not_local(self):
        """札幌・函館は中央。地方と混同しやすいので明示的に固定する。"""
        self.assertEqual(profile.profile_for_venue("札幌"), profile.JRA)
        self.assertEqual(profile.profile_for_venue("函館"), profile.JRA)


class TestProfileFiles(unittest.TestCase):
    def test_missing_file_yields_empty_not_an_error(self):
        p = profile.Profile("存在しないプロファイル")
        self.assertEqual(p.load_json("ratings.json"), {})
        self.assertFalse(p.exists("ratings.json"))

    def test_thresholds_fall_back_to_defaults(self):
        p = profile.Profile("存在しないプロファイル")
        self.assertEqual(p.thresholds["鉄板_上限オッズ"],
                         profile.DEFAULT_THRESHOLDS["鉄板_上限オッズ"])

    def test_thresholds_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as d:
            orig = profile.PROFILES_DIR
            try:
                profile.PROFILES_DIR = Path(d)
                (Path(d) / "test").mkdir()
                (Path(d) / "test" / "thresholds.json").write_text(
                    json.dumps({"鉄板_上限オッズ": 1.5}), encoding="utf-8")
                t = profile.Profile("test").thresholds
                self.assertEqual(t["鉄板_上限オッズ"], 1.5)
                # 上書きしていない項目は既定のまま
                self.assertEqual(t["波乱_下限オッズ"],
                                 profile.DEFAULT_THRESHOLDS["波乱_下限オッズ"])
            finally:
                profile.PROFILES_DIR = orig


class TestActiveProfileSwitching(unittest.TestCase):
    def setUp(self):
        self._orig = profile.active().name

    def tearDown(self):
        profile.use(self._orig)

    def test_switching_changes_where_ratings_are_read_from(self):
        import keiba.scoring as sc
        profile.use(profile.NAR)
        nar_path = sc.load_ratings.__globals__["profile"].active().path("ratings.json")
        profile.use(profile.JRA)
        jra_path = sc.load_ratings.__globals__["profile"].active().path("ratings.json")
        self.assertNotEqual(nar_path, jra_path)
        self.assertIn("nar", str(nar_path))
        self.assertIn("jra", str(jra_path))

    def test_the_two_profiles_hold_different_running_style_rates(self):
        """実データがある場合、地方と中央で脚質の実測値が違うことを確認する。"""
        import keiba.scoring as sc
        rates = {}
        for name in (profile.NAR, profile.JRA):
            profile.use(name)
            table = sc.load_ratings().get("脚質", {})
            if "先行" in table:
                rates[name] = table["先行"]["勝率"]
        if len(rates) == 2:
            self.assertNotEqual(rates[profile.NAR], rates[profile.JRA])

    def test_use_for_venue_switches_by_venue_name(self):
        profile.use_for_venue("東京")
        self.assertEqual(profile.active().name, profile.JRA)
        profile.use_for_venue("大井")
        self.assertEqual(profile.active().name, profile.NAR)


if __name__ == "__main__":
    unittest.main()
