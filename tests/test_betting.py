import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.betting import (
    HARAN,
    HYOJUN,
    TEPPAN,
    favorite_odds_of,
    make_betting_plan,
    select_strategy,
)
from keiba.marks import assign_marks
from keiba.models import Horse, load_horses
from keiba.scoring import HorseScore, score_race

DATA = Path(__file__).resolve().parent.parent / "data"


def _marked(ninki_odds: dict[int, tuple[int, float]] | None = None):
    """宮益坂賞の実データに、任意で人気・オッズを付与して印を割り振る。"""
    horses = load_horses(DATA / "宮益坂賞_出走馬.csv")
    if ninki_odds:
        for h in horses:
            if h.umaban in ninki_odds:
                h.ninki, h.tansho_odds = ninki_odds[h.umaban]
    return assign_marks(score_race(horses, None, kyori=1800), baba="良")


class TestStrategySelection(unittest.TestCase):
    """荒れやすさの判定は1番人気の単勝オッズで行う（大井83レースの実測に基づく）。"""

    def test_boundaries(self):
        self.assertEqual(select_strategy(1.9), TEPPAN)
        self.assertEqual(select_strategy(2.0), HYOJUN)   # 2.0倍は標準側
        self.assertEqual(select_strategy(2.9), HYOJUN)
        self.assertEqual(select_strategy(3.0), HARAN)    # 3.0倍から波乱
        self.assertEqual(select_strategy(10.0), HARAN)

    def test_unknown_odds_falls_back_to_standard(self):
        self.assertEqual(select_strategy(None), HYOJUN)

    def test_favorite_odds_uses_ninki_column(self):
        marked = _marked({2: (3, 5.0), 13: (1, 2.4), 3: (2, 3.0)})
        self.assertEqual(favorite_odds_of(marked), 2.4)

    def test_favorite_odds_falls_back_to_min_odds(self):
        # 人気列が無い場合は最小オッズを1番人気とみなす
        marked = _marked()
        for m in marked:
            m.score.horse.ninki = None
        marked[0].score.horse.tansho_odds = 4.5
        marked[1].score.horse.tansho_odds = 1.8
        self.assertEqual(favorite_odds_of(marked), 1.8)


class TestPlanShapes(unittest.TestCase):
    def test_teppan_is_at_most_3_points_and_wide_only(self):
        plan = make_betting_plan(_marked(), favorite_odds=1.5)
        self.assertEqual(plan.strategy, TEPPAN)
        self.assertLessEqual(plan.total_points, 3)
        self.assertEqual(len(plan.umaren), 0)
        self.assertEqual(len(plan.wide), 3)

    def test_hyojun_flows_from_top_score_and_caps_at_10(self):
        marked = _marked()
        plan = make_betting_plan(marked, favorite_odds=2.5)
        self.assertEqual(plan.strategy, HYOJUN)
        self.assertLessEqual(plan.total_points, 10)
        axis = marked[0].score.horse.umaban
        for t in plan.umaren:
            self.assertIn(axis, [m.score.horse.umaban for m in t.horses])

    def test_haran_is_a_6_point_box_of_the_top_four(self):
        """波乱型はスコア上位4頭のBOX。

        軸を2・3番人気に固定していた旧型は、1番人気と4番人気で決まると
        買えなかった。実測（大井9-12R 43レース）でも旧型は回収率60%
        （90%区間36-86%）で、上位4頭BOXの300%（同66-671%）に大きく劣る。
        """
        marked = _marked({2: (1, 3.4), 13: (2, 4.1), 3: (3, 5.2)})
        plan = make_betting_plan(marked, favorite_odds=3.4)
        self.assertEqual(plan.strategy, HARAN)
        self.assertEqual(plan.total_points, 6)

        top4 = {m.score.horse.umaban for m in marked[:4]}
        for t in plan.umaren:
            umabans = {m.score.horse.umaban for m in t.horses}
            self.assertTrue(umabans <= top4, f"{t.label} が上位4頭の外にある")
        # 4頭の総当たりなので組み合わせは重複なく6通り
        combos = {frozenset(m.score.horse.umaban for m in t.horses) for t in plan.umaren}
        self.assertEqual(len(combos), 6)

    def test_haran_keeps_the_favorite_when_the_score_rates_it_highly(self):
        """1番人気でもスコア上位なら買い目に含める。

        ◎が1番人気と一致するとき、その馬の勝率は55%（n=109）ある。
        旧型はこれを軸から外していたため、9/3の11Rで1着馬を取り逃した。
        """
        marked = _marked({2: (1, 3.4), 13: (2, 4.1), 3: (3, 5.2)})
        fav = 2
        plan = make_betting_plan(marked, favorite_odds=3.4)
        if fav in {m.score.horse.umaban for m in marked[:4]}:
            covered = [t for t in plan.umaren
                       if fav in {m.score.horse.umaban for m in t.horses}]
            self.assertTrue(covered, "スコア上位の1番人気が買い目に入っていない")

    def test_explicit_strategy_overrides_odds(self):
        plan = make_betting_plan(_marked(), favorite_odds=1.2, strategy=HARAN)
        self.assertEqual(plan.strategy, HARAN)

    def test_note_records_the_reason(self):
        for odds in (1.5, 2.5, 3.5):
            plan = make_betting_plan(_marked(), favorite_odds=odds)
            self.assertIn(f"{odds:.1f}倍", plan.note)
            self.assertIn(plan.strategy, plan.note)

    def test_too_few_horses(self):
        plan = make_betting_plan([], favorite_odds=2.0)
        self.assertEqual(plan.total_points, 0)
        self.assertIn("生成できません", plan.note)


if __name__ == "__main__":
    unittest.main()
