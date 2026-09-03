import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.betting import make_betting_plan
from keiba.marks import assign_marks
from keiba.models import Horse, HistoryRecord, load_history, load_horses
from keiba.pace import forecast_pace
from keiba.scoring import MAX_BASE, score_race

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class TestScoringBasics(unittest.TestCase):
    def test_max_base_is_85(self):
        self.assertEqual(MAX_BASE, 85)

    def test_age_parsing(self):
        h = Horse.from_row({"馬番": "1", "枠番": "1", "馬名": "A", "性齢": "牡7", "斤量": "58",
                             "騎手": "テスト", "前走着順": "1", "前走レース名": "X", "上がり3F": "34.0",
                             "調教評価": "A"})
        self.assertEqual(h.age, 7)

    def test_koreiuma_correction_scales_for_short_distance(self):
        from keiba.scoring import correction_koreiuma
        h8 = Horse.from_row({"馬番": "1", "枠番": "1", "馬名": "A", "性齢": "牡8", "斤量": "58",
                              "騎手": "テスト", "前走着順": "1", "前走レース名": "X", "上がり3F": "34.0",
                              "調教評価": "A"})
        self.assertAlmostEqual(correction_koreiuma(h8, 2000).points, -5.0)
        self.assertAlmostEqual(correction_koreiuma(h8, 1600).points, -3.75)


class TestSampleRacePipeline(unittest.TestCase):
    """data/サンプルステークス_*.csv を使ったエンドツーエンドの健全性チェック。"""

    @classmethod
    def setUpClass(cls):
        cls.horses = load_horses(DATA_DIR / "サンプルステークス_出走馬.csv")
        cls.history = load_history(DATA_DIR / "サンプルステークス_過去10年.csv")
        cls.scores = score_race(cls.horses, cls.history, kyori=2000)

    def test_all_horses_scored(self):
        self.assertEqual(len(self.scores), len(self.horses))

    def test_base_subtotal_within_bounds(self):
        for s in self.scores:
            self.assertGreaterEqual(s.base_subtotal, 0)
            self.assertLessEqual(s.base_subtotal, MAX_BASE)

    def test_course_experience_detected_for_repeat_runner(self):
        # テスト太郎は過去10年データに同名で出走歴あり→初コースペナルティが付かない
        taro = next(s for s in self.scores if s.horse.name == "テスト太郎")
        penalty = next(c for c in taro.corrections if c.label == "初コース・ぶっつけペナルティ")
        self.assertEqual(penalty.points, 0.0)

    def test_first_timer_gets_penalty(self):
        # ロクローは過去10年データに出走歴なし→ペナルティが付く
        rokuro = next(s for s in self.scores if s.horse.name == "ロクロー")
        penalty = next(c for c in rokuro.corrections if c.label == "初コース・ぶっつけペナルティ")
        self.assertEqual(penalty.points, -3.0)

    def test_handicap_discount_applied(self):
        rokuro = next(s for s in self.scores if s.horse.name == "ロクロー")
        zenso_item = next(i for i in rokuro.base_items if i.label == "前走内容")
        self.assertIn("0.9倍", zenso_item.note)

    def test_no_history_file_does_not_penalize_everyone(self):
        # 過去10年データ自体が未提供(None)の場合は「未経験と確認された」わけではないので
        # 初コースペナルティを一律には付けない（休養日数による判定は独立に効く）
        scores_no_history = score_race(self.horses, None, kyori=2000)
        for s in scores_no_history:
            penalty = next(c for c in s.corrections if c.label == "初コース・ぶっつけペナルティ")
            if s.horse.kyusoku_days is None or s.horse.kyusoku_days <= 180:
                self.assertEqual(penalty.points, 0.0, s.horse.name)

    def test_marks_assigned_in_score_order(self):
        marked = assign_marks(self.scores, baba="良")
        self.assertEqual(marked[0].mark, "◎")
        scores_desc = [m.score.total_yoi for m in marked]
        self.assertEqual(scores_desc, sorted(scores_desc, reverse=True))

    def test_betting_plan_respects_strategy_point_cap(self):
        # 買い目は荒れやすさ（1番人気オッズ）で3型に分かれ、それぞれ上限点数が違う
        from keiba.betting import MAX_POINTS
        marked = assign_marks(self.scores, baba="良")
        for odds, expected in [(1.5, "鉄板"), (2.5, "標準"), (3.5, "波乱")]:
            plan = make_betting_plan(marked, baba="良", favorite_odds=odds)
            self.assertEqual(plan.strategy, expected)
            self.assertLessEqual(plan.total_points, MAX_POINTS[expected])
            self.assertGreater(plan.total_points, 0)

    def test_pace_forecast_probabilities_sum_to_one(self):
        pace = forecast_pace(self.horses)
        self.assertAlmostEqual(sum(pace.probabilities.values()), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()


class TestExpectation(unittest.TestCase):
    """期待度%は実測の対応表がある時だけ出す（無ければ数字を捏造しない）。"""

    def test_no_calibration_yields_no_numbers(self):
        from keiba.expectation import Expectation
        exp = Expectation({})
        self.assertFalse(exp.available)
        self.assertIsNone(exp.lookup(1))
        self.assertEqual(exp.format(1), ("—", "—"))

    def test_small_sample_is_suppressed(self):
        from keiba.expectation import Expectation, MIN_SAMPLE
        cal = {"順位別": {"1": {"n": MIN_SAMPLE - 1, "勝率": 0.9, "複勝率": 1.0,
                              "勝率CI": [0.5, 1.0], "複勝率CI": [0.6, 1.0]}}}
        self.assertIsNone(Expectation(cal).lookup(1))

    def test_lookup_and_rank_bucketing(self):
        from keiba.expectation import Expectation, MAX_RANK, rank_key
        rec = {"n": 100, "勝率": 0.25, "複勝率": 0.5,
               "勝率CI": [0.2, 0.3], "複勝率CI": [0.4, 0.6]}
        cal = {"順位別": {"1": rec, f"{MAX_RANK + 1}位以下": rec}}
        exp = Expectation(cal)
        self.assertEqual(exp.lookup(1), (0.25, 0.5))
        self.assertEqual(rank_key(MAX_RANK + 5), f"{MAX_RANK + 1}位以下")
        self.assertEqual(exp.lookup(MAX_RANK + 5), (0.25, 0.5))

    def test_wilson_interval_brackets_the_estimate(self):
        from keiba.expectation import wilson
        lo, hi = wilson(50, 100)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)
        self.assertEqual(wilson(0, 0), (0.0, 0.0))
