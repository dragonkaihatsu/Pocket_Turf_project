"""レース水準（走破タイムから測ったレースのレベル）と持ち時計の分解のテスト。

固定するのは3つ。
  1. 水準→クラスの言い換えが実測の中央値と整合すること（勝手な閾値にしない）
  2. **後知恵が入らないこと**（as_of 以降の走りを見ない・窓は365日）
  3. 表示は交差で「差あり＋期間再現」を通った形だけに出ること
     （全馬に出すと判別の役に立たない。相手関係で一度踏んだ失敗）
"""
import json
import tempfile
import unittest
from pathlib import Path

from keiba import mochidokei as mk
from keiba import racelevel as rl


def base_times() -> mk.BaseTimes:
    """中山ダ1200mだけの基準表。平均72.0秒・ばらつき1.0秒。"""
    return mk.BaseTimes(cells={mk.cell_key("中山", "ダ", "1200"):
                               {"n": 500, "mean": 72.0, "sd": 1.0}})


def run(d: str, sec: str, ba: str = "中山", r: str = "10") -> dict:
    return {"日付": d, "場": ba, "R": r, "馬場種別": "ダ", "距離": "1200",
            "馬場": "良", "タイム": sec, "着順": "3"}


class TestClassLabel(unittest.TestCase):
    def test_measured_medians_map_to_their_own_class(self):
        """実測の中央値を入れたら、そのクラスの名前が返る。"""
        for cls, label in (("新馬", "新馬級"), ("未勝利", "未勝利級"),
                           ("1勝", "1勝クラス級"), ("2勝", "2〜3勝クラス級")):
            self.assertEqual(rl.class_label(rl.CLASS_MEDIANS[cls]), label,
                             f"{cls} の中央値が {label} にならない")

    def test_open_median_is_called_open(self):
        self.assertEqual(rl.class_label(rl.OPEN_MEDIAN), "オープン級")

    def test_bounds_are_sorted_and_monotonic(self):
        vals = [b for b, _ in rl.CLASS_BOUNDS]
        self.assertEqual(vals, sorted(vals))
        meds = [rl.CLASS_MEDIANS[c] for c in ("新馬", "未勝利", "1勝", "2勝")]
        self.assertEqual(meds, sorted(meds), "クラスの中央値が単調でない")

    def test_grades_are_not_told_apart(self):
        """オープン以上の格は時計で測れないので、言い分けない。"""
        labels = {rl.class_label(v) for v in (0.83, 0.87, 1.00, 1.50)}
        self.assertEqual(labels, {"オープン級"})


