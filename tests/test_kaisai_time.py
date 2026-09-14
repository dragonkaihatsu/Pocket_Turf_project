"""同開催内の相対（当日補正）が、母数の下限と情報漏れの線を守ること。"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import kaisai_time as kt


def run(name, d, r, raw, stem=None, chaku=1, ninki=1, umaban=1):
    return {"馬名": name, "日付": d, "R": r, "場": "中山",
            "stem": stem or f"{d}_中山{r:02d}R_x", "馬場種別": "芝",
            "距離": 1800, "馬場": "良", "生指数": raw,
            "馬場補正指数": raw, "着順": chaku, "人気": ninki, "馬番": umaban}


class TestDayOffsetNeedsEnoughRows(unittest.TestCase):
    def test_thin_day_gets_no_offset(self):
        d = date(2025, 5, 3)
        runs = [run(f"h{i}", d, 9, 1.0, umaban=i) for i in range(1, 6)]
        self.assertEqual(kt.day_offsets(runs), {})

    def test_needs_several_races_not_just_rows(self):
        d = date(2025, 5, 3)
        # 1レースに30頭（現実には無いが、レース数の下限を測るため）
        runs = [run(f"h{i}", d, 9, 1.0, stem="one", umaban=i) for i in range(1, 31)]
        self.assertEqual(kt.day_offsets(runs), {})

    def test_offset_is_the_mean_of_that_day_and_surface(self):
        d = date(2025, 5, 3)
        runs = []
        for r in (9, 10, 11):
            for i in range(1, 11):
                runs.append(run(f"h{r}_{i}", d, r, 2.0, umaban=i))
        # 同じ日の別の馬場種別（ダ）は混ざらない
        for i in range(1, 31):
            x = run(f"d{i}", d, 1 + i % 3, -5.0, umaban=i)
            x["馬場種別"] = "ダ"
            runs.append(x)
        off = kt.day_offsets(runs)
        self.assertAlmostEqual(off[(d, "中山", "芝")], 2.0)
        self.assertAlmostEqual(off[(d, "中山", "ダ")], -5.0)

    def test_apply_day_subtracts_the_offset(self):
        d = date(2025, 5, 3)
        runs = []
        for r in (9, 10, 11):
            for i in range(1, 11):
                runs.append(run(f"h{r}_{i}", d, r, 2.0, umaban=i))
        kt.apply_day(runs, kt.day_offsets(runs))
        self.assertAlmostEqual(runs[0]["当日補正指数"], 0.0)

    def test_missing_offset_leaves_none(self):
        d = date(2025, 5, 3)
        runs = [run("h1", d, 9, 1.0)]
        kt.apply_day(runs, {})
        self.assertIsNone(runs[0]["当日補正指数"])


class TestNoLeakFromTheTargetDay(unittest.TestCase):
    """対象レース当日の走りを指標に入れない（同着日・同日開催を含む）。"""

    def _horse(self, target_day):
        runs = []
        for k, dd in enumerate([date(2025, 1, 5), date(2025, 2, 5),
                                date(2025, 3, 5)]):
            runs.append(run("うま", dd, 5, 1.0 + k))
        runs.append(run("うま", target_day, 11, 99.0))   # 今走
        for r in runs:
            r["当日補正指数"] = r["生指数"]
        return runs

    def test_current_run_is_not_in_its_own_window(self):
        t = date(2025, 4, 5)
        rows = kt.build(self._horse(t), "9-12")
        self.assertEqual(len(rows), 1)
        # 99.0 が入れば平均は跳ね上がる。過去3走(1.0/2.0/3.0)だけで作られること
        self.assertLessEqual(rows[0]["馬場_近走"], 3.0)
        self.assertLessEqual(rows[0]["当日_近走"], 3.0)

    def test_window_is_365_days(self):
        runs = [run("うま", date(2023, 1, 1), 5, 9.0),
                run("うま", date(2023, 2, 1), 5, 9.0),
                run("うま", date(2023, 3, 1), 5, 9.0),
                run("うま", date(2025, 4, 5), 11, 0.0)]
        for r in runs:
            r["当日補正指数"] = r["生指数"]
        self.assertEqual(kt.build(runs, "9-12"), [])

    def test_needs_min_runs_in_window(self):
        runs = [run("うま", date(2025, 1, 5), 5, 1.0),
                run("うま", date(2025, 2, 5), 5, 2.0),
                run("うま", date(2025, 4, 5), 11, 0.0)]
        for r in runs:
            r["当日補正指数"] = r["生指数"]
        self.assertEqual(kt.build(runs, "9-12"), [])


if __name__ == "__main__":
    unittest.main()
