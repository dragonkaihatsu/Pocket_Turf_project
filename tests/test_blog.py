import re
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.betting import make_betting_plan
from keiba.blog import (AMEBA_LIMIT, SAFE_LIMIT, fits_ameba, format_day_html,
                        format_race_html)
from keiba.marks import assign_marks
from keiba.models import Horse
from keiba.scoring import score_race

# アメブロのHTML編集が落とすタグ。生成物に混ざっていたら貼っても効かない
FORBIDDEN = re.compile(r"<\s*(script|style|link|meta|iframe|form|input)", re.I)


def _race(n=12):
    horses = [Horse.from_row({
        "馬番": str(i), "枠番": str((i + 1) // 2), "馬名": f"テスト馬{i}",
        "性齢": "牡4", "斤量": "56", "騎手": "テスト", "前走着順": str(i),
        "前走レース名": "前走", "上がり3F": f"{34.0 + i * 0.2:.1f}",
        "調教評価": "", "脚質": "先行", "単勝オッズ": f"{2.0 + i:.1f}",
        "人気": str(i),
    }) for i in range(1, n + 1)]
    scores = score_race(horses, None)
    marked = assign_marks(scores, baba="良")
    plan = make_betting_plan(marked, baba="良", favorite_odds=3.0)
    return horses, scores, marked, plan


def _payload(n=12):
    """build_payload と同じ形の最小データ。blog は site と同じ入力を受ける。"""
    horses=[{"rank":i,"mark":"◎○▲△△△注注"[i-1] if i<=8 else "","umaban":i,
             "waku":(i+1)//2,"name":f"テスト馬{i}","ninki":i,"odds":2.0+i,
             "kyaku":"先行","score":80-i*2,"ratio":1-0.03*i,"win":"—","place":"—",
             "measure":[{"label":"馬単体能力","pts":40.0,"max":45}],
             "items":[{"label":"基礎能力","note":"上がり3F 34.5"}]}
            for i in range(1,n+1)]
    return {"heading":"2026-09-06 中央","date":"2026-09-06","races":[{
        "venue":"中山","no":"11R","name":"テストステークス","surface":"芝2000m",
        "post":"15:45","horses":horses,
        "single":{"combo":"1-3","label":"ワイド 1位-3位","rec":True},
        "boxes":[{"kind":"馬連","width":4,"points":6,"rec":True,
                  "combos":["1-2","1-3","1-4","2-3","2-4","3-4"]},
                 {"kind":"ワイド","width":3,"points":3,"rec":False,
                  "combos":["1-2","1-3","2-3"]}],
        "result":None}]}


class TestAmebaHtml(unittest.TestCase):
    def setUp(self):
        from keiba.blog import format_day_html, format_race_html
        d=_payload()
        self.block=format_race_html(d["races"][0])
        self.day=format_day_html([self.block]*9, "9月6日（日）中央競馬")

    def test_no_tags_that_ameba_strips(self):
        """<style> や <script> は落とされるため、使っていたら見た目が壊れる。"""
        self.assertIsNone(FORBIDDEN.search(self.day))

    def test_styling_is_inline_only(self):
        self.assertIn('style="', self.block)
        self.assertNotIn("<style", self.block)

    def test_a_full_day_fits_in_one_article(self):
        """本文はHTMLタグ込みで半角60,000文字まで。9レースで収まること。"""
        from keiba.blog import AMEBA_LIMIT, SAFE_LIMIT, fits_ameba
        ok,n=fits_ameba(self.day)
        self.assertLess(n, AMEBA_LIMIT)
        self.assertTrue(ok, f"安全圏{SAFE_LIMIT}を超えた: {n}文字")

    def test_html_is_escaped(self):
        from keiba.blog import format_race_html
        d=_payload()
        d["races"][0]["horses"][0]["name"]="<b>悪意</b>"
        html=format_race_html(d["races"][0])
        self.assertIn("&lt;b&gt;", html)
        self.assertNotIn("<b>悪意", html)

    def test_公開ページから外した文言が復活していない(self):
        """回収率・黒字確率・買い目の型は公開ページに載せない方針。

        以前は blog が独自にデータを組み立てていたため、方針変更が
        反映されず古い文言のまま出続けていた。site と同じ入力にした。
        """
        for word in ("回収", "黒字", "波乱型", "標準型", "鉄板型", "ワイド1点"):
            self.assertNotIn(word, self.day, f"{word} が残っている")
        self.assertIn("気になるワイド", self.day)


class TestAmebaText(unittest.TestCase):
    """ブログの本文は等幅ではないので、テキスト版は桁揃えをしない。"""

    def setUp(self):
        from keiba.blog import format_day_text, format_race_text
        d=_payload()
        self.text=format_day_text([format_race_text(d["races"][0])]*9,
                                  "9月6日（日）中央競馬")

    def test_no_html_tags(self):
        self.assertNotIn("<", self.text)

    def test_no_column_alignment(self):
        """半角スペース3連続は桁揃えの痕跡。等幅でない環境で崩れる。"""
        for line in self.text.split("\n"):
            self.assertNotIn("   ", line)

    def test_lines_fit_a_phone(self):
        long=[l for l in self.text.split("\n") if len(l) > 20]
        self.assertLessEqual(len(long), 1, f"長すぎる行: {long[:3]}")


class TestSiteBuilder(unittest.TestCase):
    """docs/ に出す静的サイト。テンプレートの差し込み口が壊れていないか見る。"""

    def test_template_has_both_placeholders(self):
        from keiba.site import TEMPLATE
        tpl = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("__DATA__", tpl)
        self.assertIn("__ARCHIVE__", tpl)

    def test_render_fills_data_and_leaves_no_placeholder(self):
        from keiba.site import render
        html = render({"heading": "2026-09-05 中央", "date": "2026-09-05",
                       "races": []}, archive=["2026-09-04"])
        self.assertNotIn("__DATA__", html)
        self.assertNotIn("__ARCHIVE__", html)
        self.assertIn('href="d/2026-09-04.html"', html)

    def test_archive_block_is_dropped_when_empty(self):
        from keiba.site import render
        html = render({"heading": "x", "date": None, "races": []})
        self.assertNotIn("__ARCHIVE__", html)

    def test_json_cannot_close_the_script_tag(self):
        """馬名などに '</' が現れてもスクリプトが途中で閉じないこと。"""
        from keiba.site import render
        html = render({"heading": "</script><b>x", "date": None, "races": []})
        self.assertNotIn("</script><b>x", html)


class TestSiteLookups(unittest.TestCase):
    """設定ファイルの書式が揃っていないので、日付と競馬場は複数の場所から拾う。"""

    def test_iso_and_compact_dates(self):
        from keiba.site import find_date
        self.assertEqual(find_date("2026-09-05 中央"), "2026-09-05")
        self.assertEqual(find_date(None, "20260831_大井"), "2026-08-31")
        self.assertEqual(find_date("大井 8月31日 10R–12R", "20260831_大井"),
                         "2026-08-31")
        self.assertIsNone(find_date("見出しだけ", "config"))

    def test_venue_from_heading_or_filename(self):
        from keiba.site import find_venue
        # 大井の設定は競馬場が1つなので race ごとの venue を持たない
        self.assertEqual(find_venue(None, "大井 9月3日 10R–12R"), "大井")
        self.assertEqual(find_venue(None, None, None, "20260904_大井"), "大井")
        self.assertEqual(find_venue(None, "2026-09-05 中央", None, "20260905_中央"), "")
        self.assertEqual(find_venue("札幌", "x"), "札幌")
