"""乗り替わり補正のテスト。

**測れた条件にしか点を付けない**という性質を固定する。実測（中央9-12R
前走ペア14,485組）で効果が確認できたのは「前走二桁着順 × 一軍騎手へ
乗り替わり」だけで、前走1-5着からの格上げは母数755で差が無かった。
ここを緩めると、測っていない条件に点が付く状態に戻る。
"""
import unittest

from keiba.scoring import (NORIKAE_KAKUAGE_POINTS, correction_norikae,
                           is_tier1_jockey)
from keiba.models import Horse

RATINGS = {"騎手": {
    "ルメール": {"n": 900, "勝率": 0.25, "複勝率": 0.55, "単勝回収率": 0.9},
    "武豊": {"n": 500, "勝率": 0.12, "複勝率": 0.35, "単勝回収率": 0.8},
    "無名": {"n": 40, "勝率": 0.02, "複勝率": 0.10, "単勝回収率": 0.3},
}}


def horse(jockey: str, zenso: int | None, ninki: int | None = None) -> Horse:
    h = Horse.from_row({
        "馬番": "1", "枠番": "1", "馬名": "テスト馬", "性齢": "牡4",
        "斤量": "56", "騎手": jockey,
        "前走着順": "" if zenso is None else str(zenso),
        "前走レース名": "テスト特別", "上がり3F": "35.0", "調教評価": "",
        "脚質": "差し",
    })
    if ninki is not None:
        h.ninki = ninki
    return h


def records(prev_jockey: str, name: str = "テスト馬") -> dict:
    return {name: [{"馬名": name, "日付": "2026-08-01", "場": "中山",
                    "R": "10", "着順": "12", "騎手": prev_jockey,
                    "距離": "1800", "馬場種別": "ダート"}]}


class TestTier(unittest.TestCase):
    def test_tier_by_measured_rides_not_by_name_list(self):
        self.assertTrue(is_tier1_jockey("ルメール", RATINGS))
        self.assertTrue(is_tier1_jockey("武豊", RATINGS))
        self.assertFalse(is_tier1_jockey("無名", RATINGS))
        self.assertFalse(is_tier1_jockey("知らない騎手", RATINGS))

    def test_empty_name(self):
        self.assertFalse(is_tier1_jockey("", RATINGS))


class TestNorikae(unittest.TestCase):
    def test_double_digit_to_tier1_gets_points(self):
        """実測で効果が確認できた唯一の形。"""
        it = correction_norikae(horse("ルメール", 12), records("無名"),
                                "2026-09-12", RATINGS)
        self.assertEqual(it.points, NORIKAE_KAKUAGE_POINTS)
        self.assertIn("前走6-9着相当", it.note)

    def test_good_finish_to_tier1_gets_nothing(self):
        """前走1-5着からの格上げは母数755で差が無かった → 0点。"""
        it = correction_norikae(horse("ルメール", 3), records("無名"),
                                "2026-09-12", RATINGS)
        self.assertEqual(it.points, 0.0)
        self.assertIn("差なし", it.note)

    def test_tier1_to_tier1_gets_nothing(self):
        """一軍から一軍への替わりは『格上げ』ではない。"""
        it = correction_norikae(horse("ルメール", 12), records("武豊"),
                                "2026-09-12", RATINGS)
        self.assertEqual(it.points, 0.0)

    def test_continuation_gets_nothing(self):
        it = correction_norikae(horse("ルメール", 12), records("ルメール"),
                                "2026-09-12", RATINGS)
        self.assertEqual(it.points, 0.0)
        self.assertIn("継続騎乗", it.note)

    def test_middle_finish_is_unmeasured_so_zero(self):
        """前走6-9着は検証していないので点を付けない。"""
        it = correction_norikae(horse("ルメール", 7), records("無名"),
                                "2026-09-12", RATINGS)
        self.assertEqual(it.points, 0.0)
        self.assertIn("測れている条件に当たらない", it.note)

    def test_no_records_means_no_correction(self):
        """前走の騎手が分からない馬に補正を掛けない。

        データが無いことを『該当しない』と混同すると、全キャリアを
        取れていない馬だけ静かに評価が変わる。
        """
        it = correction_norikae(horse("ルメール", 12), None,
                                "2026-09-12", RATINGS)
        self.assertEqual(it.points, 0.0)
        self.assertIn("不明", it.note)

    def test_no_leak_from_future_runs(self):
        """レース日より後の戦績は前走として使わない。"""
        recs = {"テスト馬": [
            {"馬名": "テスト馬", "日付": "2026-08-01", "場": "中山", "R": "10",
             "着順": "12", "騎手": "無名", "距離": "1800", "馬場種別": "ダート"},
            {"馬名": "テスト馬", "日付": "2026-10-01", "場": "東京", "R": "11",
             "着順": "1", "騎手": "武豊", "距離": "1800", "馬場種別": "ダート"},
        ]}
        it = correction_norikae(horse("ルメール", 12), recs,
                                "2026-09-12", RATINGS)
        # 前走は8/01の「無名」であって、10/01の「武豊」ではない
        self.assertEqual(it.points, NORIKAE_KAKUAGE_POINTS)
        self.assertIn("無名", it.note)


