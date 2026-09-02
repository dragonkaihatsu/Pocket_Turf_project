import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.collect import build_race_id, parse_result, save_race

ROOT = Path(__file__).resolve().parent.parent
CACHED = ROOT / "data" / "raw" / "202644090211.html"


class TestRaceId(unittest.TestCase):
    def test_build_race_id(self):
        # 2026年9月2日 大井(場コード44) 11R
        self.assertEqual(build_race_id("2026-09-02", "大井", 11), "202644090211")
        self.assertEqual(build_race_id("2026-09-02", "大井", 1), "202644090201")

    def test_unknown_venue_raises(self):
        with self.assertRaises(ValueError):
            build_race_id("2026-09-02", "東京", 11)


@unittest.skipUnless(CACHED.exists(), "取得済みHTMLのキャッシュが必要")
class TestParseResult(unittest.TestCase):
    """実際に取得した大井11Rアフター5スター賞のHTMLでパースを検証する。"""

    @classmethod
    def setUpClass(cls):
        cls.data = parse_result(CACHED.read_text(encoding="utf-8"), "202644090211")

    def test_race_info(self):
        i = self.data.info
        self.assertEqual(i.name, "アフター5スター賞競走")
        self.assertEqual(i.date, "2026-09-02")
        self.assertEqual(i.venue, "大井")
        self.assertEqual(i.race_no, 11)
        self.assertEqual(i.post_time, "20:15")
        self.assertEqual(i.kyori, 1200)
        self.assertEqual(i.baba, "良")
        self.assertEqual(i.head_count, 16)

    def test_finishing_order(self):
        self.assertEqual(len(self.data.horses), 16)
        top3 = [(h["着順"], h["馬番"], h["馬名"]) for h in self.data.horses[:3]]
        self.assertEqual(top3, [("1", "3", "ティントレット"),
                                 ("2", "13", "ナスティウェザー"),
                                 ("3", "8", "マスターオブライフ")])

    def test_horse_detail_columns(self):
        winner = self.data.horses[0]
        self.assertEqual(winner["騎手"], "矢野貴之")
        self.assertEqual(winner["人気"], "1")
        self.assertEqual(winner["単勝オッズ"], "1.9")
        self.assertEqual(winner["上がり3F"], "36.3")
        self.assertEqual(winner["馬体重"], "494(-10)")  # 空白が詰めてあること

    def test_payouts(self):
        pay = {(p["券種"], p["組み合わせ"]): p["配当"] for p in self.data.payouts}
        self.assertEqual(pay[("単勝", "3")], "190")
        self.assertEqual(pay[("馬連", "3-13")], "4710")
        self.assertEqual(pay[("ワイド", "8-13")], "1560")   # 複数組のワイドが取れること
        self.assertEqual(pay[("3連複", "3-8-13")], "3420")
        self.assertEqual(len(self.data.payouts), 12)

    def test_corner_positions(self):
        corners = {c["コーナー"]: c["通過順"] for c in self.data.corners}
        self.assertIn("4コーナー", corners)
        # 括弧は横並びを表す。空白が入っていないこと
        self.assertTrue(corners["4コーナー"].startswith("2,6,5,3,12,(8,4)"))
        self.assertNotIn(" ", corners["4コーナー"])

    def test_saved_csv_is_readable_by_feedback(self):
        import tempfile
        from keiba.feedback import RaceResult, load_payouts
        with tempfile.TemporaryDirectory() as d:
            paths = save_race(self.data, Path(d))
            result = RaceResult.from_csv(paths["結果"])
            payouts = load_payouts(paths["配当"])
        self.assertEqual(result.umaban_to_chakujun[3], 1)
        self.assertEqual(result.umaban_to_chakujun[13], 2)
        umaren = next(p for p in payouts if p.kind == "馬連")
        self.assertEqual(umaren.combo, frozenset({3, 13}))
        self.assertEqual(umaren.amount, 4710)


if __name__ == "__main__":
    unittest.main()
