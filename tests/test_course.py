import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.course import (
    analyze,
    load_corpus,
    parse_passing_order,
    tally_by_corner,
    winner_corner_distribution,
)

COLLECTED = Path(__file__).resolve().parent.parent / "data" / "collected"


class TestParsePassingOrder(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(parse_passing_order("2,6,5"), {2: 1, 6: 2, 5: 3})

    def test_parentheses_share_position(self):
        # 括弧内は横並び＝同一順位。括弧の次は「その次の順位」ではなく通し番号が進む
        self.assertEqual(parse_passing_order("2,(5,12),3"), {2: 1, 5: 2, 12: 2, 3: 3})

    def test_real_race(self):
        # 2026-09-02 大井11R の4コーナー
        pos = parse_passing_order("2,6,5,3,12,(8,4),1,13,14,(9,15),(7,10,16),11")
        self.assertEqual(pos[2], 1)
        self.assertEqual(pos[3], 4)     # 勝ち馬は4番手
        self.assertEqual(pos[8], 6)     # 括弧内は同位置
        self.assertEqual(pos[4], 6)
        self.assertEqual(pos[13], 8)    # 2着馬は8番手からの差し

    def test_empty(self):
        self.assertEqual(parse_passing_order(""), {})


@unittest.skipUnless(any(COLLECTED.glob("*_結果.csv")), "収集済みデータが必要")
class TestCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load_corpus(COLLECTED)

    def test_corpus_loaded(self):
        self.assertGreater(len(self.corpus), 0)
        self.assertGreater(len(self.corpus.races), 0)

    def test_every_runner_has_valid_finish(self):
        for r in self.corpus.runners:
            self.assertGreaterEqual(r.chakujun, 1)
            self.assertGreaterEqual(r.umaban, 1)

    def test_corner_tally_covers_all_positioned_runners(self):
        tally = tally_by_corner(self.corpus)
        counted = sum(v["頭数"] for v in tally.values())
        positioned = sum(1 for r in self.corpus.runners if r.corner4 is not None)
        self.assertEqual(counted, positioned)

    def test_rates_are_within_range(self):
        for section in ("人気別", "枠番別", "4角通過順位別"):
            for _, row in analyze(self.corpus)[section].items():
                if row["頭数"]:
                    self.assertLessEqual(row["勝率"], row["連対率"])
                    self.assertLessEqual(row["連対率"], row["複勝率"])
                    self.assertLessEqual(row["複勝率"], 1.0)

    def test_winner_distribution_sums_to_winner_count(self):
        w = winner_corner_distribution(self.corpus)
        self.assertEqual(sum(w["分布"].values()), w["勝ち馬数"])
        self.assertLessEqual(w["3番手以内の割合"], w["5番手以内の割合"])


if __name__ == "__main__":
    unittest.main()