class TestNoPopularityBasedJockeyFlag(unittest.TestCase):
    """人気帯×騎手ティアのフラグを持ち込まないことを固定する。

    CLAUDE.mdに「人気薄×極少騎乗は876騎乗で1勝＝ほぼ死んでいる」
    「人気薄×一軍騎手は102%」と書いていたが、母数をそろえて再判定すると
    どちらも差が無かった（n=393で勝率差-1.0p、1.8pt以上なら見えた／
    n=796で複勝率+1.5p、2.4pt以上なら見えた）。
    人気に応じて騎手の評価を変える実装を入れてはいけない。
    """

    def test_norikae_correction_ignores_popularity(self):
        for ninki in (1, 5, 12, None):
            h = horse("ルメール", 12, ninki)
            it = correction_norikae(h, records("無名"), "2026-09-12", RATINGS)
            self.assertEqual(it.points, NORIKAE_KAKUAGE_POINTS,
                             f"人気{ninki}で点数が変わった")

    def test_kishu_correction_ignores_popularity(self):
        from keiba.scoring import correction_kishu
        pts = set()
        for ninki in (1, 5, 12, None):
            h = horse("ルメール", 3, ninki)
            pts.add(correction_kishu(h, None, RATINGS).points)
        self.assertEqual(len(pts), 1, "騎手補正が人気で変わっている")


if __name__ == "__main__":
    unittest.main()


class TestLookupAmbiguity(unittest.TestCase):
    """略記の前方一致で別人を掴まないことを固定する。

    以前は辞書順で最初に当たったものを返していたため、表に岩田康と岩田望が
    両方ある状態で「岩田」を引くと、どちらかが返る実装だった。
    誰の成績か確定できないときは補正を掛けないのが正しい。
    """

    TABLE = {"岩田康": {"n": 344, "複勝率": 0.30},
             "岩田望": {"n": 473, "複勝率": 0.32},
             "丹内": {"n": 583, "複勝率": 0.28},
             "丹内祐": {"n": 3, "複勝率": 0.0}}

    def test_ambiguous_prefix_returns_none(self):
        from keiba.scoring import _lookup
        self.assertIsNone(_lookup(self.TABLE, "岩田"))

    def test_exact_match_wins_over_longer(self):
        from keiba.scoring import _lookup
        self.assertEqual(_lookup(self.TABLE, "丹内")["n"], 583)

    def test_unique_prefix_resolves(self):
        from keiba.scoring import _lookup
        self.assertEqual(_lookup(self.TABLE, "岩田望")["n"], 473)

    def test_full_name_matches_abbreviation(self):
        """表が略記で、渡された名前がフルネームのとき。"""
        from keiba.scoring import _lookup
        self.assertEqual(_lookup(self.TABLE, "岩田望来")["n"], 473)

    def test_picks_most_specific_abbreviation(self):
        from keiba.scoring import _lookup
        table = {"横山": {"n": 100}, "横山武": {"n": 494}}
        self.assertEqual(_lookup(table, "横山武史")["n"], 494)

    def test_ambiguous_jockey_gets_no_correction(self):
        """曖昧な名前の馬は乗り替わり補正を受けない。"""
        ratings = {"騎手": {"岩田康": {"n": 344, "複勝率": 0.3},
                            "岩田望": {"n": 473, "複勝率": 0.3},
                            "無名": {"n": 40, "複勝率": 0.1}}}
        it = correction_norikae(horse("岩田", 12), records("無名"),
                                "2026-09-12", ratings)
        self.assertEqual(it.points, 0.0)
