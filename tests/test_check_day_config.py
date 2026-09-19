"""設定JSONの検算（開催区分ごと）を固定する。

2026-09-12の事故は2段あった:

1. **手書き設定で芝ダートが4レース逆だった**（距離は全部合っていた）。
   これが本体。「レインボーがダートで、ラジオ日本が芝」と取り違えていた
2. 生成に切り替えたあとも**馬場が4レースずれていた**（全部ダート）

馬場については、危ないのは**良↔非良をまたぐ取り違えだけ**で、稍重/重/不良の
取り違えは印の並び順を変えない（`keiba/marks.py` は良か否かしか見ない）。
この区別を緩めると、直す優先順位を取り違える。
"""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_day_config
from build_day_config import parse as parse_racedata
from check_day_config import axis, parse_list_page, severity


def parse_paren(paren: str) -> dict:
    """`build_day_config.parse` に括弧だけを食わせるための小さな包み。"""
    html = ('<div class="RaceData01">10:00発走 /<span> 芝1600m</span> '
            f'{paren} / 天候:曇<span class="Item03">/ 馬場:良</span></div>')
    return parse_racedata(html) or {}


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


class TestCourseSymbolImpliesTurf(unittest.TestCase):
    """コース記号(A/B/C/D)と内/外は芝にしか付かない。芝ダの裏づけになる。

    `芝(B)` の (B) は **Bコース（柵の位置）であって馬場ではない**。
    実データ: `芝1600m (右 外 B)` / `芝2000m (右 B)` / `ダ1200m (右)`
    """

    def test_芝には柵の記号が付く(self):
        for paren, kui in (("(右 外 B)", "B"), ("(右 B)", "B"), ("(右 A)", "A")):
            self.assertEqual(parse_paren(paren).get("kui"), kui, paren)

    def test_ダートには柵の記号が付かない(self):
        got = parse_paren("(右)")
        self.assertNotIn("kui", got)
        self.assertNotIn("inner_outer", got)
        self.assertEqual(got.get("turn"), "右")

    def test_内外も読む(self):
        self.assertEqual(parse_paren("(右 外 B)").get("inner_outer"), "外")
        self.assertEqual(parse_paren("(左 内 C)").get("inner_outer"), "内")


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
        self.baba, self.cond, self.extra = parse_list_page(self.path)

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

    def test_頭数と発走時刻もレースごとに読む(self):
        self.assertEqual(self.extra["202606040309"]["頭数"], 16)
        self.assertEqual(self.extra["202606040311"]["頭数"], 15)
        self.assertEqual(self.extra["202606040309"]["発走"], "15:00")
        self.assertEqual(self.extra["202606040311"]["発走"], "16:00")

    def test_隣のレースの頭数を拾わない(self):
        """**<li> の中だけを見る。**

        アドホックな正規表現で「レース名から600文字以内の N頭」を探すと、
        隣の <li> の頭数を拾う。実際に2026-09-19の検算でこれを踏み、
        16頭立てのレースに14頭と出た（8レース中5レースが誤判定）。
        """
        html = self.HTML.replace(
            '<li><a href="?race_id=202606040311">11R ラジオ日本賞 16:00 ダ1200m 15頭</a></li>',
            '<li><a href="?race_id=202606040310">10R 別のレース 15:30 ダ1800m 8頭</a></li>\n'
            '<li><a href="?race_id=202606040311">11R ラジオ日本賞 16:00 ダ1200m 15頭</a></li>')
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "jra_list_20260912.html"
            p.write_text(html, encoding="utf-8")
            _, _, extra = parse_list_page(p)
        # 間に8頭のレースを挟んでも、11Rは15頭のまま
        self.assertEqual(extra["202606040310"]["頭数"], 8)
        self.assertEqual(extra["202606040311"]["頭数"], 15)
        self.assertEqual(extra["202606040309"]["頭数"], 16)


if __name__ == "__main__":
    unittest.main()


class TestRaceIdsComeFromTheListPage(unittest.TestCase):
    """(競馬場, R) → race_id は**その日の一覧ページ**から作る（2026-09-13）。

    race_id に開催日は入っていない（年+場+開催回+日目+R）ので、年だけで
    絞って走査すると同じ場・同じRが開催日の数だけ当たり、後勝ちで
    **別の日のレース**が選ばれる。実際に2026-09-13の検算で、中山9R
    （芝1800m 重）の確定値として別の日の ダ1200m 不良 が出て、
    **設定は正しいのに8レース全部を「重大な不一致」**と誤報した。
    """

    LIST_HTML = """
    <li class="RaceList_DataItem">
      <a href="../race/result.html?race_id=202606040409">
      <span>芝1800m</span></a></li>
    <li class="RaceList_DataItem">
      <a href="../race/result.html?race_id=202609040411">
      <span>芝1800m</span></a></li>
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.cache = Path(self.tmp.name)
        (self.cache / "jra_list_20260913.html").write_text(
            self.LIST_HTML, encoding="utf-8")
        # 別の開催日の馬柱キャッシュ。**これに引きずられてはいけない**
        for rid in ("202606040109", "202606049909", "202609040111"):
            (self.cache / f"{rid}_past.html").write_text("", encoding="utf-8")
        (self.cache / "202606040409_past.html").write_text("", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_the_days_races(self):
        ids = check_day_config.race_ids_for(self.cache, "2026-09-13")
        self.assertEqual(ids.get(("中山", 9)), "202606040409")
        self.assertEqual(ids.get(("阪神", 11)), "202609040411")

    def test_other_days_do_not_win(self):
        """同じ場・同じRの別開催日が混ざっても選ばれない。"""
        ids = check_day_config.race_ids_for(self.cache, "2026-09-13")
        self.assertNotIn("202606049909", ids.values())
        self.assertNotIn("202606040109", ids.values())

    def test_no_list_page_means_empty(self):
        """一覧ページが無ければ空。照合できないことを一致と混同しない。"""
        self.assertEqual(
            check_day_config.race_ids_for(self.cache, "2026-09-14"), {})


class TestUnrunPagesAreNotConfirmed(unittest.TestCase):
    """発走前の結果ページを「確定値」として扱わないこと。

    結果ページのURLは発走前でも200を返し RaceData01 を持っている。着順
    テーブルだけが無い。ここを見落とすと、朝に取ったキャッシュの馬場を
    確定として、いま更新したばかりの設定のほうを不一致として責める
    （2026-09-13の12:00に実際に起きた）。
    """

    def _page(self, body: str) -> Path:
        d = Path(self._tmp.name)
        (d / "202606040409.html").write_text(body, encoding="utf-8")
        return d

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    DATA = '<div class="RaceData01">15:45発走 / 芝1800m (右 B) / 天候:曇 / 馬場:重</div>'

    def test_unrun_page_returns_none(self):
        cache = self._page(self.DATA)          # 着順テーブルが無い
        self.assertIsNone(check_day_config.result_condition(cache, "202606040409"))

    def test_finished_page_is_read(self):
        cache = self._page(self.DATA + '<table class="ResultTableWrap"></table>')
        self.assertEqual(check_day_config.result_condition(cache, "202606040409"),
                         ("芝1800m", "重"))

    def test_rank_cells_also_count_as_finished(self):
        cache = self._page(self.DATA + '<span class="Rank">1</span>')
        self.assertEqual(check_day_config.result_condition(cache, "202606040409"),
                         ("芝1800m", "重"))

    def test_missing_page(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(check_day_config.result_condition(Path(d), "202606040409"))
