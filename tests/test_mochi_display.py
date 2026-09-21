"""持ち時計指数を予想に表示する（本人の指示・2026-09-21「新たなスピード指数に
切り替える」→「持ち時計を予想に表示する」）。

基礎能力25点の尺度は2026-09-13に上がり3Fから持ち時計指数へ変わっていたが、
**値は予想テキストに一度も出ていなかった**（`grep 持ち時計` が0件）。
採点は変えず、表示だけを足した。ここで固定するのは3点:

  1. 表示する値は**採点で使った量そのもの**（`scoring.mochi_delta` 経由）
  2. 作れない馬は**空**にする（中立値で埋めない）
  3. 何頭に作れたかをレースごとに出す（混在を隠さない）
"""
import unittest

from keiba.expectation import Expectation
from keiba.marks import assign_marks
from keiba.models import Horse
from keiba.scoring import MIN_MOCHI_FIELD, mochi_delta, score_race
from keiba.textreport import _horse_line, mochi_note


def horse(umaban: int, name: str, agari: str = "35.0") -> Horse:
    return Horse.from_row({
        "馬番": str(umaban), "枠番": str(umaban), "馬名": name, "性齢": "牡4",
        "斤量": "56", "騎手": "テスト騎手", "前走着順": "3",
        "前走レース名": "テスト特別", "上がり3F": agari, "調教評価": "",
        "脚質": "先行",
    })


class TestMochiDelta(unittest.TestCase):
    """採点と表示の共通の入口。"""

    def test_returns_member_mean_difference(self):
        mochi = {"A": 1.0, "B": 0.0, "C": -1.0, "D": 0.0}
        d, n = mochi_delta(mochi, "A")
        self.assertAlmostEqual(d, 1.0)
        self.assertEqual(n, 4)
        self.assertAlmostEqual(mochi_delta(mochi, "B")[0], 0.0)

    def test_absent_horse_is_none(self):
        self.assertIsNone(mochi_delta({"A": 1.0, "B": 0.0, "C": 0.0, "D": 0.0}, "Z"))

    def test_thin_field_is_none(self):
        """MIN_MOCHI_FIELD 未満では正規化が尺度にならないので採点も表示もしない。"""
        thin = {f"H{i}": 0.5 for i in range(MIN_MOCHI_FIELD - 1)}
        self.assertIsNone(mochi_delta(thin, "H0"))

    def test_empty_is_none(self):
        self.assertIsNone(mochi_delta(None, "A"))
        self.assertIsNone(mochi_delta({}, "A"))

    def test_scoring_note_uses_the_same_number(self):
        """注記の「平均差」と表示の値が同じであること（2か所で計算しない）。"""
        import keiba.scoring as sc
        hs = [horse(i, f"馬{i}") for i in range(1, 6)]
        mochi = {"馬1": 1.2, "馬2": 0.3, "馬3": -0.4, "馬4": -0.6, "馬5": -0.5}
        item = sc.score_kiso_nouryoku(hs[0], hs, mochi)
        d, _ = mochi_delta(mochi, "馬1")
        self.assertIn(f"平均差{d:+.2f}", item.note)


class TestHorseLine(unittest.TestCase):
    def _line(self, delta, field=6):
        hs = [horse(i, f"馬{i}") for i in range(1, 7)]
        scores = score_race(hs, None)
        for s in scores:
            s.mochi_delta, s.mochi_field, s.mochi_used = delta, field, True
        marked = assign_marks(scores)
        return _horse_line(1, marked[0], Expectation())

    def test_value_is_shown(self):
        self.assertIn("時計 +0.42", self._line(0.42))

    def test_negative_sign_is_shown(self):
        self.assertIn("時計 -0.42", self._line(-0.42))

    def test_blank_when_not_computable(self):
        """中立値を書かない。落ちた馬は空欄で見えるようにする。"""
        line = self._line(None)
        self.assertIn("時計    —", line)
        self.assertNotIn("+0.0", line)

    def test_other_columns_are_kept(self):
        line = self._line(0.1)
        for token in ("偏差", "1着", "着内"):
            self.assertIn(token, line)


class TestMochiNote(unittest.TestCase):
    def _scores(self, deltas, used=True):
        hs = [horse(i, f"馬{i}") for i in range(1, len(deltas) + 1)]
        scores = score_race(hs, None)
        for s, d in zip(scores, deltas):
            s.mochi_delta = d
            s.mochi_used = used and d is not None
        return scores

    def test_all_horses(self):
        self.assertEqual(mochi_note(self._scores([0.1] * 5)), "持ち時計 5/5頭")

    def test_partial_says_the_rest_falls_back(self):
        note = mochi_note(self._scores([0.1, 0.2, None, None, None]))
        self.assertIn("2/5頭", note)
        self.assertIn("上がり3Fで代替", note)

    def test_none_says_the_race_is_scored_by_agari(self):
        """2歳戦・障害では0頭になる。そのときこそ出す（旧尺度で採点される）。"""
        note = mochi_note(self._scores([None] * 5))
        self.assertIn("0/5頭", note)
        self.assertIn("上がり3Fで採点", note)

    def test_flavor_3_is_marked_display_only(self):
        """--agari-mix 1.0 では指数が作れても採点は上がり3F単独。"""
        note = mochi_note(self._scores([0.1] * 5, used=False))
        self.assertIn("表示のみ", note)


class TestScoreRaceCarriesTheValue(unittest.TestCase):
    def test_mochi_used_is_false_for_agari_only(self):
        hs = [horse(i, f"馬{i}") for i in range(1, 7)]
        mochi = {f"馬{i}": 0.1 * i for i in range(1, 7)}
        for mix, expected in ((0.0, True), (0.5, True), (1.0, False)):
            with self.subTest(mix=mix):
                import keiba.scoring as sc
                scores = [sc.score_horse(h, hs, None, None, mochi=mochi,
                                         agari_mix=mix) for h in hs]
                self.assertTrue(all(s.mochi_delta is not None for s in scores))
                self.assertEqual(scores[0].mochi_used, expected)

    def test_no_mochi_leaves_the_field_empty(self):
        hs = [horse(i, f"馬{i}") for i in range(1, 7)]
        scores = score_race(hs, None)
        self.assertTrue(all(s.mochi_delta is None for s in scores))
        self.assertTrue(all(not s.mochi_used for s in scores))


if __name__ == "__main__":
    unittest.main()
