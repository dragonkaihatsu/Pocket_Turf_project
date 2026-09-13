"""HTMLの書き出し口の固定テスト。

レポート生成側は `<title>` と `<style>` から始まる断片を返す。ページに
埋め込むならそれでよいが、**ファイルに書いてWindowsで開く用途**では
doctype が無いと互換モードになりレイアウトが変わる。BOMを付けるのと
同じ理由なので、書き出し口で完全な文書にする。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.cli import HTML_ENCODING, standalone_document

FRAGMENT = (
    '<title>テスト</title>\n'
    '<link rel="stylesheet" href="https://example.com/f.css">\n'
    '<style>body{color:red}</style>\n'
    '<h1>本文</h1>\n'
)


class TestStandaloneDocument(unittest.TestCase):
    def test_wraps_fragment(self):
        out = standalone_document(FRAGMENT)
        self.assertTrue(out.lstrip().startswith("<!doctype html>"))
        self.assertIn('<meta charset="utf-8">', out)
        self.assertIn('name="viewport"', out)
        self.assertTrue(out.rstrip().endswith("</html>"))

    def test_head_elements_go_in_head(self):
        out = standalone_document(FRAGMENT)
        head = out.split("</head>")[0]
        for tag in ("<title>テスト</title>", "stylesheet", "<style>"):
            self.assertIn(tag, head, f"{tag} が head に入っていない")
        self.assertNotIn("<h1>", head, "本文が head に混ざっている")

    def test_body_keeps_content(self):
        body = standalone_document(FRAGMENT).split("<body>")[1]
        self.assertIn("<h1>本文</h1>", body)

    def test_does_not_double_wrap(self):
        already = "<!doctype html>\n<html><body>x</body></html>"
        self.assertEqual(standalone_document(already), already)

    def test_doctype_detection_is_case_insensitive(self):
        already = "<!DOCTYPE html>\n<html><body>x</body></html>"
        self.assertEqual(standalone_document(already), already)

    def test_fragment_without_head_run(self):
        """head要素が無い断片でも壊さない。"""
        out = standalone_document("<p>だけ</p>")
        self.assertIn("<p>だけ</p>", out.split("<body>")[1])


class TestEncoding(unittest.TestCase):
    def test_html_is_bom_utf8(self):
        """CSV・テキスト出力と同じくBOM付き。Windowsで開く人のため。"""
        self.assertEqual(HTML_ENCODING, "utf-8-sig")

    def test_round_trip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.html"
            p.write_text(standalone_document(FRAGMENT), encoding=HTML_ENCODING)
            self.assertEqual(p.read_bytes()[:3], b"\xef\xbb\xbf")
            # utf-8-sig で読めばBOMは消える
            self.assertTrue(
                p.read_text(encoding="utf-8-sig").startswith("<!doctype html>"))


if __name__ == "__main__":
    unittest.main()
