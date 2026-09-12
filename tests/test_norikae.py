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


class TestNameVariants(unittest.TestCase):
    """netkeibaの表記ゆれで誤って「格上げ」と判定しないことを固定する。

    実測の ratings.json には同じ騎手が複数のキーで入っている
    （`団野`(455騎乗) と `団野大`(7騎乗)）。最も具体的な一致を採ると
    n=7 の側を掴み、前走の一軍騎手を「一軍ではない」と誤判定して
    一軍→一軍の乗り替わりに加点してしまう（実例: 団野大成→菊沢）。
    """

    SPLIT = {"騎手": {
        "団野": {"n": 455, "複勝率": 0.30},     # 同一人物が
        "団野大": {"n": 7, "複勝率": 0.0},       # 2つのキーに割れている
        "菊沢": {"n": 472, "複勝率": 0.25},
        "国分恭": {"n": 195, "複勝率": 0.18},
        "小林美": {"n": 60, "複勝率": 0.10},
    }}

    def test_tier1_is_tolerant_to_split_keys(self):
        """前方一致するキーのどれかが基準を満たせば一軍とみなす。"""
        self.assertTrue(is_tier1_jockey("団野大成", self.SPLIT))
        self.assertTrue(is_tier1_jockey("団野", self.SPLIT))

    def test_tier1_to_tier1_change_is_not_an_upgrade(self):
        """団野大成→菊沢はどちらも一軍なので加点しない。"""
        it = correction_norikae(horse("菊沢", 14), records("団野大成"),
                                "2026-09-12", self.SPLIT)
        self.assertEqual(it.points, 0.0)

    def test_abbreviation_is_not_a_jockey_change(self):
        """国分恭介→国分恭 は継続騎乗（文字列は違うが同一人物）。"""
        from keiba.scoring import same_jockey
        self.assertTrue(same_jockey("国分恭介", "国分恭"))
        it = correction_norikae(horse("国分恭", 12), records("国分恭介"),
                                "2026-09-12", self.SPLIT)
        self.assertIn("継続騎乗", it.note)

    def test_different_people_are_not_merged(self):
        """角田大和と角田和は互いに前方一致しないので別人。"""
        from keiba.scoring import same_jockey
        self.assertFalse(same_jockey("角田大和", "角田和"))

    def test_upgrade_from_minor_still_fires(self):
        """本来の形（非一軍→一軍）は引き続き加点される。"""
        it = correction_norikae(horse("菊沢", 14), records("小林美"),
                                "2026-09-12", self.SPLIT)
        self.assertEqual(it.points, NORIKAE_KAKUAGE_POINTS)


class TestTier1DefinitionDoesNotLoosen(unittest.TestCase):
    """一軍の定義が収集量で緩まないことを固定する（2026-09-12）。

    `n >= 400` という生の騎乗数だけで切っていたため、1-8Rの収集で
    延べ騎乗が1.5倍になったところ一軍が15人→32人に増え、
    「前走二桁×一軍へ乗り替わり」の複勝率が16.9%→13.6%に薄まった。
    人数を固定して測ると16.2%で再現したので、効果が消えたのではなく
    **定義が緩んだ**だけだった。NORIKAE_KAKUAGE_POINTS はこの複勝率から
    校正しているため、緩むと補正の校正が静かに崩れる。
    """

    @staticmethod
    def roster(n_jockeys: int, scale: int = 1) -> dict:
        """騎乗数が等差で並ぶ騎手表。scale はコーパスの大きさ倍率。"""
        return {"騎手": {f"騎手{i:03d}": {"n": (n_jockeys - i) * 40 * scale,
                                        "複勝率": 0.22, "勝率": 0.07,
                                        "単勝回収率": 0.8}
                         for i in range(n_jockeys)}}

    def tier_size(self, ratings: dict) -> int:
        from keiba.scoring import is_tier1_jockey
        return sum(1 for name in ratings["騎手"]
                   if is_tier1_jockey(name, ratings))

    def test_corpus_growth_does_not_expand_the_tier(self):
        """コーパスが3倍になっても一軍の人数は増えない。"""
        base = self.tier_size(self.roster(300))
        for scale in (2, 3, 5):
            self.assertEqual(
                self.tier_size(self.roster(300, scale)), base,
                f"コーパス{scale}倍で一軍の人数が変わった"
                "（生の騎乗数で切ると緩む）")

    def test_tier_size_is_capped_at_topn(self):
        from keiba.scoring import JOCKEY_TIER1_TOPN
        self.assertLessEqual(self.tier_size(self.roster(300, 10)),
                             JOCKEY_TIER1_TOPN)

    def test_thin_corpus_names_nobody(self):
        """騎乗数が全員少ない薄いコーパスでは誰も一軍にしない。

        順位だけで決めると、母数が無いのに上位16人が一軍になってしまう。
        騎乗数の下限（JOCKEY_TIER1_RIDES）がそれを防ぐ。
        """
        thin = {"騎手": {f"騎手{i}": {"n": 30, "複勝率": 0.2}
                         for i in range(100)}}
        self.assertEqual(self.tier_size(thin), 0)

    def test_top_jockeys_are_still_tier1(self):
        from keiba.scoring import is_tier1_jockey
        r = self.roster(300)
        self.assertTrue(is_tier1_jockey("騎手000", r))    # 最多騎乗
        self.assertFalse(is_tier1_jockey("騎手299", r))   # 最少騎乗
