"""参考注記（表示のみ）を固定する。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from keiba.sanko import (
    course_note,
    distance_band,
    jockey_note,
    waku_band,
)


def combo(jockey, grain, cond, n, rate):
    return {"騎手": jockey, "粒度": grain, "条件": cond, "n": n,
            "勝利数": 12, "複勝内数": int(n * rate), "勝率": 0.1,
            "複勝率": rate, "単勝回収率": 100.0, "信頼できる母数": True}


class TestBandsHaveOneDefinition(unittest.TestCase):
    def test_jockey_stats_imports_the_bands(self):
        """境目を2か所に書くと、予想時に引く側と集計する側がずれる。"""
        import jockey_stats as js
        self.assertIs(js.distance_band, distance_band)
        self.assertIs(js.waku_band, waku_band)

    def test_edges(self):
        self.assertEqual(distance_band(1400), "短距離(~1400)")
        self.assertEqual(distance_band(1401), "マイル(1401-1800)")
        self.assertEqual(distance_band(1800), "マイル(1401-1800)")
        self.assertEqual(distance_band(2200), "中距離(1801-2200)")
        self.assertEqual(distance_band(2201), "長距離(2201~)")
        self.assertEqual(waku_band(1), "内枠(1-2)")
        self.assertEqual(waku_band(6), "中枠(3-6)")
        self.assertEqual(waku_band(8), "外枠(7-8)")
        self.assertIsNone(waku_band(None))
        self.assertIsNone(waku_band(9))


class TestCourseNote(unittest.TestCase):
    def test_nakayama_turf_only_when_wet(self):
        self.assertIsNone(course_note("中山", "芝", "良"))
        self.assertIn("内枠", course_note("中山", "芝", "稍重"))
        self.assertIn("内枠", course_note("中山", "芝", "重"))

    def test_nakayama_dirt_is_the_opposite(self):
        """同じ測定で芝とダで符号が逆だった。排水の話を芝ダ一括で
        当てると逆になる。"""
        turf = course_note("中山", "芝", "重")
        dirt = course_note("中山", "ダ", "良")
        self.assertIn("有利", turf)
        self.assertIn("不利", dirt)

    def test_other_venues_get_nothing(self):
        """全10場で測って、両期間で向きが揃ったのは中山の芝だけ。"""
        for v in ("東京", "阪神", "京都", "小倉", "札幌", "函館",
                  "新潟", "中京", "福島"):
            self.assertIsNone(course_note(v, "芝", "重"), v)

    def test_it_says_the_verdict_is_not_settled(self):
        """n=146・要る差9.7pで判定不能。断定しない言い方にしてある。"""
        self.assertIn("判定不能", course_note("中山", "芝", "重"))


class TestJockeyNote(unittest.TestCase):
    BASE = {"テスト騎手": {"n": 1000, "複勝率": 0.20, "勝率": 0.08,
                       "単勝回収率": 80.0}}

    def test_needs_a_baseline(self):
        """水準ではなく、その騎手の中での対比を出す。比べる相手が無ければ
        何も言わない（「複勝率24%」は得意条件ではなく単なる成績）。"""
        stats = [combo("テスト騎手", "芝ダ", "芝", 300, 0.40)]
        self.assertIsNone(
            jockey_note("テスト騎手", stats, "中山", "芝", 1600,
                        "先行", 3, None))

    def test_emits_when_the_gap_exceeds_what_the_sample_can_see(self):
        stats = [combo("テスト騎手", "芝ダ", "芝", 300, 0.40)]
        note = jockey_note("テスト騎手", stats, "中山", "芝", 1600,
                           "先行", 3, self.BASE)
        self.assertIn("得意", note)
        self.assertIn("40%", note)
        self.assertIn("20%", note)

    def test_stays_quiet_when_the_sample_cannot_see_the_gap(self):
        """n=12で3ptの差を「得意」と呼ぶと、母数が薄いときの大きな
        数字を拾う。"""
        stats = [combo("テスト騎手", "芝ダ", "芝", 12, 0.23)]
        self.assertIsNone(
            jockey_note("テスト騎手", stats, "中山", "芝", 1600,
                        "先行", 3, self.BASE))

    def test_says_nigate_when_below(self):
        stats = [combo("テスト騎手", "芝ダ", "芝", 300, 0.05)]
        note = jockey_note("テスト騎手", stats, "中山", "芝", 1600,
                           "先行", 3, self.BASE)
        self.assertIn("苦手", note)

    def test_only_conditions_that_match_today(self):
        """今日はダ1200mなので、芝の条件は引かない。"""
        stats = [combo("テスト騎手", "芝ダ", "芝", 300, 0.40)]
        self.assertIsNone(
            jockey_note("テスト騎手", stats, "中山", "ダ", 1200,
                        "先行", 3, self.BASE))

    def test_ambiguous_abbreviation_is_not_resolved(self):
        """表記ゆれで2人以上に当たるなら出さない。前方一致で辞書順の
        先頭を返して別人を掴んだ不具合があった。"""
        stats = [combo("岩田康", "芝ダ", "芝", 300, 0.40),
                 combo("岩田望", "芝ダ", "芝", 300, 0.40)]
        base = {"岩田康": {"n": 344, "複勝率": 0.2},
                "岩田望": {"n": 473, "複勝率": 0.2}}
        self.assertIsNone(
            jockey_note("岩田", stats, "中山", "芝", 1600, "先行", 3, base))


if __name__ == "__main__":
    unittest.main()
