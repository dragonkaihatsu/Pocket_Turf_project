"""コンピ指数風の一覧表が、紙面の構造と貼り先の制約を守ること。"""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import kompi
from keiba.marks import assign_marks
from keiba.models import load_horses
from keiba.scoring import score_race

ROOT = Path(__file__).resolve().parent.parent
ENTRIES = (ROOT / "data" / "collected_jra"
           / "2026-09-13_中山11R_セントライト記念(G2)_出走馬.csv")
CAL = ROOT / "data" / "profiles" / "jra" / "calibration.json"


def race(**over) -> dict:
    d = {"venue": "中山", "race_no": "11R", "name": "セントライト記念(G2)",
         "entries": str(ENTRIES), "kyori": 2200, "surface": "芝2200m",
         "baba": "稍重", "post_time": "15:45"}
    d.update(over)
    return d


@unittest.skipUnless(ENTRIES.exists(), "出走馬CSVが無い")
class TestOrderMatchesMarks(unittest.TestCase):
    """列の並びは `assign_marks` と同じ軸で決まること（良/重で軸が変わる）。"""

    def _ranked(self, baba):
        horses = load_horses(str(ENTRIES))
        scores = score_race(horses, None, kyori=2200, venue="中山")
        key = ((lambda s: s.total_yoi) if baba == "良"
               else (lambda s: s.total_omoi))
        return [s.horse.umaban
                for s in sorted(scores, key=key, reverse=True)]

    def test_baba_good_uses_good_score(self):
        g = kompi.race_grid(race(baba="良"))
        self.assertEqual([c.umaban for c in g.cells], self._ranked("良"))

    def test_baba_soft_uses_heavy_score(self):
        g = kompi.race_grid(race(baba="稍重"))
        self.assertEqual([c.umaban for c in g.cells], self._ranked("稍重"))

    def test_marks_land_on_the_first_three_columns(self):
        g = kompi.race_grid(race())
        self.assertEqual([c.mark for c in g.cells[:3]], ["◎", "○", "▲"])

    def test_every_horse_gets_a_column(self):
        g = kompi.race_grid(race())
        self.assertEqual(g.n, len(load_horses(str(ENTRIES))))
        self.assertEqual([c.rank for c in g.cells], list(range(1, g.n + 1)))


@unittest.skipUnless(ENTRIES.exists(), "出走馬CSVが無い")
class TestSheetStructure(unittest.TestCase):
    def sheet(self, **kw):
        cfg = {"heading": "2026-09-13 中央", "races": [race()]}
        cal = kompi.load_calibration(CAL) if CAL.exists() else None
        return kompi.build_sheet(cfg, cal, **kw)

    def test_header_body_and_footer_have_the_same_column_count(self):
        s = self.sheet()
        head = len(re.findall(r"<th[ >]", s)) - 1          # corner を除く
        for row in re.findall(r"<tr>(.*?)</tr>", s, re.S):
            n = len(re.findall(r"<td[ >]", row))
            if n:
                self.assertEqual(n - 1, head, row[:120])   # 行ラベルを除く

    def test_group_rule_every_five_columns(self):
        """朱の縦罫は5列ごと。最後の列には引かない（紙面と同じ）。"""
        g = kompi.race_grid(race())
        edges = {i for i in range(kompi.GROUP, g.n, kompi.GROUP)}
        self.assertIn(5, edges)
        self.assertNotIn(g.n, edges)

    def test_ranks_nine_and_beyond_share_the_bucket_value(self):
        """9位以下は一括値。列ごとの数字を作らない（CLAUDE.mdの方針）。"""
        if not CAL.exists():
            self.skipTest("実測表が無い")
        s = self.sheet()
        cal = json.loads(CAL.read_text(encoding="utf-8-sig"))
        bucket = round(cal["順位別"]["9位以下"]["勝率"] * 100)
        self.assertIn(f'class="bucket ', s)
        self.assertIn(f">{bucket}<", s)

    def test_no_footer_without_measurements(self):
        """実測表が無いなら最下段2行も、それを説明する凡例も出さない。"""
        s = kompi.build_sheet({"heading": "x", "races": [race()]}, None)
        self.assertNotIn("<tfoot>", s)
        self.assertNotIn('<td class="rate-lbl"', s)   # CSSの規則は常に載る
        self.assertNotIn("最下段2行", s)

    def test_footer_appears_only_with_measurements(self):
        if not CAL.exists():
            self.skipTest("実測表が無い")
        self.assertIn("<tfoot>", self.sheet())

    def test_legend_is_only_the_fixed_notice(self):
        """凡例は印の意味と免責だけ。読み方の解説は置かない（説明しすぎない）。"""
        from keiba.notice import MARK_NOTICE
        legend = re.search(r'<p class="legend">(.*?)</p>', self.sheet(), re.S)
        self.assertEqual(legend.group(1), MARK_NOTICE)
        self.assertNotIn("読み方", self.sheet())

    def test_hensachi_metric_changes_the_label(self):
        """見出しの角は列の軸を名乗る（本文の他の「スコア」は対象外）。"""
        corner = re.search(r'<th class="corner[^>]*>(.*?)</th>',
                           self.sheet(metric="hensachi"), re.S).group(1)
        self.assertIn("偏差値順位", corner)
        self.assertNotIn("スコア", corner)


