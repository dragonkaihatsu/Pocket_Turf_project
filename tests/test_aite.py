"""メンバー質の差分（相手関係）を固定する。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.aite import BANDS, Index, label_of, note


def run(date, venue, r, chaku):
    return {"日付": date, "場": venue, "R": r, "着順": str(chaku)}


class TestLabels(unittest.TestCase):
    def test_band_edges(self):
        self.assertEqual(label_of(0.06), "相手弱化(大)")
        self.assertEqual(label_of(0.02), "相手弱化(小)")
        self.assertEqual(label_of(0.0), "ほぼ同等")
        self.assertEqual(label_of(-0.02), "相手強化(小)")
        self.assertEqual(label_of(-0.06), "相手強化(大)")

    def test_thresholds_match_the_measuring_script(self):
        """境目は `scripts/aite_delta.py` の dt() と同じでなければならない。

        2か所に書くと、測った区分と表示する区分が静かにずれる。
        """
        src = (Path(__file__).resolve().parent.parent
               / "scripts" / "aite_delta.py").read_text(encoding="utf-8")
        for lo, _, _ in BANDS:
            self.assertIn(f"{lo}", src)


class TestNoteOnlyForValidatedCombinations(unittest.TestCase):
    """独立検証を通った2パターンだけ出す。

    差分そのものには単調な関係が無く（弱化(大)と強化(大)がほぼ並ぶ）、
    しかもラベルはレース単位の事実になりやすい。OP戦では出走馬のほぼ
    全頭が「相手強化」になるので、裸のラベルを全頭に付けると判別の
    役に立たない（実際に8頭中7頭に付いた）。
    """

    def test_bare_label_is_not_emitted(self):
        self.assertIsNone(note(0.10, 5))     # 弱化だが前走5着
        self.assertIsNone(note(-0.10, 5))    # 強化だが前走5着
        self.assertIsNone(note(0.0, 12))     # ほぼ同等
        self.assertIsNone(note(0.10, None))  # 前走着順が不明
        self.assertIsNone(note(None, 12))    # 差分が作れない

    def test_the_two_validated_combinations(self):
        self.assertIn("前走二桁", note(0.10, 12))
        self.assertIn("相手弱化(大)", note(0.10, 12))
        self.assertIn("前走1-2着", note(-0.10, 1))
        self.assertIn("相手強化(大)", note(-0.10, 1))


class TestIndex(unittest.TestCase):
    def setUp(self):
        self.recs = {
            "勝ち馬": [run("2026-01-01", "中山", "9", 1),
                     run("2026-02-01", "中山", "9", 1),
                     run("2026-03-01", "中山", "9", 5)],
            "普通馬": [run("2026-01-01", "中山", "9", 3),
                     run("2026-02-01", "中山", "9", 4),
                     run("2026-03-01", "中山", "9", 2)],
            "弱い馬": [run("2026-01-01", "中山", "9", 8),
                     run("2026-02-01", "中山", "9", 9),
                     run("2026-03-01", "中山", "9", 7)],
            # メンバー質は自分を除いて3頭ぶん要るので4頭にする
            "もう1頭": [run("2026-01-01", "中山", "9", 6),
                     run("2026-02-01", "中山", "9", 6),
                     run("2026-03-01", "中山", "9", 6)],
        }
        self.ix = Index.build(self.recs)

    def test_prior_counts_only_runs_before_the_cutoff(self):
        self.assertEqual(self.ix.prior("勝ち馬", "2026-01-01"), (0, 0))
        self.assertEqual(self.ix.prior("勝ち馬", "2026-02-01"), (1, 1))
        self.assertEqual(self.ix.prior("勝ち馬", "2026-03-01"), (2, 2))
        self.assertEqual(self.ix.prior("勝ち馬", "2026-04-01"), (3, 2))

    def test_quality_needs_enough_horses_with_enough_starts(self):
        names = ["勝ち馬", "普通馬", "弱い馬"]
        # 1走ずつしか無い時点では、勝率を出せる馬が居ないので None
        self.assertIsNone(self.ix.quality(names, "2026-02-01"))
        # 2走ずつあれば出る（勝ち馬1.0・他0.0 の平均）
        q = self.ix.quality(names, "2026-03-01")
        self.assertAlmostEqual(q, 1 / 3, places=6)

    def test_quality_excludes_the_horse_itself(self):
        names = ["勝ち馬", "普通馬", "弱い馬"]
        # 自分を除くと勝率を出せるのが2頭になり、MIN_FIELD=3 に足りない
        self.assertIsNone(
            self.ix.quality(names, "2026-03-01", exclude="勝ち馬"))

    def test_previous_run_is_strictly_before(self):
        self.assertEqual(self.ix.previous_run("勝ち馬", "2026-03-01"),
                         ("2026-02-01", "中山", "9"))
        self.assertIsNone(self.ix.previous_run("勝ち馬", "2026-01-01"))

    def test_delta_does_not_look_at_today(self):
        """今日の着順を見てしまうと後知恵になる。

        今日の行を戦績に入れても、cutoff=今日 なので勝率には入らない。
        """
        field = ["勝ち馬", "普通馬", "弱い馬", "もう1頭"]
        d = self.ix.delta("勝ち馬", field, "2026-03-01")
        # 前走(2/1)のメンバーと今走のメンバーが同じ顔ぶれなので差は0
        self.assertIsNotNone(d)
        self.assertAlmostEqual(d, 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
