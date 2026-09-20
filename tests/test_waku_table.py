"""枠順補正の場×芝ダ代用表（`scripts/build_waku_table.py`）を固定する。

`correction_wakuban` は本来「同一レース名の過去10年データ」
（`HistoryRecord`）を要求する設計だが、日々の自動予想では一度も渡って
いない（発火率0%）。代わりに `keiba/courses.py` と同じ「場で束ねる」
やり方で、場×芝ダの枠番バイアスをコーパス（1-12R）から作った代用表を
使えるようにした。ここではその優先順位（レース固有データ→代用表→無し）と、
採用フラグが立っていないセルでは補正しないことを固定する。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.models import Horse, HistoryRecord
from keiba.scoring import correction_wakuban


def make_horse(wakuban: int) -> Horse:
    return Horse.from_row({
        "馬番": "1", "枠番": str(wakuban), "馬名": "テスト", "性齢": "牡4",
        "斤量": "56", "騎手": "テスト", "前走着順": "3",
        "前走レース名": "X", "上がり3F": "34.0", "調教評価": "",
    })


class TestNoDataNoCorrection(unittest.TestCase):
    def test_no_history_no_stats_scores_zero(self):
        h = make_horse(1)
        item = correction_wakuban(h, None)
        self.assertEqual(item.points, 0.0)

    def test_stats_without_venue_or_surface_scores_zero(self):
        h = make_horse(1)
        stats = [{"場": "中山", "芝ダ": "芝", "枠帯": "内枠(1-2)",
                  "差": 0.05, "n": 1000}]
        # venue/surface のどちらかが無ければ引けない
        item = correction_wakuban(h, None, venue=None, surface="芝2000m",
                                  waku_stats=stats)
        self.assertEqual(item.points, 0.0)
        item = correction_wakuban(h, None, venue="中山", surface=None,
                                  waku_stats=stats)
        self.assertEqual(item.points, 0.0)


class TestHistoryTakesPriority(unittest.TestCase):
    """レース固有の過去10年データがあれば、代用表より優先する。"""

    def test_history_present_ignores_stats_table(self):
        h = make_horse(1)
        history = [
            HistoryRecord(year=2020, race_name="X", umaban=1, wakuban=1,
                         name="A", chakujun=1, kyori=2000, baba="良", agari_3f=34.0),
            HistoryRecord(year=2020, race_name="X", umaban=2, wakuban=2,
                         name="B", chakujun=8, kyori=2000, baba="良", agari_3f=35.0),
            HistoryRecord(year=2021, race_name="X", umaban=1, wakuban=1,
                         name="C", chakujun=1, kyori=2000, baba="良", agari_3f=34.0),
            HistoryRecord(year=2021, race_name="X", umaban=2, wakuban=2,
                         name="D", chakujun=9, kyori=2000, baba="良", agari_3f=35.0),
        ]
        # 代用表は逆方向（1枠が不利）を示していても、historyがあれば無視される
        stats = [{"場": "中山", "芝ダ": "芝", "枠帯": "内枠(1-2)",
                  "差": -0.10, "n": 1000}]
        item = correction_wakuban(h, history, venue="中山", surface="芝2000m",
                                  waku_stats=stats)
        self.assertGreater(item.points, 0)
        self.assertIn("レース固有", item.note)


class TestTableFallback(unittest.TestCase):
    """history が無いときだけ、場×芝ダ代用表を引く。"""

    def _stats(self):
        return [
            {"場": "中山", "芝ダ": "芝", "枠帯": "内枠(1-2)",
             "差": 0.027, "n": 1569},
            {"場": "中山", "芝ダ": "芝", "枠帯": "外枠(7-8)",
             "差": -0.031, "n": 2140},
            {"場": "新潟", "芝ダ": "芝", "枠帯": "内枠(1-2)",
             "差": -0.056, "n": 1262},
        ]

    def test_inside_frame_gets_positive_points(self):
        h = make_horse(1)  # 内枠(1-2)
        item = correction_wakuban(h, None, venue="中山", surface="芝2000m",
                                  waku_stats=self._stats())
        self.assertEqual(item.points, 2.0)

    def test_outside_frame_gets_negative_points(self):
        h = make_horse(8)  # 外枠(7-8)
        item = correction_wakuban(h, None, venue="中山", surface="芝2000m",
                                  waku_stats=self._stats())
        self.assertEqual(item.points, -2.0)

    def test_large_diff_scales_to_three_points(self):
        h = make_horse(1)  # 内枠(1-2)。新潟芝は-5.6pなので符号は負、大きさは3点
        item = correction_wakuban(h, None, venue="新潟", surface="芝1400m",
                                  waku_stats=self._stats())
        self.assertEqual(item.points, -3.0)

    def test_middle_frame_is_out_of_scope(self):
        """3-6枠（中枠）は表に無いので0点。"""
        h = make_horse(4)
        item = correction_wakuban(h, None, venue="中山", surface="芝2000m",
                                  waku_stats=self._stats())
        self.assertEqual(item.points, 0.0)

    def test_unlisted_venue_scores_zero(self):
        """採用セルに無い場（差なし/判定不能だった場）は補正しない。"""
        h = make_horse(1)
        item = correction_wakuban(h, None, venue="東京", surface="芝2000m",
                                  waku_stats=self._stats())
        self.assertEqual(item.points, 0.0)

    def test_dirt_does_not_borrow_turf_bias(self):
        """芝の実測をダートに流用しない（中山ダートは符号が逆）。"""
        h = make_horse(1)
        item = correction_wakuban(h, None, venue="中山", surface="ダ1200m",
                                  waku_stats=self._stats())
        self.assertEqual(item.points, 0.0)


class TestOnlyAdoptedCellsAreLoaded(unittest.TestCase):
    """`load_waku_stats` は『採用』フラグが立ったセルだけを返す。"""

    def test_filters_by_adopted_flag(self):
        import json
        import tempfile
        from keiba.scoring import load_waku_stats

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "waku_stats.json"
            p.write_text(json.dumps({
                "組み合わせ": [
                    {"場": "中山", "芝ダ": "芝", "枠帯": "内枠(1-2)",
                     "差": 0.027, "採用": True},
                    {"場": "東京", "芝ダ": "芝", "枠帯": "内枠(1-2)",
                     "差": 0.011, "採用": False},
                ]
            }, ensure_ascii=False), encoding="utf-8")
            out = load_waku_stats(path=p)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["場"], "中山")


if __name__ == "__main__":
    unittest.main()
