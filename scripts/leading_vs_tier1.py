#!/usr/bin/env python3
"""2026年JRAリーディング上位30名と、一軍(延べ騎乗上位16人)判定を突き合わせる
（2026-09-20）。

リーディング表（`data/leading_2026_top30.csv`）は db-keiba.com から取得し、
手元コーパスの2026年勝利数の並び順と一致することを確認済み（CLAUDE.md
「2026年JRA騎手リーディング上位30名を調べ、一軍判定と突き合わせた」参照）。
WebFetchでの取得は2回とも実在しない表を返した（福永祐一1位・岩田望来104勝
など、引退済み騎手が混ざる作り話）ため、**手元データとの整合を必ず確認
してから使うこと**。

減量記号（☆▲△◇★）つきの表記ゆれは `endswith` で緩く束ねている
（厳密な同一性の保証ではない。誤って別人を束ねる可能性はゼロではないが、
今回の対象30名では目視で問題ないことを確認済み）。

    python3 scripts/leading_vs_tier1.py
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.racefiles import result_paths

LEADING_TOP30 = [
    ("岩田望", 1, 92), ("ルメー", 2, 91), ("松山", 3, 84), ("横山武", 4, 76),
    ("西村淳", 5, 71), ("坂井", 6, 69), ("川田", 7, 69), ("丹内", 8, 59),
    ("戸崎圭", 9, 58), ("荻野極", 10, 57), ("横山和", 11, 55), ("津村", 12, 48),
    ("武豊", 13, 48), ("斎藤", 14, 44), ("舟山", 15, 42), ("佐々木", 16, 40),
    ("鮫島駿", 17, 40), ("田山", 18, 38), ("高杉", 19, 38), ("北村友", 20, 35),
    ("吉村", 21, 34), ("三浦", 22, 34), ("菊沢", 23, 33), ("松若", 24, 33),
    ("小林美", 25, 32), ("団野", 26, 31), ("幸", 27, 30), ("西塚", 28, 27),
    ("田口", 29, 26), ("浜中", 30, 26),
]


def main() -> int:
    rides: Counter[str] = Counter()
    wins: Counter[str] = Counter()
    for f in result_paths("data/collected_jra", races="1-12"):
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            j = (r.get("騎手") or "").strip()
            c = r.get("着順") or ""
            if not j:
                continue
            rides[j] += 1
            if c.isdigit() and int(c) == 1:
                wins[j] += 1

    def merged(counter: Counter, base: str) -> int:
        # 素の名前 or 減量記号つき（先頭に1文字以上付く）で終わるものを束ねる
        return sum(v for k, v in counter.items()
                  if k == base or (k.endswith(base) and len(k) > len(base)))

    tier1_cut = sorted(rides.values(), reverse=True)[15]  # 上位16人目

    print(f"一軍の閾値（延べ騎乗上位16人目）: {tier1_cut:,}騎乗\n")
    print(f"{'順位':>4}{'騎手':<8}{'2026勝':>7}{'延べ(表記ゆれ統合)':>13}"
          f"{'勝率':>8}{'一軍':>5}")

    out = []
    for name, rank, w in LEADING_TOP30:
        n = merged(rides, name)
        win = merged(wins, name)
        t1 = n >= tier1_cut
        mark = "○" if t1 else ""
        if not t1:
            out.append((rank, name, win / n if n else 0))
        print(f"{rank:>4}{name:<8}{w:>7}{n:>13,}"
              f"{(win / n if n else 0):>8.1%}{mark:>5}")

    print(f"\n一軍から漏れている: {len(out)}/{len(LEADING_TOP30)}人")
    print("うち勝率が際立って高い（厳選型の疑い、目安20%以上）:")
    for rank, name, rate in out:
        if rate >= 0.20:
            print(f"  {rank}位 {name} 勝率{rate:.1%}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
