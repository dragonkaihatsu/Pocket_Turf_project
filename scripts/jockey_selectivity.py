#!/usr/bin/env python3
"""騎手個別の選択的騎乗パターンを一覧で見る（2026-09-20）。

ルメールが一軍（延べ騎乗上位16人）から漏れる理由が「出走日数を絞り、
朝の下級条件を避け、勝てる馬に集中する」選択的騎乗だと分かった
（前回の検証）。**この形はルメール固有か、他の騎手にも共通するか**を
確かめるため、母数十分な全騎手に広げて個別に見る。

    python3 scripts/jockey_selectivity.py --min-rides 300
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.racefiles import VENUE_NO_RE, result_paths

TIER1_TOPN = 16  # keiba/scoring.py の JOCKEY_TIER1_TOPN と揃える
# 一般的に知られる有力騎手（若手・外国人・ベテランを横断して並べて見る）
NOTABLE = ["ルメー", "Mデム", "川田", "武豊", "横山典", "岩田康", "池添"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="1-12")
    ap.add_argument("--min-rides", type=int, default=300,
                    help="この延べ騎乗数以上の騎手だけを個別集計する")
    a = ap.parse_args()

    rides = Counter()
    wins = Counter()
    by_days = defaultdict(set)
    by_raceno = defaultdict(Counter)
    all_days: set[str] = set()

    for f in result_paths(a.dir, races=a.races):
        stem = Path(f).name
        date = stem[:10]
        all_days.add(date)
        m = VENUE_NO_RE.search(stem)
        raceno = int(m.group(2)) if m else None
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            j = (r.get("騎手") or "").strip()
            c = r.get("着順") or ""
            if not j:
                continue
            rides[j] += 1
            if c.isdigit() and int(c) == 1:
                wins[j] += 1
            by_days[j].add(date)
            if raceno:
                by_raceno[j][raceno] += 1

    targets = [j for j, n in rides.items() if n >= a.min_rides]
    tier1_cut = sorted(rides.values(), reverse=True)[TIER1_TOPN - 1]
    tier1 = {j for j in targets if rides[j] >= tier1_cut}

    print(f"収集済み全体の開催日数: {len(all_days)}　"
          f"延べ{a.min_rides}騎乗以上の騎手: {len(targets)}人　"
          f"（一軍=延べ騎乗上位{TIER1_TOPN}人・閾値{tier1_cut:,}騎乗）\n")

    print(f"■ 個別の騎手別（延べ{a.min_rides}騎乗以上・勝率順）")
    print(f"{'騎手':<8}{'延べ':>6}{'勝率':>8}{'出走率':>8}"
          f"{'1-4R':>7}{'9-12R':>7}{'一軍':>5}")
    ranked = sorted(targets, key=lambda x: -wins[x] / rides[x])
    for j in ranked:
        n = rides[j]
        w = wins[j]
        d = len(by_days[j])
        c = by_raceno[j]
        tot = sum(c.values())
        early = sum(v for k, v in c.items() if k <= 4) / tot
        late = sum(v for k, v in c.items() if k >= 9) / tot
        mark = " ★" if j in NOTABLE else ""
        t1 = "○" if j in tier1 else ""
        print(f"{j:<8}{n:>6,}{w / n:>8.1%}{d / len(all_days):>8.1%}"
              f"{early:>7.1%}{late:>7.1%}{t1:>5}{mark}")

    print(f"\n■ 有名どころだけ抜き出す")
    print(f"{'騎手':<8}{'延べ':>6}{'勝率':>8}{'出走率':>8}"
          f"{'1-4R':>7}{'9-12R':>7}{'一軍':>5}")
    for j in NOTABLE:
        if j not in rides:
            print(f"{j:<8}  対象外（母数不足 or 未収集）")
            continue
        n = rides[j]
        w = wins[j]
        d = len(by_days[j])
        c = by_raceno[j]
        tot = sum(c.values())
        early = sum(v for k, v in c.items() if k <= 4) / tot
        late = sum(v for k, v in c.items() if k >= 9) / tot
        t1 = "○" if j in tier1 else ""
        print(f"{j:<8}{n:>6,}{w / n:>8.1%}{d / len(all_days):>8.1%}"
              f"{early:>7.1%}{late:>7.1%}{t1:>5}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
