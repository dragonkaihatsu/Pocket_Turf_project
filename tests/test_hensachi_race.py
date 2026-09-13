"""レース内偏差値の帯分けを検証するスクリプトの固定テスト。

いちばん固定したいのは「混戦」がほぼ発火しないという事実そのものではなく、
**帯の境目を勝手に動かさないこと**と、1位の偏差値が頭数で上がる性質を
検証側が拾えることである。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from keiba.hensachi import CLEAR, SLIGHT, deviations
import hensachi_race as hr


class TestBands(unittest.TestCase):
    def test_band_thresholds_match_hensachi(self):
        """帯の境目は keiba/hensachi.py と同じ値を使う（2か所に書かない）。"""
        self.assertEqual(hr.band_of(CLEAR), "抜けている")
        self.assertEqual(hr.band_of(CLEAR - 0.1), "やや優位")
        self.assertEqual(hr.band_of(SLIGHT), "やや優位")
        self.assertEqual(hr.band_of(SLIGHT - 0.1), "混戦")

    def test_odds_band(self):
        self.assertEqual(hr.odds_band(1.9), "1倍台")
        self.assertEqual(hr.odds_band(2.0), "2倍台")
        self.assertEqual(hr.odds_band(2.9), "2倍台")
        self.assertEqual(hr.odds_band(3.0), "3倍以上")
        self.assertEqual(hr.odds_band(None), "不明")


class TestTopDeviationGrowsWithFieldSize(unittest.TestCase):
    """1位の偏差値は頭数で上がる。だから「抜けている」は接戦度の指標にならない。

    同じ形の分布（等間隔）を頭数だけ変えて作ると、最大値の偏差値が単調に
    上がることを確認する。ここが崩れたら report_fieldsize の読み方も変わる。
    """

    def test_monotonic(self):
        tops = []
        for n in (8, 12, 16, 18):
            vals = [float(i) for i in range(n)]      # 形は同じ、頭数だけ変える
            tops.append(max(deviations(vals)))
        self.assertEqual(tops, sorted(tops))
        self.assertGreater(tops[-1], tops[0])

    def test_flat_field_already_counts_as_clear(self):
        """完全に等間隔（＝突出した馬がいない）でも、8頭で既に閾値65を超える。

        これが「抜けている」が1,971レース中1,460レースで出た理由である。
        閾値が『抜けている』を意味していない、という欠陥をここで固定する。
        """
        for n in (8, 12, 16):
            self.assertGreaterEqual(max(deviations([float(i) for i in range(n)])), CLEAR,
                                    f"{n}頭の等間隔でも CLEAR を超えるはず")


class TestBoxes(unittest.TestCase):
    def test_sizes(self):
        b = hr.boxes([1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(len(b["ワイド 上位3頭BOX"][1]), 3)
        self.assertEqual(len(b["ワイド 上位6頭BOX"][1]), 15)
        self.assertEqual(len(b["馬連 上位4頭BOX"][1]), 6)

    def test_only_top_n_used(self):
        """7頭目以降が買い目に混ざらないこと。"""
        b = hr.boxes([1, 2, 3, 4, 5, 6, 7])
        used = {u for t in b["ワイド 上位6頭BOX"][1] for u in t}
        self.assertNotIn(7, used)


class TestFirstPlace(unittest.TestCase):
    def test_reads_first(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.csv"
            p.write_text("着順,馬番\n3,5\n1,9\n2,4\n", encoding="utf-8-sig")
            self.assertEqual(hr.first_place(p), 9)

    def test_missing_first(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.csv"
            p.write_text("着順,馬番\n中止,5\n除外,9\n", encoding="utf-8-sig")
            self.assertIsNone(hr.first_place(p))


if __name__ == "__main__":
    unittest.main()
