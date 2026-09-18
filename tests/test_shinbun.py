"""新聞レイアウト（軸／相手／押さえ＋結果）が、買い目幅と結果に一致すること。"""
import csv
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import shinbun

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "2026-09-13_中央.json"


def config() -> dict:
    with open(CONFIG, encoding="utf-8-sig") as f:
        return json.load(f)


class TestGroupsMatchTheBoxWidths(unittest.TestCase):
    """欄の区切りは実測の買い目幅と同じ。飾りの線にしない。"""

    def test_groups_cover_the_marks_without_gaps(self):
        spans = [(lo, hi) for _, _, lo, hi in shinbun.GROUPS]
        self.assertEqual(spans[0][0], 1)
        self.assertEqual(spans[-1][1], shinbun.MARKS_SHOWN)
        for (_, hi), (lo, _) in zip(spans, spans[1:]):
            self.assertEqual(lo, hi + 1, "欄のあいだに隙間や重なりがある")

    def test_dotted_closes_the_four_horse_box(self):
        self.assertEqual(shinbun.DOTTED_AFTER, 4)
        self.assertEqual(shinbun._edge(4).strip(), "dot")

    def test_solid_closes_the_six_horse_box(self):
        self.assertEqual(shinbun.SOLID_AFTER, 6)
        self.assertEqual(shinbun._edge(6).strip(), "sol")

    def test_no_rule_anywhere_else(self):
        for i in (1, 2, 3, 5, 7, 8):
            self.assertEqual(shinbun._edge(i), "")


@unittest.skipUnless(CONFIG.exists(), "設定が無い")
class TestGroupHeaderRuleMatchesTheBody(unittest.TestCase):
    """群の見出しに引く罫は、本文と同じ列の右にしか出ないこと。

    押さえ(5-8)は赤線が群の内側(6の後ろ)に来るので、見出しに赤線を引くと
    位置がずれる。実際に一度ずれた。
    """

    def test_header_rule_positions(self):
        s = shinbun.build_sheet(config())
        head = re.search(r"<thead>(.*?)</thead>", s, re.S).group(1)
        rows = re.findall(r"<tr>(.*?)</tr>", head, re.S)
        grp = re.findall(r'<th class="(grp[^"]*)"', rows[0])
        # 相手馬は4で閉じるので点線、押さえは8で閉じるので線を引かない
        self.assertIn("dot", grp[1])
        self.assertNotIn("sol", grp[2])
        # 番号の見出し側は本文と同じ位置
        nums = re.findall(r'<th class="([^"]*)">(\d)</th>', rows[1])
        pos = {int(n): c for c, n in nums}
        self.assertEqual(pos[4], "dot")
        self.assertEqual(pos[6], "sol")


class TestResultsAreNotInvented(unittest.TestCase):
    """結果CSVが無いレースは空欄のまま。数字を作らない。"""

    def test_no_result_files_means_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "2026-01-01_中山09R_テスト_出走馬.csv"
            p.write_text("馬番\n1\n", encoding="utf-8-sig")
            chaku, scr, pay = shinbun.load_result(str(p))
            self.assertEqual((chaku, scr, pay), ({}, set(), {}))

    def test_prefix_comes_from_the_real_filename(self):
        """レース名を組み立て直さない（クラス名が付くと一致しなくなる）。"""
        got = shinbun.result_stem(
            "data/collected_jra/2026-09-13_中山09R_習志野特別(2勝クラス)_出走馬.csv")
        self.assertIsNotNone(got)
        folder, prefix = got
        self.assertEqual(prefix, "2026-09-13_中山09R_")

    def test_unparseable_path_returns_none(self):
        self.assertIsNone(shinbun.result_stem("でたらめ.csv"))


