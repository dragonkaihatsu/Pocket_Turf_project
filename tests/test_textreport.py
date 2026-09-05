"""買い目をそのまま書き写せるテキスト様式のテスト。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.betting import make_betting_plan
from keiba.expectation import Expectation
from keiba.marks import assign_marks
from keiba.models import Horse
from keiba.scoring import score_race
from keiba.textreport import format_day, format_race


def _field(n=8):
    return [Horse.from_row({
        "馬番": str(i), "枠番": str(i), "馬名": f"テスト馬{i}", "性齢": "牡4",
        "斤量": "56", "騎手": "テスト", "前走着順": str(i), "前走レース名": "X",
        "上がり3F": f"{34.0 + i * 0.3:.1f}", "調教評価": "", "脚質": "先行",
        "単勝オッズ": f"{2.0 + i:.1f}", "人気": str(i),
    }) for i in range(1, n + 1)]


class TestTextReport(unittest.TestCase):
    def setUp(self):
        horses = _field()
        self.scores = score_race(horses, None, kyori=1200)
        self.marked = assign_marks(self.scores, baba="良")
        self.plan = make_betting_plan(self.marked, baba="良", favorite_odds=2.5)
        self.text = format_race("テスト11R テストS", "ダ1200m", "15:30",
                                self.marked, self.scores, self.plan, Expectation({}))

    def test_shows_score_order_with_ranks(self):
        lines = [l for l in self.text.splitlines() if l.strip().startswith(("1 ", "2 ", "3 "))]
        self.assertGreaterEqual(len(lines), 3)
        self.assertIn("◎", self.text)

    def test_lists_five_and_six_horse_candidates(self):
        """5頭・6頭の候補を馬番の並びで出す。"""
        self.assertIn("  5頭  ", self.text)
        self.assertIn("  6頭  ", self.text)
        top = [m.score.horse.umaban for m in self.marked[:6]]
        self.assertIn("-".join(str(u) for u in top[:5]), self.text)
        self.assertIn("-".join(str(u) for u in top), self.text)

    def test_candidates_follow_score_order(self):
        five = next(l for l in self.text.splitlines() if l.strip().startswith("5頭"))
        nums = [int(x) for x in five.split()[1].split("-")]
        self.assertEqual(nums, [m.score.horse.umaban for m in self.marked[:5]])

    def test_marks_exactly_one_recommended_bet(self):
        # 見出しの「★=推奨」ではなく、買い目の行だけを数える
        rows = [l for l in self.text.splitlines() if l.startswith("★")]
        self.assertEqual(len(rows), 1)
        self.assertIn("BOX", rows[0])

    def test_reports_whether_the_top_pick_matches_the_favorite(self):
        self.assertTrue("◎と1番人気: 一致" in self.text
                        or "◎と1番人気: 不一致" in self.text)

    def test_notes_that_training_is_not_scored(self):
        self.assertIn("調教は採点対象外", self.text)
        self.assertIn("満点75点", self.text)

    def test_missing_expectation_shows_a_dash_not_a_made_up_number(self):
        self.assertIn("1着—/着内—", self.text)

    def test_unmarked_horses_appear_as_reference(self):
        horses = _field(14)
        scores = score_race(horses, None, kyori=1200)
        marked = assign_marks(scores, baba="良")
        plan = make_betting_plan(marked, baba="良", favorite_odds=2.5)
        text = format_race("T", "ダ1200m", "15:30", marked, scores, plan, Expectation({}))
        self.assertIn("参考(印なし)", text)

    def test_format_day_joins_blocks_under_a_heading(self):
        day = format_day([self.text, self.text], "見出し")
        self.assertTrue(day.startswith("見出し"))
        self.assertEqual(day.count("テスト11R"), 2)


if __name__ == "__main__":
    unittest.main()
