"""中央（JRA）のページは地方と markup が違う。その差分を固定するテスト。

実際に踏んだ違い:
  * 着順テーブルのクラスに ResultMain が付かない（idは共通）
  * 中央だけ「コーナー通過順」列があり、位置で切ると厩舎と馬体重がずれる
  * レース名が <h1 class="RaceName">（地方は <div>）
  * 等級が名前ではなくアイコンのクラスにしか出ない
  * 馬柱のセルが <div class="Horse01">（地方は <dt>）
  * 脚質が <span class="kyakusitu">（地方は <div class="Type"><span>）
  * 馬柱に「[馬記号] 馬名 [ブリンカー]」という凡例行が混ざる
  * 発走後はオッズ配信が止まり ---.- になる
"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.collect import (
    JRA_VENUE_CODES,
    RaceData,
    backfill_odds,
    jra_venue_of,
    parse_result,
    parse_shutuba_past,
)


def _result_html(extra_col: bool, name_tag: str) -> str:
    """中央/地方の着順テーブルを最小限で再現する。"""
    corner_h = "<th>コーナー\n通過順</th>" if extra_col else ""
    corner_d = "<td>2-2</td>" if extra_col else ""
    return f"""
    <title>テストC(G3) 結果・払戻 | 2026年8月23日 札幌11R レース情報(JRA)</title>
    <{name_tag} class="RaceName">テストC
      <span class="Icon_GradeType Icon_GradeType3"></span></{name_tag}>
    <div class="RaceData01">15:45発走 /<span> 芝1200m</span> (右) / 天候:晴
      <span class="Item04">/ 馬場:良</span></div>
    <div class="RaceData02">2回 札幌 2日目 サラ系３歳以上 16頭</div>
    <table id="All_Result_Table">
    <tr><th>着\n順</th><th>枠</th><th>馬\n番</th><th>馬名</th><th>性齢</th><th>斤量</th>
    <th>騎手</th><th>タイム</th><th>着差</th><th>人\n気</th><th>単勝\nオッズ</th>
    <th>後3F</th>{corner_h}<th>厩舎</th><th>馬体重\n (増減)</th></tr>
    <tr><td>1</td><td>7</td><td>14</td><td>サウンドモリアーナ</td><td>牝4</td><td>55.0</td>
    <td>武豊</td><td>1:07.7</td><td></td><td>5</td><td>12.9</td>
    <td>33.6</td>{corner_d}<td>栗東\n武英</td><td>454(+4)</td></tr>
    </table>
    """


SHUTUBA_ROW = """
<tr class="HorseList">
  <td class="Waku1"></td><td class="Waku"> 1 </td>
  <td class="Horse_Info"><div class="fc">
    <div class="Horse01 fc">アドマイヤマーズ</div>
    <div class="Horse02"><a href="/horse/2022102887">ナムラクララ</a></div>
    <div class="Horse03">サンクイーンII</div>
    <div class="Horse04">(Storm Cat)</div>
    <div class="Horse05"><a href="/trainer/01173">栗東・長谷川</a></div>
    <div class="Horse06 fc"><img alt=""><span class="kyakusitu">差</span>中1週</div>
    <div class="Horse07 fc"><div class="Weight color-red">476kg<span>(-2)</span></div>
      <div class="Popular"><span id="odds-1_01">---.-</span>
        <span id="ninki-1_01">**</span></div></div>
  </div></td>
  <td class="Jockey"><span class="Barei">牝4栗</span><a href="#">浜中</a></td>
</tr>
<tr class="HorseList">
  <td class="Horse_Info"><div class="fc">
    <div class="Horse02">[馬記号] 馬名 [ブリンカー]</div>
  </div></td>
</tr>
"""


class TestJraResultParsing(unittest.TestCase):
    def test_venue_from_race_id(self):
        self.assertEqual(jra_venue_of("202601020211"), "札幌")
        self.assertEqual(jra_venue_of("202605030411"), "東京")
        self.assertEqual(jra_venue_of("209999020211"), "")

    def test_all_ten_jra_venues_have_codes(self):
        self.assertEqual(len(JRA_VENUE_CODES), 10)
        self.assertEqual(len(set(JRA_VENUE_CODES.values())), 10)

    def test_extra_corner_column_does_not_shift_stable_and_weight(self):
        """中央の余分な列で厩舎・馬体重がずれないこと。"""
        d = parse_result(_result_html(extra_col=True, name_tag="h1"), "202601020211")
        self.assertIsNotNone(d)
        row = d.horses[0]
        self.assertEqual(row["厩舎"], "栗東武英")
        self.assertEqual(row["馬体重"], "454(+4)")
        self.assertEqual(row["上がり3F"], "33.6")

    def test_local_layout_still_parses(self):
        d = parse_result(_result_html(extra_col=False, name_tag="div"), "202644011201")
        row = d.horses[0]
        self.assertEqual(row["厩舎"], "栗東武英")
        self.assertEqual(row["馬体重"], "454(+4)")

    def test_race_name_from_h1(self):
        d = parse_result(_result_html(extra_col=True, name_tag="h1"), "202601020211")
        self.assertEqual(d.info.name, "テストC")

    def test_grade_falls_back_to_the_title(self):
        # 中央は等級がアイコンのクラスにしか出ないためtitleから拾う
        d = parse_result(_result_html(extra_col=True, name_tag="h1"), "202601020211")
        self.assertEqual(d.info.grade, "G3")


class TestJraShutubaParsing(unittest.TestCase):
    def setUp(self):
        self.rows = parse_shutuba_past(SHUTUBA_ROW, date(2026, 8, 23))

    def test_legend_row_is_dropped(self):
        self.assertEqual(len(self.rows), 1)

    def test_div_cells_are_read(self):
        r = self.rows[0]
        self.assertEqual(r["馬名"], "ナムラクララ")
        self.assertEqual(r["血統父"], "アドマイヤマーズ")
        self.assertEqual(r["血統母父"], "Storm Cat")

    def test_kyakusitu_span_is_read(self):
        self.assertEqual(self.rows[0]["脚質"], "差し")
        self.assertEqual(self.rows[0]["間隔表記"], "中1週")

    def test_weight_with_extra_class_is_read(self):
        self.assertEqual(self.rows[0]["馬体重"], "476(-2)")

    def test_odds_are_absent_after_the_race(self):
        # 発走後は ---.- になるため取れない。結果から補完する必要がある
        self.assertIsNone(self.rows[0].get("単勝オッズ"))


class TestOddsBackfill(unittest.TestCase):
    def test_odds_are_filled_from_the_result_rows(self):
        data = RaceData(info=None)
        data.horses = [{"馬番": "1", "単勝オッズ": "22.0", "人気": "8"},
                       {"馬番": "2", "単勝オッズ": "3.4", "人気": "1"}]
        data.entries = [{"馬番": 1, "単勝オッズ": None}, {"馬番": 2, "単勝オッズ": None}]
        self.assertEqual(backfill_odds(data), 2)
        self.assertEqual(data.entries[0]["単勝オッズ"], 22.0)
        self.assertEqual(data.entries[0]["人気"], 8)

    def test_existing_odds_are_not_overwritten(self):
        data = RaceData(info=None)
        data.horses = [{"馬番": "1", "単勝オッズ": "22.0", "人気": "8"}]
        data.entries = [{"馬番": 1, "単勝オッズ": 19.9, "人気": 7}]
        self.assertEqual(backfill_odds(data), 0)
        self.assertEqual(data.entries[0]["単勝オッズ"], 19.9)


if __name__ == "__main__":
    unittest.main()