@unittest.skipUnless(ENTRIES.exists(), "出走馬CSVが無い")
class TestAmebloSafe(unittest.TestCase):
    """既定の出力はアメブロにそのまま貼れること（CLAUDE.mdの禁止タグ・上限）。"""

    FORBIDDEN = ("html", "head", "body", "iframe", "object", "form", "input",
                 "embed", "textarea", "script", "meta", "button", "option",
                 "title", "svg")

    def sheet(self, **kw):
        cfg = {"heading": "2026-09-13 中央", "races": [race()]}
        return kompi.build_sheet(cfg, kompi.load_calibration(CAL), **kw)

    def test_no_forbidden_tags_by_default(self):
        s = self.sheet().lower()
        for t in self.FORBIDDEN:
            self.assertNotIn(f"<{t}", s, f"禁止タグ {t} が出ている")

    def test_title_only_when_asked(self):
        self.assertNotIn("<title", self.sheet())
        self.assertIn("<title>", self.sheet(title="x"))

    def test_css_is_scoped_so_it_cannot_leak_into_the_blog(self):
        """`.kompi` の外に効く規則を書かない（* や body の裸の指定を禁止）。"""
        css = re.search(r"<style>(.*?)</style>", self.sheet(), re.S).group(1)
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        # `}` をまたがない形で拾う（またぐと "}\n.kompi *" のような偽の
        # セレクタが出て、正しいCSSを落としてしまう）
        for sel in re.findall(r"([^{}]+)\{", css):
            sel = sel.strip()
            if sel.startswith("@"):        # @media 自体はセレクタではない
                continue
            for part in sel.split(","):
                part = part.strip()
                if part:
                    self.assertTrue(part.startswith(".kompi"),
                                    f"スコープ外の規則: {part}")

    def test_one_day_fits_the_ameblo_limit(self):
        cfg = {"heading": "2026-09-13 中央", "races": [race()] * 8}
        s = kompi.build_sheet(cfg, kompi.load_calibration(CAL))
        self.assertLess(len(s.encode("utf-8")), 60_000)


class TestKyakushitsu(unittest.TestCase):
    """脚質は1文字だけ入れる（本人の指示・2026-09-14「脚質は要ります」）。"""

    def test_one_character(self):
        for src, want in (("先行", "先"), ("逃げ", "逃"), ("差し", "差"),
                          ("追込", "追")):
            self.assertEqual(kompi._kyaku(src), want)

    def test_unreadable_value_is_left_blank(self):
        """それらしい文字を作らない（数字を作らない方針と同じ）。"""
        for src in ("", None, "—", "不明", "自在"):
            self.assertEqual(kompi._kyaku(src), "")

    def test_cell_shows_mark_and_kyakushitsu_together(self):
        c = kompi.Cell(rank=1, umaban=7, wakuban=4, value=60.0,
                       mark="◎", kyaku="先")
        td = kompi._cell(c, False)
        self.assertIn("<span class=\"mk\">◎<i>先</i></span>", td)

    def test_cell_without_kyakushitsu_has_no_empty_tag(self):
        c = kompi.Cell(rank=9, umaban=7, wakuban=4, value=40.0, mark="")
        self.assertNotIn("<i>", kompi._cell(c, False))


@unittest.skipUnless(ENTRIES.exists(), "出走馬CSVが無い")
class TestKyakushitsuInGrid(unittest.TestCase):
    def test_grid_carries_the_kyakushitsu_of_each_horse(self):
        g = kompi.race_grid(race())
        horses = {h.umaban: h.kyakushitsu for h in load_horses(str(ENTRIES))}
        for c in g.cells:
            self.assertEqual(c.kyaku, kompi._kyaku(horses[c.umaban]))
        self.assertTrue(any(c.kyaku for c in g.cells))


class TestWakuColour(unittest.TestCase):
    def test_every_frame_number_has_a_class(self):
        for w in range(1, 9):
            self.assertIn(f".kompi .w{w}{{", kompi.CSS)
        self.assertIn(".kompi .w0{", kompi.CSS)   # 枠番が読めないとき

    def test_unknown_frame_falls_back_without_raising(self):
        c = kompi.Cell(rank=1, umaban=1, wakuban=99, value=50.0, mark="")
        self.assertIn('class="u w0"', kompi._cell(c, False))


if __name__ == "__main__":
    unittest.main()
