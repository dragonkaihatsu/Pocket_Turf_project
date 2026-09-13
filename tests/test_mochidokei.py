"""持ち時計指数のテスト。

固定したい性質は3つ:

1. **数字を作らない** — 基準が無い区分・タイム不明は None を返す（0 にしない）
2. **馬場の表記ゆれで静かに引けなくなる状態を作らない** — race_info は
   「稍」「不」と略すが、予想時の設定JSONは「稍重」「不良」で渡ってくる
3. **後知恵を入れない** — 指標はレース日より前・365日以内の走りだけから作る
"""
from __future__ import annotations

import unittest
from pathlib import Path

from keiba import mochidokei as mk
from keiba import scoring as sc
from keiba.models import Horse

BASE_TIMES = Path("data/profiles/jra/base_times.json")


def horse(umaban: int, name: str, agari: float | None = None) -> Horse:
    return Horse.from_row({
        "馬番": str(umaban), "枠番": "1", "馬名": name, "性齢": "牡4",
        "斤量": "56", "騎手": "テスト", "前走着順": "3",
        "前走レース名": "テスト特別",
        "上がり3F": "" if agari is None else f"{agari:.1f}",
        "調教評価": "", "脚質": "差し",
    })


class TestParseTime(unittest.TestCase):
    def test_formats(self):
        self.assertAlmostEqual(mk.parse_time("2:14.6"), 134.6)
        self.assertAlmostEqual(mk.parse_time("1:34.5"), 94.5)
        self.assertAlmostEqual(mk.parse_time("59.9"), 59.9)

    def test_unreadable_is_none_not_zero(self):
        for s in ("", None, "---", "中止", "1:2:3"):
            self.assertIsNone(mk.parse_time(s), s)


class TestBabaNormalisation(unittest.TestCase):
    """netkeibaの略記と設定JSONの表記が同じキーになること。

    ここがずれると馬場補正だけ静かに落ちる（エラーは出ない）。
    """

    def test_abbreviations_map_to_canonical(self):
        self.assertEqual(mk.canon_baba("稍"), "稍重")
        self.assertEqual(mk.canon_baba("不"), "不良")
        self.assertEqual(mk.canon_baba("稍重"), "稍重")
        self.assertEqual(mk.canon_baba("良"), "良")

    def test_unknown_is_none(self):
        self.assertIsNone(mk.canon_baba("やや重"))
        self.assertIsNone(mk.canon_baba(""))

    def test_key_is_the_same_either_way(self):
        self.assertEqual(mk.baba_key("中山", "芝", "稍"),
                         mk.baba_key("中山", "芝", "稍重"))


class TestBuild(unittest.TestCase):
    def rows(self, n: int, secs=None):
        secs = secs or [100.0, 101.0, 102.0]
        return [{"場": "中山", "馬場種別": "芝", "距離": "1600", "馬場": "良",
                 "秒": secs[i % len(secs)]} for i in range(n)]

    def test_thin_cell_is_dropped(self):
        b = mk.BaseTimes.build(self.rows(30), min_rows=100)
        self.assertEqual(b.cells, {})
        self.assertIsNone(b.index(100.0, "中山", "芝", "1600", "良"))

    def test_faster_time_gives_higher_index(self):
        b = mk.BaseTimes.build(self.rows(300), min_rows=100, min_baba_rows=100)
        fast = b.index(99.0, "中山", "芝", "1600", "良")
        slow = b.index(103.0, "中山", "芝", "1600", "良")
        self.assertGreater(fast, slow)

    def test_unknown_cell_returns_none(self):
        b = mk.BaseTimes.build(self.rows(300), min_rows=100)
        self.assertIsNone(b.index(100.0, "札幌", "芝", "1600", "良"))
        self.assertIsNone(b.index(None, "中山", "芝", "1600", "良"))


@unittest.skipUnless(BASE_TIMES.exists(), "基準表が未生成")
class TestRealBabaCorrection(unittest.TestCase):
    """実データで作った馬場補正の符号を固定する。

    芝は渋るほど時計が遅く、**ダートは渋るほど速くなる**（砂が締まる）。
    符号を取り違えると、濡れたダートの速い時計を能力と読む。
    実測では 芝6場すべて負・ダ8場すべて正で例外が無かった。
    """

    @classmethod
    def setUpClass(cls):
        cls.base = mk.BaseTimes.load(BASE_TIMES)

    def deltas(self):
        import collections
        by = collections.defaultdict(dict)
        for k, v in self.base.baba.items():
            ba, shu, baba = k.split(mk.SEP)
            by[(ba, shu)][baba] = v["delta"]
        return by

    def test_turf_slower_dirt_faster_when_wet(self):
        seen = {"芝": 0, "ダ": 0}
        for (ba, shu), d in self.deltas().items():
            if "良" not in d or "重" not in d:
                continue
            diff = d["重"] - d["良"]
            seen[shu] += 1
            if shu == "芝":
                self.assertLess(diff, 0, f"{ba}芝 重-良={diff:+.2f}")
            else:
                self.assertGreater(diff, 0, f"{ba}ダ 重-良={diff:+.2f}")
        self.assertGreaterEqual(seen["芝"], 5)
        self.assertGreaterEqual(seen["ダ"], 5)


