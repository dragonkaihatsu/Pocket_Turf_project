"""設定JSONの検算（開催区分ごと）を固定する。

2026-09-12に「距離は全部正しく、馬場が4レース違い、全部ダートだった」という
事故があった。危ないのは**良↔非良をまたぐ取り違えだけ**で、稍重/重/不良の
取り違えは印の並び順を変えない（`keiba/marks.py` は良か否かしか見ない）。
この区別を緩めると、直す優先順位を取り違える。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_day_config import axis, parse_list_page, severity


class TestAxis(unittest.TestCase):
    def test_良だけが良馬場スコア(self):
        self.assertEqual(axis("良"), "良馬場スコア")
        for b in ("稍重", "重", "不良"):
            self.assertEqual(axis(b), "重馬場スコア", b)


class TestSeverity(unittest.TestCase):
    def test_一致ならOK(self):
        self.assertEqual(severity("芝1600m", "良", "芝1600m", "良"), "OK")

    def test_芝ダの取り違えは重大(self):
        v = severity("ダ1200m", "重", "芝1200m", "重")
        self.assertTrue(v.startswith("重大"))
        self.assertIn("芝ダ", v)

    def test_距離の取り違えは重大(self):
        self.assertTrue(severity("芝1600m", "良", "芝2000m", "良").startswith("重大"))

    def test_良と非良をまたぐ馬場は重大(self):
        # 2026-09-12 阪神10R・12R: 稍重 と書いたが確定は良
        v = severity("ダ1800m", "稍重", "ダ1800m", "良")
        self.assertTrue(v.startswith("重大"))
        self.assertIn("並び順", v)
        # 逆向きも同じ
        self.assertTrue(severity("芝2000m", "良", "芝2000m", "重").startswith("重大"))

    def test_非良どうしの取り違えは軽微(self):
        # 2026-09-12 中山11R・12R: 不良 と書いたが確定は重。印は動かなかった
        for a, b in (("不良", "重"), ("重", "稍重"), ("稍重", "不良")):
            v = severity("ダ1200m", a, "ダ1200m", b)
            self.assertTrue(v.startswith("軽微"), f"{a}→{b}: {v}")


class TestParseListPage(unittest.TestCase):
    """一覧ページは開催区分（競馬場×芝ダ）ごとの馬場をそのまま持っている。"""

    HTML = """
    <dt class="RaceList_DataHeader">
    <p class="RaceList_DataTitle"><small>4回</small> 中山 <small>3日目</small></p>
    <span class="Weather">天気：</span>
    <span class="Shiba">芝(B)：重</span><span class="Da">ダ：不</span>
    </dt>
    <dd><ul>
    <li><a href="?race_id=202606040309">9R 御宿特別 15:00 芝1600m 16頭</a></li>
    <li><a href="?race_id=202606040311">11R ラジオ日本賞 16:00 ダ1200m 15頭</a></li>
    </ul></dd>
    <dt class="RaceList_DataHeader">
    <p class="RaceList_DataTitle"><small>4回</small> 阪神 <small>3日目</small></p>
    <span class="Shiba">芝(A)：稍</span><span class="Da">ダ：重</span>
    </dt>
    """

    def setUp(self):
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "jra_list_20260912.html"
        self.path.write_text(self.HTML, encoding="utf-8")
        self.baba, self.cond = parse_list_page(self.path)

    def tearDown(self):
        self.dir.cleanup()

    def test_開催区分ごとに馬場を読む(self):
        self.assertEqual(self.baba[("中山", "芝")], "重")
        self.assertEqual(self.baba[("中山", "ダ")], "不良")   # 「不」を展開する
        self.assertEqual(self.baba[("阪神", "芝")], "稍重")   # 「稍」を展開する
        self.assertEqual(self.baba[("阪神", "ダ")], "重")

    def test_同じ競馬場でも芝とダで別の値になる(self):
        self.assertNotEqual(self.baba[("中山", "芝")], self.baba[("中山", "ダ")])

    def test_レースごとの芝ダ距離を読む(self):
        self.assertEqual(self.cond["202606040309"], "芝1600m")
        self.assertEqual(self.cond["202606040311"], "ダ1200m")


if __name__ == "__main__":
    unittest.main()
