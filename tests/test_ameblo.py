"""アメブロ向け変換の固定テスト。

いちばん守りたいのは「禁止タグを1つも残さない」こと。1つでも混ざると
アメブロ側が投稿を拒否するので、変換が黙って壊れると気づけない。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_ameblo as ab

SAMPLE = (
    "<!doctype html>\n<html lang=\"ja\"><head><meta charset=\"utf-8\">"
    "<title>予想</title><style>:root{--a:#fff}body{margin:0}*{box-sizing:border-box}"
    ".card{color:red}@media (max-width:600px){.card{color:blue}}</style></head><body>"
    '<nav class="tabs"><button class="tab">9R</button></nav>'
    '<section class="race" data-race="9R"><div class="race-head">'
    '<span class="rno">9R</span><div><h2>テスト特別</h2></div></div>'
    '<div class="toolbar"><button class="seg-btn">馬番順</button></div>'
    '<div class="cards" data-cards>'
    '<details class="card" data-umaban="1" data-score="50.0"><summary>A</summary>'
    '<div class="bd"><table><tr><td>基礎能力</td></tr></table></div></details>'
    '<details class="card" data-umaban="2" data-score="70.0"><summary>B</summary>'
    '<div class="bd"><table><tr><td>基礎能力</td></tr></table></div></details>'
    "</div></section>"
    '<script>var x=1;</script></body></html>'
)


class TestProhibitedTags(unittest.TestCase):
    def test_none_remain(self):
        css, races = ab.convert(SAMPLE, ["中山"])
        for label, sec in races:
            doc = f'<style>{css}</style><div class="kb">{sec}</div>'
            self.assertEqual(ab.check_prohibited(doc), [], f"{label} に禁止タグ")

    def test_checker_actually_detects(self):
        """検出器そのものが効いていること（空を返すだけの実装を防ぐ）。"""
        self.assertIn("script", ab.check_prohibited("<script>x</script>"))
        self.assertIn("button", ab.check_prohibited('<button class="a">押</button>'))
        self.assertIn("body", ab.check_prohibited("<body>x</body>"))

    def test_style_is_not_prohibited(self):
        """style は禁止タグではない（禁止タグ一覧に無い）。落としてはいけない。"""
        self.assertNotIn("style", ab.PROHIBITED)


class TestCssScoping(unittest.TestCase):
    def test_root_and_body_are_replaced(self):
        out = ab.scope_css(":root{--a:#fff}body{margin:0}")
        self.assertIn(".kb{--a:#fff}", out)
        self.assertIn(".kb{margin:0}", out)
        self.assertNotIn(":root", out)

    def test_universal_selector_does_not_leak(self):
        """`*` をそのまま残すとアメブロのページ全体に当たる。"""
        out = ab.scope_css("*{box-sizing:border-box}")
        self.assertFalse(out.lstrip().startswith("*{"),
                         "セレクタが裸の * のままだとページ全体に当たる")
        self.assertIn(".kb *", out)
        # `*` が出るのは必ず `.kb ` の後ろだけ
        for i in (j for j, c in enumerate(out) if c == "*"):
            self.assertTrue(out[max(0, i - 4):i].endswith(".kb "), out[:80])

    def test_plain_selector_is_nested(self):
        self.assertIn(".kb .card{color:red}", ab.scope_css(".card{color:red}"))

    def test_media_query_inner_rules_are_scoped(self):
        out = ab.scope_css("@media (max-width:600px){.card{color:blue}}")
        self.assertIn("@media (max-width:600px)", out)
        self.assertIn(".kb .card", out)

    def test_keyframes_are_left_alone(self):
        """@keyframes の中は 0%/to などでセレクタではない。触ると壊れる。"""
        out = ab.scope_css("@keyframes fade{from{opacity:0}to{opacity:1}}")
        self.assertIn("from{opacity:0}", out)
        self.assertNotIn(".kb from", out)


class TestSorting(unittest.TestCase):
    def test_cards_come_out_in_score_order(self):
        """JSが無いと既定は馬番順。貼る前にスコア順へ並べ替える。"""
        _, races = ab.convert(SAMPLE, ["中山"])
        sec = races[0][1]
        self.assertLess(sec.index('data-score="70.0"'), sec.index('data-score="50.0"'))


class TestBreakdown(unittest.TestCase):
    def test_kept_by_default(self):
        _, races = ab.convert(SAMPLE, ["中山"])
        self.assertIn("基礎能力", races[0][1])

    def test_dropped_on_request(self):
        _, races = ab.convert(SAMPLE, ["中山"], drop_bd=True)
        sec = races[0][1]
        self.assertNotIn("基礎能力", sec)
        self.assertNotIn("<details", sec, "中身の無い details を残さない")
        self.assertIn("A", sec, "馬の行そのものは残す")


class TestLabels(unittest.TestCase):
    def test_venue_is_taken_from_config(self):
        """競馬場名はHTMLに入っていないので設定JSONから補う。"""
        _, races = ab.convert(SAMPLE, ["中山"])
        self.assertTrue(races[0][0].startswith("中山9R"))


if __name__ == "__main__":
    unittest.main()
