"""画像化の下ごしらえ（貼る用HTMLを汚さないこと・全列が写ること）。"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import shot


class TestShotPage(unittest.TestCase):
    SHEET = '<style>.kompi{}</style>\n<div class="kompi">x</div>'

    def test_measure_script_only_when_measuring(self):
        """貼る用のHTML片に script を混ぜない（アメブロの禁止タグ）。"""
        self.assertNotIn("<script", shot.shot_page(self.SHEET))
        self.assertIn("<script", shot.shot_page(self.SHEET, measure=True))

    def test_scroll_box_is_opened_so_every_column_is_captured(self):
        """表は横スクロールの箱に入っている。画像では見えている分だけでは困る。"""
        css = shot.SHOT_CSS
        self.assertIn(".scroll{overflow:visible}", css.replace(" ", ""))
        self.assertIn("width:max-content", css)

    def test_page_is_a_whole_document(self):
        p = shot.shot_page(self.SHEET)
        self.assertTrue(p.startswith("<!doctype html>"))
        self.assertIn('<meta charset="utf-8">', p)
        self.assertIn('<div class="shot">', p)

    def test_size_pattern_reads_what_the_measure_script_writes(self):
        """測る側と読む側が同じ属性名であること（片方だけ直すと静かに壊れる）。"""
        for name in ("data-kw", "data-kh"):
            self.assertIn(f"'{name}'", shot.MEASURE)
        m = shot.SIZE_RE.search('<body data-kw="916" data-kh="736">')
        self.assertEqual((m.group(1), m.group(2)), ("916", "736"))


class TestFindChrome(unittest.TestCase):
    def test_headless_shell_comes_first(self):
        """同梱のchromium(--headless)はこの環境で文字を描かない。順番が要。"""
        self.assertIn("headless_shell", shot.CANDIDATES[0])
        rest = " ".join(shot.CANDIDATES[1:])
        self.assertNotIn("headless_shell", rest)

    def test_explicit_path_wins(self):
        self.assertEqual(shot.find_chrome("/tmp/my-chrome"), "/tmp/my-chrome")

    def test_found_executable_exists(self):
        """この環境で実際に見つかること（見つからないなら理由を出して落ちる）。"""
        try:
            p = shot.find_chrome()
        except RuntimeError as e:
            self.skipTest(str(e))
        self.assertTrue(Path(p).exists(), p)


if __name__ == "__main__":
    unittest.main()
