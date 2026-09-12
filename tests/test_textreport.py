"""買い目をそのまま書き写せるテキスト様式のテスト。"""
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.betting import make_betting_plan
from keiba.expectation import Expectation
from keiba.marks import assign_marks
from keiba.models import Horse
from keiba.scoring import score_race
from keiba.textreport import alt_order_note, format_day, format_race


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
        # 判定がどの時点のオッズによるものかを必ず添える（朝と最終で入れ替わる）
        self.assertIn("最終オッズで再判定", self.text)

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


class TestAltOrderNote(unittest.TestCase):
    """馬場の良/非良が反転したとき、買い目が変わるかを併記する。

    馬場は発走までに変わる。特にダートは乾いて回復するので朝の値が古くなり
    やすく、2026-09-12は生成後もダート4レースの馬場がずれていた。
    `assign_marks` は良か否かだけを見るので、反転で並びが動きうる。

    `HorseScore` の total_yoi / total_omoi は読み取り専用なので、
    並びだけを決める最小のスタブで測る（assign_marks はこの3つしか使わない）。
    """

    class Stub:
        def __init__(self, umaban: int, yoi: float, omoi: float):
            self.horse = SimpleNamespace(umaban=umaban)
            self.total_yoi = yoi
            self.total_omoi = omoi

    def scores(self, omoi: list[float]) -> list:
        """良馬場スコアは 10,9,8,… 固定。重馬場スコアだけを差し替える。"""
        return [self.Stub(i + 1, 10.0 - i, omoi[i]) for i in range(len(omoi))]

    def test_並びが変わらなければ何も出さない(self):
        same = [10.0 - i for i in range(10)]
        self.assertIsNone(alt_order_note(self.scores(same), "良", 8))

    def test_上位4頭の顔ぶれが同じなら買い目は変わらないと伝える(self):
        # 3番手(馬番3)と4番手(馬番4)だけを入れ替える → 上位4頭の集合は同じ
        omoi = [10.0 - i for i in range(10)]
        omoi[2], omoi[3] = omoi[3], omoi[2]
        note = alt_order_note(self.scores(omoi), "重", 8)
        self.assertIsNotNone(note)
        self.assertIn("買い目は変わらない", note)

    def test_上位4頭が入れ替わるなら馬番を出して警告する(self):
        # 重馬場スコアだけ4番手(馬番4)と5番手(馬番5)を入れ替える。
        # いま重で採点しているので現在の上位4頭は 1-2-3-5、
        # 対置する良の上位4頭は 1-2-3-4 → 集合が変わる
        omoi = [10.0 - i for i in range(10)]
        omoi[3], omoi[4] = omoi[4], omoi[3]
        note = alt_order_note(self.scores(omoi), "重", 8)
        self.assertIsNotNone(note)
        self.assertIn("買い目が変わる", note)
        self.assertIn("1-2-3-4", note)   # 対置する良の並びを出す

    def test_反転先は良の裏返しになる(self):
        omoi = [10.0 - i for i in range(10)]
        omoi[3], omoi[4] = omoi[4], omoi[3]
        # いま重馬場で採点しているなら、対置するのは良
        self.assertIn("馬場が良", alt_order_note(self.scores(omoi), "稍重", 8))
        # いま良で採点しているなら、対置するのは非良（稍重と表示する）
        self.assertIn("馬場が稍重", alt_order_note(self.scores(omoi), "良", 8))
