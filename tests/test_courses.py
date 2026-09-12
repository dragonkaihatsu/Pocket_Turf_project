"""競馬場の特性表と、特性で束ねた戦績のテスト。

CLAUDE.mdが「札幌・函館は中央」をテストで固定しているのと同じ趣旨で、
**分類そのものを固定する**。特性の分類を間違えると、もっともらしく
間違った予想が静かに出続けるため（プロファイル取り違えと同じ失敗の形）。
"""
import unittest

from keiba.courses import (COURSES, chokusen_band, same_trait_courses,
                           shares_trait, traits)
from keiba.horsedb import summarize, summarize_trait


class TestCourseTraits(unittest.TestCase):
    def test_ten_jra_courses(self):
        self.assertEqual(len(COURSES), 10)

    def test_komawari_group(self):
        """小回りは中山・福島・小倉・札幌・函館の5場。"""
        self.assertEqual(set(same_trait_courses("中山", "小回り")),
                         {"中山", "福島", "小倉", "札幌", "函館"})

    def test_yoshiba_is_only_hokkaido(self):
        """洋芝は札幌・函館だけ。"""
        self.assertEqual(set(same_trait_courses("札幌", "芝種", "芝")),
                         {"札幌", "函館"})

    def test_kyoto_is_not_a_saka_course(self):
        """京都をゴール前の急坂（中山・阪神・中京）と同じ扱いにしない。

        京都の特徴は3-4角の下り坂で、直線は平坦。ゴール前の急坂とは
        逆の性質なので、同じ「坂適性」で束ねてはいけない。
        """
        self.assertEqual(traits("京都")["坂"], "平坦")
        self.assertFalse(shares_trait("京都", "中山", "坂"))
        self.assertEqual(set(same_trait_courses("中山", "坂")),
                         {"中山", "阪神", "中京"})

    def test_tokyo_is_its_own_saka_group(self):
        """東京は緩い上りで、急坂でも平坦でもない（束ねる相手がいない）。"""
        self.assertEqual(same_trait_courses("東京", "坂"), ["東京"])

    def test_nakayama_straight_not_grouped_with_chukyo(self):
        """中山310mを中京412.5mと同じ直線帯に入れない（100m以上違う）。"""
        self.assertNotEqual(chokusen_band("中山"), chokusen_band("中京"))
        self.assertEqual(chokusen_band("新潟"), "長い(560m~)")

    def test_surface_removes_shiba_axis_on_dirt(self):
        """洋芝はダートに存在しない概念なので、ダートでは軸から外す。"""
        self.assertIn("芝種", traits("札幌", "芝"))
        self.assertNotIn("芝種", traits("札幌", "ダート"))

    def test_unknown_course_is_empty(self):
        """大井など地方の場名を渡しても、勝手に分類しない。"""
        self.assertEqual(traits("大井"), {})
        self.assertEqual(same_trait_courses("大井", "小回り"), [])


class TestSummarizeTrait(unittest.TestCase):
    ROWS = [
        {"場": "中山", "着順": "3", "距離": "1800"},
        {"場": "福島", "着順": "1", "距離": "1800"},
        {"場": "東京", "着順": "9", "距離": "1800"},
        {"場": "函館", "着順": "2", "距離": "1200"},
    ]

    def test_pooling_increases_sample(self):
        """同じデータで、場一致1走 → 小回り束ね3走に増える。"""
        self.assertEqual(summarize(self.ROWS, ba="中山")["着順あり"], 1)
        self.assertEqual(summarize_trait(self.ROWS, "中山", "小回り")["着順あり"], 3)

    def test_shows_which_courses_were_pooled(self):
        """どの場を束ねた数字なのかを必ず返す（根拠の明示）。"""
        t = summarize_trait(self.ROWS, "中山", "小回り")
        # 並び順は実装の都合（文字コード順）なので集合で比べる
        self.assertEqual(set(t["対象場"]),
                         {"中山", "福島", "小倉", "札幌", "函館"})
        self.assertEqual(t["値"], "小回り")

    def test_wide_course_excludes_komawari_runs(self):
        """東京（広い）の予想では、小回りの3走は入らない。"""
        t = summarize_trait(self.ROWS, "東京", "小回り")
        self.assertEqual(t["着順あり"], 1)
        self.assertEqual(t["平均着順"], 9.0)


if __name__ == "__main__":
    unittest.main()
