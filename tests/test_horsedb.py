import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.horsedb import (
    horse_name_from_html,
    parse_horse_results,
    records_before,
    summarize,
)

SAMPLE_TABLE = """
<title>テストホース (Test Horse)の競走成績 | 競走馬データ - netkeiba</title>
<table class="db_h_race_results">
<tr><th>日付</th><th>開催</th><th>天気</th><th>R</th><th>レース名</th><th>映像</th>
<th>頭数</th><th>枠番</th><th>馬番</th><th>オッズ</th><th>人気</th><th>着順</th>
<th>騎手</th><th>斤量</th><th>距離</th><th>馬場</th></tr>
<tr><td>2026/05/19</td><td>2大井3</td><td>晴</td><td>5</td><td>C2九</td><td></td>
<td>14</td><td>1</td><td>1</td><td>1.1</td><td>1</td><td>1</td>
<td>安藤洋一</td><td>56</td><td>ダ1200</td><td>良</td></tr>
<tr><td>2026/04/27</td><td>大井</td><td>曇</td><td>9</td><td>C212</td><td></td>
<td>13</td><td>8</td><td>12</td><td>2.0</td><td>1</td><td>3</td>
<td>安藤洋一</td><td>56</td><td>ダ1600</td><td>不</td></tr>
<tr><td>2026/03/01</td><td>川崎</td><td>晴</td><td>2</td><td>C3</td><td></td>
<td>13</td><td>8</td><td>13</td><td>5.0</td><td>4</td><td>7</td>
<td>安藤洋一</td><td>56</td><td>ダ1200</td><td>良</td></tr>
<tr><td>2026/02/01</td><td>大井</td><td>晴</td><td>2</td><td>C3</td><td></td>
<td>13</td><td>8</td><td>13</td><td>9.0</td><td>6</td><td>中止</td>
<td>安藤洋一</td><td>56</td><td>ダ1200</td><td>良</td></tr>
<tr><td>2026/01/10</td><td>大井</td><td>晴</td><td>3</td><td>C3</td><td></td>
<td>12</td><td>5</td><td>7</td><td>4.0</td><td>3</td><td>2</td>
<td>安藤洋一</td><td>56</td><td>ダ1200</td><td>良</td></tr>
</table>
"""


class TestHorseDb(unittest.TestCase):
    def setUp(self):
        self.rows = parse_horse_results(SAMPLE_TABLE, "9999999999")

    def test_name_is_taken_from_title(self):
        self.assertEqual(horse_name_from_html(SAMPLE_TABLE), "テストホース")
        self.assertEqual(self.rows[0]["馬名"], "テストホース")

    def test_kaisai_number_is_stripped_from_venue(self):
        # 「2大井3」のような回次付き表記でも場名だけになる
        self.assertEqual(self.rows[0]["場"], "大井")

    def test_distance_and_surface_split(self):
        self.assertEqual(self.rows[0]["距離"], "1200")
        self.assertEqual(self.rows[0]["馬場種別"], "ダ")

    def test_summarize_filters_by_venue(self):
        st = summarize(self.rows, ba="大井")
        self.assertEqual(st["出走"], 4)      # 中止を含む4走
        self.assertEqual(st["着順あり"], 3)   # 着順が付いたのは3走
        self.assertEqual(st["勝"], 1)
        self.assertEqual(st["複"], 3)
        self.assertAlmostEqual(st["平均着順"], 2.0)

    def test_summarize_filters_by_distance(self):
        st = summarize(self.rows, kyori=1200)
        self.assertEqual(st["出走"], 4)
        self.assertEqual(st["勝"], 1)

    def test_records_before_excludes_the_race_day_and_later(self):
        """後知恵の排除。予想対象日以降の戦績は絶対に見えてはいけない。"""
        past = records_before(self.rows, date(2026, 4, 27))
        self.assertEqual([r["日付"] for r in past],
                         ["2026-03-01", "2026-02-01", "2026-01-10"])
        # 4/27以降の大井2走は見えず、1/10の1走だけが残る
        self.assertEqual(summarize(past, ba="大井")["着順あり"], 1)

    def test_records_before_with_none_returns_everything(self):
        # 当日の予想では全戦績を使ってよい
        self.assertEqual(len(records_before(self.rows, None)), len(self.rows))

    def test_no_table_yields_no_rows(self):
        self.assertEqual(parse_horse_results("<html>なし</html>", "1"), [])


class TestLookaheadGuardInScoring(unittest.TestCase):
    """score_race に as_of を渡すと未来の戦績が効かないことを確認する。"""

    def test_future_record_does_not_change_score(self):
        from keiba.models import Horse
        from keiba.scoring import score_race

        horse = Horse.from_row({
            "馬番": "1", "枠番": "1", "馬名": "テストホース", "性齢": "牡4",
            "斤量": "56", "騎手": "テスト", "前走着順": "3", "前走レース名": "X",
            "上がり3F": "38.0", "調教評価": "", "脚質": "差し",
        })
        other = Horse.from_row({
            "馬番": "2", "枠番": "2", "馬名": "相手", "性齢": "牡4",
            "斤量": "56", "騎手": "テスト", "前走着順": "5", "前走レース名": "X",
            "上がり3F": "39.0", "調教評価": "", "脚質": "差し",
        })
        records = {"テストホース": parse_horse_results(SAMPLE_TABLE, "9999999999")}

        # 2026-02-02 時点で見えるのは大井1走（+中止1走）だけ → 母数不足で中立
        before = score_race([horse, other], None, kyori=1200,
                            records=records, as_of=date(2026, 2, 2))
        # 全戦績を見れば大井で1勝・平均2.0着 → 加点される
        after = score_race([horse, other], None, kyori=1200, records=records)

        c_before = next(i for i in before[0].base_items if i.label == "コース適性")
        c_after = next(i for i in after[0].base_items if i.label == "コース適性")
        self.assertLess(c_before.points, c_after.points)
        self.assertIn("3走未満", c_before.note)
        self.assertIn("当地3走", c_after.note)


if __name__ == "__main__":
    unittest.main()
