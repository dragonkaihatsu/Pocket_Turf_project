#!/usr/bin/env python3
"""ルメールが一軍（延べ騎乗上位16人）から漏れる理由を調べる（2026-09-20）。

「短期免許だから」という前回の説明は誤りだった（本人の指摘：永住の長期
免許）。ここでは**実際にどういう騎乗パターンが延べ騎乗数を押し下げて
いるか**を、収集済みコーパス（1-12R・2024〜2026）から直接測る。

    python3 scripts/jockey_selectivity.py
"""
from __future__ import annotations

import csv
import datetime
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.racefiles import VENUE_NO_RE, result_paths

TOP16 = ["丹内", "松山", "横山武", "鮫島駿", "戸崎圭", "佐々木", "岩田望",
         "団野", "幸", "菊沢", "西村淳", "坂井", "木幡巧", "津村",
         "菅原明", "横山和"]
FOCUS = "ルメー"


def main() -> int:
    targets = TOP16 + [FOCUS]

    rides = Counter()
    wins = Counter()
    by_days = defaultdict(set)
    by_raceno = defaultdict(Counter)
    all_days: set[str] = set()

    for f in result_paths("data/collected_jra", races="1-12"):
        stem = Path(f).name
        date = stem[:10]
        all_days.add(date)
        m = VENUE_NO_RE.search(stem)
        raceno = int(m.group(2)) if m else None
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            j = (r.get("騎手") or "").strip()
            c = r.get("着順") or ""
            if j not in targets:
                continue
            rides[j] += 1
            if c.isdigit() and int(c) == 1:
                wins[j] += 1
            by_days[j].add(date)
            if raceno:
                by_raceno[j][raceno] += 1

    print(f"収集済み全体の開催日数: {len(all_days)}\n")

    print("■ 出走日数（開催日のうち何日騎乗したか）")
    print(f"{'騎手':<8}{'出走日数':>8}{'出走率':>8}")
    for j in sorted(targets, key=lambda x: -len(by_days[x])):
        d = len(by_days[j])
        mark = " ★" if j == FOCUS else ""
        print(f"{j:<8}{d:>8}{d / len(all_days):>8.1%}{mark}")

    print("\n■ レース番号帯の分布（1-4Rは下級条件が多い・9-12Rは重賞/上位条件が多い）")
    print(f"{'騎手':<8}{'1-4R':>7}{'5-8R':>7}{'9-12R':>7}{'延べ':>7}")
    for j in targets:
        c = by_raceno[j]
        total = sum(c.values())
        early = sum(v for k, v in c.items() if k <= 4)
        mid = sum(v for k, v in c.items() if 5 <= k <= 8)
        late = sum(v for k, v in c.items() if k >= 9)
        mark = " ★" if j == FOCUS else ""
        print(f"{j:<8}{early / total:>6.1%} {mid / total:>6.1%} "
              f"{late / total:>6.1%} {total:>7,}{mark}")

    print("\n■ 勝率（選択的な騎乗になっているかの裏付け）")
    print(f"{'騎手':<8}{'延べ':>6}{'勝利':>6}{'勝率':>8}")
    for j in sorted(targets, key=lambda x: -wins[x] / rides[x]):
        mark = " ★" if j == FOCUS else ""
        print(f"{j:<8}{rides[j]:>6,}{wins[j]:>6}{wins[j] / rides[j]:>8.1%}{mark}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