class TestNameClass(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual(rl.name_class("3歳未勝利"), "未勝利")
        self.assertEqual(rl.name_class("2歳新馬"), "新馬")
        self.assertEqual(rl.name_class("4歳以上1勝クラス"), "1勝")
        self.assertEqual(rl.name_class("4歳以上2勝クラス"), "2勝")
        self.assertEqual(rl.name_class("チャレンジC"), "固有名")

    def test_shogai_is_excluded(self):
        """障害は時計の性質が違うので水準に混ぜない。"""
        self.assertEqual(rl.name_class("4歳以上障害未勝利"), "障害")


class TestSplit(unittest.TestCase):
    """持ち時計 = 走ってきた水準 ＋ レース内相対（恒等式）。"""

    def setUp(self):
        self.base = base_times()
        # 中山10R の水準が +0.5 だったことにする
        self.table = {rl.table_key("2026-06-01", "中山", "10"): 0.5,
                      rl.table_key("2026-07-01", "中山", "10"): 0.5,
                      rl.table_key("2026-08-01", "中山", "10"): 0.5}

    def rows(self):
        # 71.0秒 → 指数 +1.0。水準0.5なので相対は +0.5
        return [run("2026-06-01", "71.0"), run("2026-07-01", "71.0"),
                run("2026-08-01", "71.0")]

    def test_decomposition_is_exact(self):
        s = rl.split_of(self.rows(), self.table, "2026-09-01", self.base)
        self.assertIsNotNone(s)
        self.assertAlmostEqual(s.level, 0.5)
        self.assertAlmostEqual(s.margin, 0.5)
        self.assertAlmostEqual(s.total, 1.0, places=6)
        self.assertEqual(s.n, 3)

    def test_fewer_than_min_runs_is_none(self):
        """3走未満は作らない（0で埋めると遅い馬と区別できない）。"""
        s = rl.split_of(self.rows()[:2], self.table, "2026-09-01", self.base)
        self.assertIsNone(s)

    def test_no_information_leakage(self):
        """as_of 当日・それ以降の走りは使わない。"""
        s = rl.split_of(self.rows(), self.table, "2026-06-01", self.base)
        self.assertIsNone(s, "as_of より後の走りを見ている")

    def test_window_is_365_days(self):
        old = [run("2024-01-01", "71.0"), run("2024-02-01", "71.0"),
               run("2024-03-01", "71.0")]
        tbl = {rl.table_key(r["日付"], "中山", "10"): 0.5 for r in old}
        self.assertIsNone(rl.split_of(old, tbl, "2026-09-01", self.base))

    def test_runs_without_a_level_are_skipped(self):
        """水準が表に無い走りは数えない（推定値を作らない）。"""
        s = rl.split_of(self.rows(), {}, "2026-09-01", self.base)
        self.assertIsNone(s)

    def test_no_base_times_is_none(self):
        self.assertIsNone(rl.split_of(self.rows(), self.table, "2026-09-01", None))


class TestTable(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        races = {"s": {"日付": "2026-09-01", "場": "中山", "R": 11,
                       "水準": 0.6789}}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "race_levels.json"
            rl.save_table(races, p)
            tbl = rl.load_table(p)
            self.assertAlmostEqual(tbl[rl.table_key("2026-09-01", "中山", 11)],
                                   0.6789, places=4)
            self.assertIn("クラス中央値", json.loads(p.read_text(encoding="utf-8")))

    def test_missing_file_is_empty(self):
        self.assertEqual(rl.load_table(Path("/nonexistent/race_levels.json")), {})

    def test_level_of_record_needs_all_three_keys(self):
        tbl = {rl.table_key("2026-09-01", "中山", "11"): 0.3}
        self.assertEqual(rl.level_of_record(
            {"日付": "2026-09-01", "場": "中山", "R": "11"}, tbl), 0.3)
        self.assertIsNone(rl.level_of_record(
            {"日付": "2026-09-01", "場": "", "R": "11"}, tbl))


class TestNotes(unittest.TestCase):
    """表示は交差で『差あり＋期間再現』を通った形だけに出す。"""

    def splits(self):
        """6頭。上位1/3・下位1/3はそれぞれ2頭になる。

        水準だけ上位（水準↑×相対↓）と相対だけ上位（水準↓×相対↑）を
        混ぜてあるので、**両方が揃った1頭にしか出ない**ことを確かめられる。
        """
        return {
            "両方上位": rl.Split(4, 1.5, 0.6),
            "水準だけ": rl.Split(4, 1.4, -0.5),
            "相対だけ": rl.Split(4, -0.9, 0.5),
            "中1": rl.Split(4, 0.3, 0.1),
            "中2": rl.Split(4, 0.2, 0.0),
            "両方下位": rl.Split(4, -0.8, -0.6),
        }

    def test_top_is_only_flagged_for_favourites(self):
        s = self.splits()
        got = rl.horse_notes(s, {"両方上位": 1})
        self.assertIn("両方上位", got)
        self.assertIn("メンバー上位", got["両方上位"])
        # 6番人気なら同じ馬でも出さない（実測がその形で再現していない）
        self.assertNotIn("両方上位", rl.horse_notes(s, {"両方上位": 6}))

    def test_bottom_is_only_flagged_for_outsiders(self):
        s = self.splits()
        self.assertIn("両方下位", rl.horse_notes(s, {"両方下位": 9}))
        self.assertNotIn("両方下位", rl.horse_notes(s, {"両方下位": 2}))

    def test_one_component_alone_gets_nothing(self):
        """成分ごとでは帯によって期間再現しなかったので、片方だけでは出さない。"""
        got = rl.horse_notes(self.splits(),
                             {n: 1 for n in self.splits()})
        self.assertNotIn("水準だけ", got)
        self.assertNotIn("相対だけ", got)

    def test_middle_horses_get_nothing(self):
        got = rl.horse_notes(self.splits(), {n: 1 for n in self.splits()})
        self.assertNotIn("中1", got)
        self.assertNotIn("中2", got)

    def test_unknown_popularity_gets_nothing(self):
        self.assertEqual(rl.horse_notes(self.splits(), {"両方上位": None}), {})

    def test_note_carries_the_sample_size(self):
        got = rl.horse_notes(self.splits(), {"両方上位": 1})["両方上位"]
        self.assertIn("4走", got, "母数を併記していない")

    def test_race_note_needs_four_horses(self):
        self.assertIsNone(rl.race_note({"a": rl.Split(3, 0.5, 0.0)}))
        note = rl.race_note({str(i): rl.Split(3, 0.34, 0.0) for i in range(5)})
        self.assertIn("1勝クラス級", note)
        self.assertIn("5頭", note)


if __name__ == "__main__":
    unittest.main()


class TestRecordsBuilderDefault(unittest.TestCase):
    """馬別戦績の既定が 1-12R であること（他の集計と違えてある）。

    2026-09-21に既定（9-12R）のまま流して 81,445行→43,066行に縮め、
    持ち時計の発火を88%→56%に落とした。**予想が引く戦績は集計の
    母集団ではない**ので、ここだけ既定が違う。
    """

    def test_default_is_all_races(self):
        src = Path("scripts/build_horse_records.py").read_text(encoding="utf-8")
        self.assertIn('ap.add_argument("--races", default="1-12"', src)
        self.assertNotIn("DEFAULT_RACES", src,
                         "9-12R の既定を使うと前走の半分が抜ける")


class TestMidPopularityAvoidNote(unittest.TestCase):
    """4-5番人気の『弱い相手を離してきただけ』（−4.6p・差あり＋再現）。

    交差でこの形だけが中穴帯で通ったので、ここにしか出さない。
    """

    def splits(self):
        return {
            "弱相手を圧勝": rl.Split(4, -0.9, 0.6),   # 水準↓×相対↑
            "強相手で接戦": rl.Split(4, 1.5, -0.5),   # 水準↑×相対↓
            "両方上位": rl.Split(4, 1.4, 0.5),
            "中1": rl.Split(4, 0.3, 0.1),
            "中2": rl.Split(4, 0.2, 0.0),
            "両方下位": rl.Split(4, -0.8, -0.6),
        }

    def test_flagged_at_4_5th_favourite(self):
        got = rl.horse_notes(self.splits(), {"弱相手を圧勝": 4})
        self.assertIn("弱相手を圧勝", got)
        self.assertIn("弱い相手を離してきた", got["弱相手を圧勝"])

    def test_not_flagged_outside_that_band(self):
        s = self.splits()
        for nk in (1, 3, 6, 12):
            self.assertNotIn("弱相手を圧勝", rl.horse_notes(s, {"弱相手を圧勝": nk}),
                             f"{nk}番人気で出してはいけない")

    def test_level_up_close_finish_gets_nothing(self):
        """水準↑×相対↓ は期間で反転したので、どの帯でも出さない。"""
        s = self.splits()
        for nk in (1, 4, 8, 12):
            self.assertNotIn("強相手で接戦", rl.horse_notes(s, {"強相手で接戦": nk}))