class TestSummarize(unittest.TestCase):
    def test_best_and_recent(self):
        m = mk.summarize([1.0, 0.0, -1.0, 5.0], recent_runs=3)   # 新しい順
        self.assertEqual(m.n, 4)
        self.assertEqual(m.best, 5.0)
        self.assertAlmostEqual(m.recent, 0.0)   # 直近3走の平均

    def test_empty_is_none_not_zero(self):
        self.assertIsNone(mk.summarize([]))


class TestMemberDeltas(unittest.TestCase):
    def test_top_and_average(self):
        d = mk.member_deltas({1: 2.0, 2: 0.0, 3: -2.0})
        self.assertAlmostEqual(d[1][0], 0.0)      # 自分がトップ
        self.assertAlmostEqual(d[3][0], -4.0)
        self.assertAlmostEqual(d[1][1], 2.0)      # 平均0からの差
        self.assertEqual(mk.member_deltas({}), {})


class TestFromRecords(unittest.TestCase):
    def setUp(self):
        self.base = mk.BaseTimes.build(
            [{"場": "中山", "馬場種別": "芝", "距離": "1600", "馬場": "良",
              "秒": 94.0 + (i % 5) * 0.5} for i in range(500)],
            min_rows=100, min_baba_rows=100)

    def rec(self, d: str, sec: str):
        return {"日付": d, "場": "中山", "馬場種別": "芝", "距離": "1600",
                "馬場": "良", "タイム": sec}

    def test_uses_only_runs_before_as_of(self):
        rows = [self.rec("2026-01-10", "1:33.0"), self.rec("2026-02-10", "1:33.0"),
                self.rec("2026-03-10", "1:33.0"), self.rec("2026-04-10", "1:33.0")]
        self.assertIsNotNone(mk.from_records(rows, "2026-05-01", self.base))
        # 3走目の直前なら窓内2走しかないので作れない
        self.assertIsNone(mk.from_records(rows, "2026-03-01", self.base))

    def test_window_excludes_old_runs(self):
        rows = [self.rec("2024-01-10", "1:33.0"), self.rec("2024-02-10", "1:33.0"),
                self.rec("2024-03-10", "1:33.0")]
        self.assertIsNone(mk.from_records(rows, "2026-05-01", self.base))

    def test_jump_races_are_excluded(self):
        rows = [{**self.rec("2026-0%d-10" % i, "1:33.0"), "馬場種別": "障"}
                for i in (1, 2, 3)]
        self.assertIsNone(mk.from_records(rows, "2026-05-01", self.base))

    def test_field_indices_skips_horses_without_enough_runs(self):
        many = [self.rec("2026-0%d-10" % i, "1:33.0") for i in (1, 2, 3)]
        recs = {"多い": many, "少ない": many[:1]}
        out = mk.field_indices(recs, ["多い", "少ない", "いない"],
                               "2026-05-01", self.base)
        self.assertEqual(list(out), ["多い"])


