import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from keiba import rolemodel  # noqa: E402

CONFIG = ROOT / "config" / "2026-09-26_中央.json"
PUBLISHED = ROOT / "data" / "2026-09-26_中央_公表印.json"


class TestStakes(unittest.TestCase):
    def test_race_budget_and_units(self):
        self.assertEqual(rolemodel.RACE_BUDGET, 1600)
        self.assertEqual(len(rolemodel.STAKES), 6)          # 4頭BOX＝6点
        self.assertTrue(all(s % 100 == 0 for s in rolemodel.STAKES))
        self.assertEqual(list(rolemodel.STAKES), sorted(rolemodel.STAKES, reverse=True))

    def test_pairs_are_ordered_short_odds_first(self):
        odds = {1: 2.0, 2: 4.0, 3: 10.0, 4: 30.0}
        ordered = rolemodel.order_pairs([4, 3, 2, 1], odds, {})
        est = [o for _, o in ordered]
        self.assertEqual(est, sorted(est))
        self.assertEqual(ordered[0][0], (1, 2))
        self.assertEqual(len({p for p, _ in ordered}), 6)

    def test_missing_odds_fall_back_to_popularity_without_inventing_odds(self):
        ordered = rolemodel.order_pairs([1, 2, 3, 4], {1: 2.0},
                                        {1: 1, 2: 2, 3: 3, 4: 4})
        self.assertEqual(ordered[0][0], (1, 2))
        self.assertTrue(all(o is None for _, o in ordered))


@unittest.skipUnless(CONFIG.exists() and PUBLISHED.exists(), "9/26のデータが無い")
class TestDay(unittest.TestCase):
    def test_only_10_to_12_and_uses_published_top4(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
        pub = json.loads(PUBLISHED.read_text(encoding="utf-8"))
        plans = rolemodel.plan_day(config, pub)
        self.assertEqual({p.key for p in plans},
                         {"中山10R", "中山11R", "中山12R", "阪神10R", "阪神11R", "阪神12R"})
        for p in plans:
            self.assertEqual(p.top, pub[p.key][:4])
            self.assertEqual({x for t in p.tickets for x in t.pair}, set(p.top))
            self.assertEqual(p.total, rolemodel.RACE_BUDGET)
        self.assertIn("合計 6レース 9,600円", rolemodel.format_day(plans))


if __name__ == "__main__":
    unittest.main()
