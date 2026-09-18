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


class TestHorseLinkExtraction(unittest.TestCase):
    """出走馬のリンクはアイコン用のタグを挟むことがあり、それでも馬名を拾う。"""

    PAST_HTML = (
        '<td class="Horse_Info"><dl><dt class="Horse02">'
        '<a href="https://db.netkeiba.com/horse/2017100627/" target="_blank">'
        '<span class="Icon_HorseMark Icon_kakuChi"></span>コスモギンガ</a>'
        '</dt></dl></td>'
        '<td><a href="https://db.netkeiba.com/horse/2019102109/">ラピード</a></td>'
    )

    def test_name_is_found_even_behind_an_icon_span(self):
        import tempfile

        from keiba.horsedb import horse_ids_from_cache

        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "202644090410_past.html").write_text(
                self.PAST_HTML, encoding="utf-8")
            found = horse_ids_from_cache(Path(d))

        # spanを挟む馬（出走馬本体）も、挟まない馬も、どちらも名前が付く
        self.assertEqual(found["2017100627"], "コスモギンガ")
        self.assertEqual(found["2019102109"], "ラピード")


class TestLookaheadGuardInScoring(unittest.TestCase):
    """score_race に as_of を渡すと未来の戦績が効かないことを確認する。"""

    def test_course_aptitude_needs_the_venue(self):
        """venue を渡さないとコース適性は中立のまま。

        以前は既定が「大井」で、中央のレースでも大井の実績を探しに行く
        潜在バグだった。開催場は必ず明示する。
        """
        from keiba.models import Horse
        from keiba.scoring import score_race

        horse = Horse.from_row({
            "馬番": "1", "枠番": "1", "馬名": "テストホース", "性齢": "牡4",
            "斤量": "56", "騎手": "テスト", "前走着順": "3", "前走レース名": "X",
            "上がり3F": "38.0", "調教評価": "", "脚質": "差し",
        })
        records = {"テストホース": parse_horse_results(SAMPLE_TABLE, "9999999999")}
        without = score_race([horse], None, kyori=1200, records=records)
        with_venue = score_race([horse], None, kyori=1200, venue="大井", records=records)
        c_without = next(i for i in without[0].base_items if i.label == "コース適性")
        c_with = next(i for i in with_venue[0].base_items if i.label == "コース適性")
        self.assertLess(c_without.points, c_with.points)
        self.assertIn("未提供", c_without.note)

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
        before = score_race([horse, other], None, kyori=1200, venue="大井",
                            records=records, as_of=date(2026, 2, 2))
        # 全戦績を見れば大井で1勝・平均2.0着 → 加点される
        after = score_race([horse, other], None, kyori=1200, venue="大井",
                           records=records)

        c_before = next(i for i in before[0].base_items if i.label == "コース適性")
        c_after = next(i for i in after[0].base_items if i.label == "コース適性")
        self.assertLess(c_before.points, c_after.points)
        self.assertIn("3走未満", c_before.note)
        self.assertIn("当地3走", c_after.note)


class TestLoadRecordsMergesBothFiles(unittest.TestCase):
    """既定は全キャリア版とコーパス版の**両方**を読む。

    既定が `horse_records.csv`（netkeiba を1頭ずつ取った220頭）だけを
    指していたため、本番の予想で持ち時計指数の発火が0%・コース適性の
    レース内点差が中央値0点になっていた。エラーは出ず旧尺度のスコアが
    静かに出るので、ここで固定する。
    """

    COLS_FULL = ("馬ID,馬名,日付,場,R,レース名,頭数,枠番,馬番,オッズ,人気,"
                 "着順,騎手,斤量,馬場種別,距離,馬場")
    COLS_CORPUS = COLS_FULL + ",タイム,着差,通過,ペース,上り"

    def _write(self, d: Path) -> None:
        # 全キャリア版: コーパスの収集範囲外の走（2019年）も持つ
        (d / "horse_records.csv").write_text(
            self.COLS_FULL + "\n"
            "2019104321,テスト馬,2019-05-05,東京,3,3歳未勝利,16,1,1,5.0,2,4,"
            "テスト,56,芝,1600,良\n"
            "2019104321,テスト馬,2026-01-10,中山,9,某特別,16,2,3,3.0,1,1,"
            "テスト,56,芝,1600,良\n",
            encoding="utf-8")
        # コーパス版: 同じ走をタイム付きで持つ（重なりはこちらを採る）
        (d / "horse_records_corpus.csv").write_text(
            self.COLS_CORPUS + "\n"
            "テスト馬,テスト馬,2026-01-10,中山,9,某特別,16,2,3,3.0,1,1,"
            "テスト,56,芝,1600,良,1:33.4,,1-1,34.5-34.9,34.9\n",
            encoding="utf-8")

    def test_merges_and_prefers_the_row_that_has_a_time(self):
        import tempfile

        import keiba.profile as profile
        from keiba.horsedb import load_records

        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self._write(d)
            orig = profile.Profile.path
            profile.Profile.path = lambda self, name: d / name
            try:
                recs = load_records()
            finally:
                profile.Profile.path = orig

        rows = [r for v in recs.values() for r in v]
        # 2走とも残る（1/10 は重複なので1行だけ）
        self.assertEqual(len(rows), 2)
        by_date = {r["日付"]: r for r in rows}
        # 重なった走はタイムを持つコーパス側
        self.assertEqual(by_date["2026-01-10"].get("タイム"), "1:33.4")
        # コーパスに無い走は全キャリア側から残る
        self.assertIn("2019-05-05", by_date)

    def test_explicit_path_reads_only_that_file(self):
        """--records を明示したら、そのファイルだけを読む。

        検証スクリプトが素材を絞って測れなくなると独立検証が壊れる。
        """
        import tempfile

        from keiba.horsedb import load_records

        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self._write(d)
            recs = load_records(d / "horse_records.csv")

        rows = [r for v in recs.values() for r in v]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.get("タイム") in (None, "") for r in rows))


if __name__ == "__main__":
    unittest.main()