class TestScratchedAndMedals(unittest.TestCase):
    def _fixture(self, tmp, chaku_rows):
        d = Path(tmp)
        (d / "2026-01-01_中山09R_テスト_出走馬.csv").write_text(
            "馬番\n1\n", encoding="utf-8-sig")
        with open(d / "2026-01-01_中山09R_テスト_結果.csv", "w",
                  encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["着順", "馬番"])
            w.writerows(chaku_rows)
        return str(d / "2026-01-01_中山09R_テスト_出走馬.csv")

    def test_non_numeric_finish_is_scratched(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._fixture(tmp, [["1", "5"], ["除外", "7"], ["中止", "9"]])
            chaku, scr, _ = shinbun.load_result(p)
            self.assertEqual(chaku, {5: 1})
            self.assertEqual(scr, {7, 9})

    def test_medal_only_for_the_first_three(self):
        for pos, want in ((1, "🥇"), (2, "🥈"), (3, "🥉")):
            self.assertEqual(shinbun.MEDALS[pos], want)
        self.assertNotIn(4, shinbun.MEDALS)

    def test_cell_paints_and_puts_a_medal_behind_the_number(self):
        c = shinbun.Cell(rank=1, umaban=7, wakuban=3, mark="◎", chaku=2)
        td = shinbun._cell(c, 1)
        self.assertIn("p2", td)
        self.assertIn('<span class="medal">🥈</span>', td)
        self.assertLess(td.index("medal"), td.index('class="u'),
                        "メダルは馬番より前に出す（背面に敷くため）")

    def test_scratched_cell_is_grey_and_has_no_medal(self):
        c = shinbun.Cell(rank=1, umaban=7, wakuban=3, mark="◎", scratched=True)
        td = shinbun._cell(c, 1)
        self.assertIn("scr", td)
        self.assertNotIn("medal", td)


@unittest.skipUnless(CONFIG.exists(), "設定が無い")
class TestSheetMatchesTheResultFiles(unittest.TestCase):
    def test_colours_agree_with_the_result_csv(self):
        for r in config()["races"]:
            row = shinbun.race_row(r)
            chaku, _, _ = shinbun.load_result(r["entries"])
            if not chaku:
                continue
            for c in row.cells:
                want = chaku.get(c.umaban)
                self.assertEqual(c.chaku, want if want in (1, 2, 3) else None,
                                 f"{row.venue}{row.race_no} 馬番{c.umaban}")
            self.assertEqual(
                row.top3,
                [next((u for u, v in chaku.items() if v == p), None)
                 for p in (1, 2, 3)])

    def test_dead_heat_does_not_add_a_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "2026-01-01_中山09R_テスト_出走馬.csv").write_text(
                "馬番\n1\n", encoding="utf-8-sig")
            with open(d / "2026-01-01_中山09R_テスト_結果.csv", "w",
                      encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["着順", "馬番"])
                w.writerows([["1", "5"], ["1", "6"], ["3", "7"]])
            chaku, _, _ = shinbun.load_result(
                str(d / "2026-01-01_中山09R_テスト_出走馬.csv"))
            top3 = [next((u for u, v in chaku.items() if v == p), None)
                    for p in (1, 2, 3)]
            self.assertEqual(len(top3), 3)


@unittest.skipUnless(CONFIG.exists(), "設定が無い")
class TestAmebloSafe(unittest.TestCase):
    FORBIDDEN = ("html", "head", "body", "iframe", "object", "form", "input",
                 "embed", "textarea", "script", "meta", "button", "option",
                 "title", "svg")

    def test_no_forbidden_tags_by_default(self):
        s = shinbun.build_sheet(config()).lower()
        for t in self.FORBIDDEN:
            self.assertNotIn(f"<{t}", s, f"禁止タグ {t}")

    def test_title_only_when_asked(self):
        self.assertNotIn("<title", shinbun.build_sheet(config()))
        self.assertIn("<title>", shinbun.build_sheet(config(), title="x"))

    def test_one_day_fits_the_limit(self):
        self.assertLess(len(shinbun.build_sheet(config()).encode("utf-8")),
                        60_000)

    def test_css_is_scoped(self):
        css = re.search(r"<style>(.*?)</style>", shinbun.build_sheet(config()),
                        re.S).group(1)
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        for sel in re.findall(r"([^{}]+)\{", css):
            sel = sel.strip()
            if sel.startswith("@"):
                continue
            for part in sel.split(","):
                part = part.strip()
                if part:
                    self.assertTrue(part.startswith(".shinbun"),
                                    f"スコープ外の規則: {part}")


if __name__ == "__main__":
    unittest.main()