class TestScoringUsesMochi(unittest.TestCase):
    """基礎能力の尺度が持ち時計に切り替わること、切り替わらない条件。"""

    def field(self):
        return [horse(i, f"馬{i}", agari=34.0 + i * 0.1) for i in range(1, 7)]

    def test_mochi_is_used_and_ordered_by_index(self):
        f = self.field()
        mochi = {h.name: v for h, v in zip(f, [2.0, 1.0, 0.0, -1.0, -2.0, -3.0])}
        pts = [sc.score_kiso_nouryoku(h, f, mochi).points for h in f]
        self.assertEqual(pts, sorted(pts, reverse=True))
        self.assertAlmostEqual(pts[0], sc.MAX_KISO)
        self.assertAlmostEqual(pts[-1], sc.MAX_KISO * 0.4)
        self.assertIn("持ち時計指数", sc.score_kiso_nouryoku(f[0], f, mochi).note)

    def test_absolute_level_does_not_change_the_points(self):
        """メンバー相対で読むこと。レース全体の水準がずれても点は変わらない。

        実測で絶対値は期間再現しなかった（1-3番人気の複勝リフトが
        2025 −0.5p → 2026 +3.4p）ので、水準に依存しては**いけない**。
        """
        f = self.field()
        a = {h.name: v for h, v in zip(f, [2.0, 1.0, 0.0, -1.0, -2.0, -3.0])}
        b = {k: v + 10.0 for k, v in a.items()}
        for h in f:
            self.assertAlmostEqual(sc.score_kiso_nouryoku(h, f, a).points,
                                   sc.score_kiso_nouryoku(h, f, b).points)

    def test_thin_field_falls_back_to_agari(self):
        f = self.field()
        mochi = {f[0].name: 2.0, f[1].name: 1.0}      # 2頭しか作れていない
        item = sc.score_kiso_nouryoku(f[0], f, mochi)
        self.assertIn("上がり3F", item.note)

    def test_horse_without_mochi_falls_back_to_agari(self):
        f = self.field()
        mochi = {h.name: 1.0 for h in f[1:]}          # 先頭だけ持っていない
        item = sc.score_kiso_nouryoku(f[0], f, mochi)
        self.assertIn("上がり3F", item.note)
        self.assertIn("代替", item.note)

    def test_manual_override_still_wins(self):
        f = self.field()
        f[0].kiso_nouryoku_override = 12.0
        mochi = {h.name: 1.0 for h in f}
        self.assertAlmostEqual(sc.score_kiso_nouryoku(f[0], f, mochi).points, 12.0)

    def test_points_stay_in_range(self):
        f = self.field()
        mochi = {h.name: v for h, v in zip(f, [9.9, 1.0, 0.0, -1.0, -2.0, -9.9])}
        for h in f:
            p = sc.score_kiso_nouryoku(h, f, mochi).points
            self.assertGreaterEqual(p, sc.MAX_KISO * 0.4)
            self.assertLessEqual(p, sc.MAX_KISO)


class TestHorseRecordSchema(unittest.TestCase):
    """戦績CSVの列に タイム が残っていること。

    これが落ちると持ち時計が作れず、基礎能力が黙って上がり3Fに戻る。
    """

    def test_fields_include_time(self):
        from keiba.horsedb import FIELDS
        for col in ("タイム", "着差", "上り", "ペース", "通過"):
            self.assertIn(col, FIELDS)

    def test_corpus_builder_uses_the_same_columns(self):
        import importlib
        m = importlib.import_module("scripts.build_horse_records")
        from keiba.horsedb import FIELDS
        self.assertEqual(list(m.COLUMNS), list(FIELDS))


if __name__ == "__main__":
    unittest.main()


class TestBaseTimesResolvedByVenue(unittest.TestCase):
    """基準表は**競馬場名から**探すこと。active() に頼らないこと。

    集計スクリプトはプロファイルを切り替えないものが多い
    （accuracy.py / calibrate.py は既定の nar のまま）。active() に頼ると
    中央のレースを採点しているのに nar の基準表を探して「無い」と判断し、
    静かに旧尺度（上がり3F）へ落ちる。実際にそれで A/B が12セル全部
    完全一致し、新尺度が動いていないことに気づきかけなかった。
    """

    def test_venue_decides_the_profile(self):
        from keiba import profile
        self.assertIn("jra", str(profile.for_venue("中山").path("base_times.json")))
        self.assertIn("nar", str(profile.for_venue("大井").path("base_times.json")))

    def test_for_venue_does_not_switch_the_global(self):
        from keiba import profile
        before = profile.active()
        profile.for_venue("中山")
        self.assertIs(profile.active(), before)

    @unittest.skipUnless(BASE_TIMES.exists(), "基準表が未生成")
    def test_jra_race_finds_the_table_even_with_nar_active(self):
        from keiba import profile
        profile.use("nar")
        try:
            self.assertIsNotNone(sc._base_times("中山"))
            self.assertIsNone(sc._base_times("大井"))
        finally:
            profile.use("nar")

    @unittest.skipUnless(BASE_TIMES.exists(), "基準表が未生成")
    def test_load_mochi_fires_for_a_jra_race_without_profile_switching(self):
        from keiba import profile
        profile.use("nar")
        rows = [{"日付": f"2026-0{i}-10", "場": "中山", "馬場種別": "芝",
                 "距離": "1600", "馬場": "良", "タイム": "1:33.0"}
                for i in (1, 2, 3)]
        horses = [horse(i, f"馬{i}", agari=34.0) for i in range(1, 7)]
        records = {h.name: rows for h in horses}
        got = sc.load_mochi(records, horses, "2026-09-13", None, venue="中山")
        self.assertEqual(len(got), 6, "中央のレースで持ち時計が作れていない")
