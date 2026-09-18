"""血統×コース特性の測り方を固定する。

結論（測った結果）は「独立検証で判別力ゼロ」だが、**その結論を出せる
測り方であること**をここで固定する。とくに後知恵の排除（得意判定を
train 年だけから作る）が崩れると、in-sample のリフトが必ず出て
「効いている」と誤読する。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from keiba.courses import traits
from ketto_course import band_of, measure


def rec(sire, venue, surface, band, fukusho, year):
    return {"種牡馬": sire, "場": venue, "芝ダ": surface, "帯": band,
            "複": fukusho, "年": year, "特性": traits(venue, surface)}


class TestBand(unittest.TestCase):
    def test_bands_cover_and_do_not_overlap(self):
        self.assertEqual(band_of(1), "1-3番人気")
        self.assertEqual(band_of(3), "1-3番人気")
        self.assertEqual(band_of(4), "4-5番人気")
        self.assertEqual(band_of(5), "4-5番人気")
        self.assertEqual(band_of(6), "6-9番人気")
        self.assertEqual(band_of(9), "6-9番人気")
        self.assertEqual(band_of(10), "10番人気以下")
        self.assertIsNone(band_of(None))


class TestTraitAxesDependOnSurface(unittest.TestCase):
    def test_dirt_has_no_turf_kind_axis(self):
        """洋芝適性はダートに存在しない概念。

        ダートで芝種の軸を使うと、札幌・函館だけが無意味に別扱いされる。
        """
        self.assertIn("芝種", traits("札幌", "芝"))
        self.assertNotIn("芝種", traits("札幌", "ダ"))

    def test_kyoto_is_not_grouped_with_nakayama_on_slope(self):
        """京都の直線は平坦。中山・阪神のゴール前急坂とは逆の性質。"""
        self.assertEqual(traits("京都", "芝")["坂"], "平坦")
        self.assertEqual(traits("中山", "芝")["坂"], "急坂")


class TestNoHindsight(unittest.TestCase):
    """得意判定は train 年だけから作る。"""

    def _rows(self):
        rows = []
        # 2025年: この種牡馬は小回りで走り、広いコースで走らない
        for _ in range(40):
            rows.append(rec("テスト種牡馬", "中山", "芝", "1-3番人気", True, "2025"))
            rows.append(rec("テスト種牡馬", "東京", "芝", "1-3番人気", False, "2025"))
        # 2026年: **逆になる**（小回りで走らず、広いコースで走る）
        for _ in range(40):
            rows.append(rec("テスト種牡馬", "中山", "芝", "1-3番人気", False, "2026"))
            rows.append(rec("テスト種牡馬", "東京", "芝", "1-3番人気", True, "2026"))
        return rows

    def test_preference_comes_from_train_year_only(self):
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            measure(self._rows(), "小回り", 30, "2025", "2026")
        out = buf.getvalue()

        # 2025年の「得意＝小回り」を2026年に当てると外れる側になる。
        # train 年を混ぜて判定していれば、ここが高い率で出てしまう
        lines = [l for l in out.splitlines() if "得意な特性で走る" in l]
        self.assertTrue(lines)
        self.assertIn("0.0%", lines[0])   # 2026の小回りは複勝0件

    def test_sires_measurable_on_one_side_only_are_skipped(self):
        import contextlib
        import io

        rows = self._rows()
        # 片側しか走っていない種牡馬を足しても、判定対象に入らない
        rows += [rec("片側だけ", "中山", "芝", "1-3番人気", True, "2025")
                 for _ in range(100)]
        rows += [rec("片側だけ", "中山", "芝", "1-3番人気", True, "2026")
                 for _ in range(100)]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            measure(rows, "小回り", 30, "2025", "2026")
        self.assertIn("判定できた種牡馬: 1頭", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
