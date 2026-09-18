"""荒れそう／堅そうの判定が、実測表と一致し、作り話をしないこと。"""
import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import arare

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "data" / "profiles" / "jra" / "arare.json"


@dataclass
class H:
    ninki: int | None
    tansho_odds: float | None


def field(*odds):
    return [H(i + 1, o) for i, o in enumerate(odds)]


class TestShare(unittest.TestCase):
    def test_sum_of_reciprocals_of_the_top_three(self):
        self.assertAlmostEqual(arare.share3(field(2.0, 4.0, 5.0)),
                               0.5 + 0.25 + 0.2)

    def test_needs_three_horses(self):
        self.assertIsNone(arare.share3(field(2.0, 4.0)))

    def test_zero_or_missing_odds_is_not_guessed(self):
        self.assertIsNone(arare.share3(field(2.0, 0.0, 5.0)))
        self.assertIsNone(arare.share3([H(1, None), H(2, 3.0), H(3, 4.0)]))

    def test_uses_popularity_order_not_list_order(self):
        hs = [H(3, 8.0), H(1, 2.0), H(2, 4.0), H(4, 20.0)]
        self.assertAlmostEqual(arare.share3(hs), 0.5 + 0.25 + 0.125)


class TestBand(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(arare.odds_band(1.9), "1倍台")
        self.assertEqual(arare.odds_band(2.0), "2倍台")
        self.assertEqual(arare.odds_band(2.9), "2倍台")
        self.assertEqual(arare.odds_band(3.0), "3倍以上")

    def test_unknown_odds_has_no_band(self):
        self.assertIsNone(arare.odds_band(None))
        self.assertIsNone(arare.odds_band(0))


class TestJudgeMakesNothingUp(unittest.TestCase):
    def test_no_table_means_no_label(self):
        self.assertIsNone(arare.judge(2.5, field(2.5, 4.0, 6.0), table={}))

    def test_unknown_odds_means_no_label(self):
        t = arare.load_table(TABLE) if TABLE.exists() else {}
        self.assertIsNone(arare.judge(None, field(2.5, 4.0, 6.0), table=t))

    def test_missing_odds_in_field_means_no_label(self):
        t = arare.load_table(TABLE) if TABLE.exists() else {}
        self.assertIsNone(arare.judge(2.5, field(2.5, 4.0), table=t))

    def test_missing_file_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(arare.load_table(Path(tmp) / "無い.json"), {})


@unittest.skipUnless(TABLE.exists(), "判定表が無い")
class TestAgainstTheMeasuredTable(unittest.TestCase):
    def setUp(self):
        self.t = arare.load_table(TABLE)

    def test_label_follows_the_measured_hit_rate(self):
        """ラベルは実測の4頭BOX的中率だけで決まること。"""
        for band, cell in self.t.items():
            for name, v in cell["区分"].items():
                hit = v["4頭BOX的中"]
                want = (arare.LABELS[0] if hit >= arare.CLEAR
                        else arare.LABELS[2] if hit < arare.ROUGH
                        else arare.LABELS[1])
                # その区分に落ちる支持集中度を作って引き直す
                s = {"低い": cell["下限"] - 0.01,
                     "ふつう": (cell["下限"] + cell["上限"]) / 2,
                     "高い": cell["上限"] + 0.01}[name]
                odds = 3.0 / s      # 3頭で等分するとΣ(1/o)=s になる
                fav = {"1倍台": 1.5, "2倍台": 2.5, "3倍以上": 4.0}[band]
                got = arare.judge(fav, field(odds, odds, odds), table=self.t)
                self.assertEqual(got, want, f"{band}/{name}")

    def test_table_is_monotone_in_both_axes(self):
        """集中度が高いほど当たりやすく、帯が上がるほど当たりにくいこと。

        単調でなくなったら、その表を軸に使う根拠が消える。
        """
        for band, cell in self.t.items():
            hits = [cell["区分"][n]["4頭BOX的中"]
                    for n in ("低い", "ふつう", "高い") if n in cell["区分"]]
            self.assertEqual(hits, sorted(hits), f"{band} が集中度で単調でない")
        for name in ("低い", "ふつう", "高い"):
            across = [self.t[b]["区分"][name]["4頭BOX的中"]
                      for b in ("1倍台", "2倍台", "3倍以上")
                      if b in self.t and name in self.t[b]["区分"]]
            self.assertEqual(across, sorted(across, reverse=True),
                             f"{name} が帯で単調でない")

    def test_every_cell_has_enough_races(self):
        for band, cell in self.t.items():
            for name, v in cell["区分"].items():
                self.assertGreaterEqual(v["n"], 100, f"{band}/{name} の母数")


if __name__ == "__main__":
    unittest.main()
