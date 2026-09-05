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


class TestAmebaHtml(unittest.TestCase):
    def setUp(self):
        _, scores, marked, plan = _race()
        self.block = format_race_html("テスト11R テストS", "ダ1200m", "15:30",
                                      marked, scores, plan)
        self.day = format_day_html([self.block] * 9, "2026-09-05 予想")

    def test_no_tags_that_ameba_strips(self):
        """<style> や <script> は落とされるため、使っていたら見た目が壊れる。"""
        self.assertIsNone(FORBIDDEN.search(self.day))

    def test_styling_is_inline_only(self):
        self.assertIn('style="', self.block)
        self.assertNotIn("<style", self.block)

    def test_a_full_day_fits_in_one_article(self):
        """本文はHTMLタグ込みで半角60,000文字まで。9レースで収まること。"""
        ok, n = fits_ameba(self.day)
        self.assertLess(n, AMEBA_LIMIT)
        self.assertTrue(ok, f"安全圏{SAFE_LIMIT}を超えた: {n}文字")

    def test_one_race_is_small_enough_to_split(self):
        ok, n = fits_ameba(format_day_html([self.block], "テスト"))
        self.assertTrue(ok)
        self.assertLess(n, 12000)

    def test_html_is_escaped(self):
        horses, scores, marked, plan = _race()
        marked[0].score.horse.name = "<b>悪意</b>"
        html = format_race_html("R", "芝", "", marked, scores, plan)
        self.assertIn("&lt;b&gt;", html)
        self.assertNotIn("<b>悪意", html)

    def test_marks_and_numbers_survive(self):
        for token in ("◎", "○", "▲", "スコア順", "買い目", "候補"):
            self.assertIn(token, self.block)


class TestAmebaText(unittest.TestCase):
    """ブログは等幅フォントではないので、貼り付け用テキストは桁揃えに頼らない。"""

    def setUp(self):
        from keiba.blog import format_day_text, format_race_text
        _, scores, marked, plan = _race()
        self.block = format_race_text("テスト11R テストS", "ダ1200m", "15:30",
                                      marked, scores, plan)
        self.day = format_day_text([self.block] * 9, "2026-09-05 予想")

    def test_no_html(self):
        self.assertNotIn("<", self.day)

    def test_lines_fit_a_phone(self):
        """本文の行は全角17字（34桁）程度に収める。注意書きの散文は除く。"""
        from keiba.blog import _txt_width
        wide = [ln for ln in self.block.splitlines() if _txt_width(ln) > 40]
        self.assertEqual(wide, [], f"長すぎる行: {wide}")

    def test_no_column_padding(self):
        """半角スペースの連続で列を合わせていないこと（貼ると崩れるため）。"""
        self.assertNotIn("   ", self.block)

    def test_contains_the_essentials(self):
        for token in ("ワイド1点", "スコア順", "候補", "買い目", "◎"):
            self.assertIn(token, self.block)

    def test_wrapping_keeps_every_token(self):
        from keiba.blog import _wrap_tokens
        text = "回収156% 的中8% 90%区間80%〜246% 黒字86% 最大29連敗"
        lines = _wrap_tokens(text)
        self.assertGreater(len(lines), 1)
        self.assertEqual(" ".join(lines).split(), text.split())
