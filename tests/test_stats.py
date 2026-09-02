import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.stats import (
    MIN_RACES_FOR_CONCLUSION,
    aggregate,
    format_report,
    load_records,
    tally_by_mark,
    tally_by_ticket,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _sample_config(with_payouts: bool = True) -> dict:
    race = {
        "race_no": "11R", "name": "サンプルステークス", "grade": "OP",
        "post_time": "15:45", "surface": "ダ2000m", "kyori": 2000, "baba": "良",
        "entries": str(DATA / "サンプルステークス_出走馬.csv"),
        "history": str(DATA / "サンプルステークス_過去10年.csv"),
        "result": str(DATA / "サンプルステークス_結果.csv"),
    }
    if with_payouts:
        race["payouts"] = str(DATA / "サンプルステークス_配当.csv")
    return {"title": "テスト", "heading": "テスト開催", "races": [race]}


class TestStats(unittest.TestCase):
    """サンプルレース（着順・配当が全て揃っている）で集計値を検証する。"""

    def _records(self, with_payouts: bool = True):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                          encoding="utf-8") as f:
            json.dump(_sample_config(with_payouts), f, ensure_ascii=False)
            path = f.name
        records, skipped = load_records([path])
        Path(path).unlink()
        return records, skipped

    def test_loads_race_with_result(self):
        records, skipped = self._records()
        self.assertEqual(len(records), 1)
        self.assertEqual(skipped, [])

    def test_race_without_result_is_skipped(self):
        config = _sample_config()
        del config["races"][0]["result"]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                          encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False)
            path = f.name
        records, skipped = load_records([path])
        Path(path).unlink()
        self.assertEqual(records, [])
        self.assertEqual(len(skipped), 1)

    def test_mark_tally_matches_actual_finish(self):
        # サンプルレースの着順は 1着8番 / 2着1番 / 3着3番
        # 印は ◎1番・○8番・▲3番 なので、◎は2着、○は1着、▲は3着になる
        records, _ = self._records()
        by_mark = tally_by_mark(records)
        self.assertEqual(by_mark["◎"]["2着"], 1)
        self.assertEqual(by_mark["◎"]["複勝率"], 1.0)
        self.assertEqual(by_mark["○"]["1着"], 1)
        self.assertEqual(by_mark["▲"]["3着"], 1)

    def test_every_runner_is_counted_once(self):
        records, _ = self._records()
        by_mark = tally_by_mark(records)
        self.assertEqual(sum(r["出走"] for r in by_mark.values()), len(records[0].scores))

    def test_ticket_tally_recovery_rate(self):
        # サンプルレースはオッズ列が無いため標準型（◎軸の馬連6点）になる。
        # 確定着順は1着8番・2着1番なので、馬連1-8が的中して1,810円。
        # 投資600円 → 払戻1,810円 = 回収率302%
        records, _ = self._records()
        by_ticket = tally_by_ticket(records)
        self.assertEqual(by_ticket["馬連"]["的中"], 1)
        self.assertEqual(by_ticket["馬連"]["点数"], 6)
        total_invest = sum(r["投資"] for r in by_ticket.values())
        total_payout = sum(r["払戻"] for r in by_ticket.values())
        self.assertEqual(total_invest, 600)
        self.assertEqual(total_payout, 1810)
        self.assertAlmostEqual(total_payout / total_invest, 3.017, places=3)

    def test_recovery_rate_is_none_without_payout_data(self):
        # 配当CSVが無ければ、的中していても回収率は「不明」にする（0%にしない）
        records, _ = self._records(with_payouts=False)
        by_ticket = tally_by_ticket(records)
        self.assertIsNone(by_ticket["馬連"]["回収率"])
        self.assertEqual(by_ticket["馬連"]["的中"], 1)

    def test_report_warns_on_small_sample(self):
        records, skipped = self._records()
        report = format_report(aggregate(records), skipped)
        self.assertIn("母数", report)
        self.assertIn(str(MIN_RACES_FOR_CONCLUSION), report)

    def test_report_handles_zero_races(self):
        report = format_report(aggregate([]), ["どこかのレース（結果未入力）"])
        self.assertIn("結果が入力されたレースがありません", report)


if __name__ == "__main__":
    unittest.main()
