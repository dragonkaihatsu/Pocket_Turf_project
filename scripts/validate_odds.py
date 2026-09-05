#!/usr/bin/env python3
"""単勝オッズから推定した馬連・ワイドのオッズを、実際の確定配当と比べる。

合成オッズの設計は推定オッズの上に成り立つので、まずこの推定が
どれくらい当たるのかを知らないと、その先の数字はすべて絵空事になる。

比較できるのは的中した組だけ（外れた組の配当は公表されない）。

    python3 scripts/validate_odds.py --races 9-12
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest import parse_races, race_number
from keiba.models import load_horses
from keiba.oddsmodel import estimate_umaren, estimate_wide


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected")
    ap.add_argument("--races", default="9-12")
    args = ap.parse_args()

    wanted = parse_races(args.races)
    d = Path(args.dir)
    rows_umaren, rows_wide = [], []

    for res in sorted(d.glob("*_結果.csv")):
        stem = res.name.replace("_結果.csv", "")
        rn = race_number(stem)
        if rn is None or rn not in wanted:
            continue
        ent = d / f"{stem}_出走馬.csv"
        pay = d / f"{stem}_配当.csv"
        if not (ent.exists() and pay.exists()):
            continue
        horses = load_horses(ent)
        odds = {h.umaban: h.tansho_odds for h in horses if h.tansho_odds}
        if len(odds) < 5:
            continue
        for p in csv.DictReader(open(pay, encoding="utf-8-sig")):
            try:
                combo = [int(x) for x in p["組み合わせ"].split("-")]
                actual = int(p["配当"]) / 100.0
            except ValueError:
                continue
            if len(combo) != 2:
                continue
            a, b = combo
            if p["券種"] == "馬連":
                est = estimate_umaren(odds, a, b)
                if est:
                    rows_umaren.append((est, actual))
            elif p["券種"] == "ワイド":
                est = estimate_wide(odds, a, b)
                if est:
                    rows_wide.append((est, actual))

    for label, rows in (("馬連", rows_umaren), ("ワイド", rows_wide)):
        if not rows:
            print(f"{label}: 比較できるデータがありません")
            continue
        ratios = [e / a for e, a in rows]
        ratios.sort()
        n = len(ratios)
        within = lambda lo, hi: sum(1 for r in ratios if lo <= r <= hi) / n
        print(f"\n■ {label}（{n}件・的中した組のみ）")
        print(f"  推定/実際 の比: 中央値 {statistics.median(ratios):.2f}倍"
              f" / 平均 {statistics.mean(ratios):.2f}倍")
        print(f"  25-75%点: {ratios[n//4]:.2f} 〜 {ratios[3*n//4]:.2f}")
        print(f"  ±20%以内に収まった割合: {within(0.8, 1.2):.0%}")
        print(f"  ±50%以内に収まった割合: {within(0.5, 1.5):.0%}")
        print(f"  2倍以上ずれた割合: {sum(1 for r in ratios if r >= 2 or r <= 0.5)/n:.0%}")
        big = sorted(rows, key=lambda x: x[1], reverse=True)[:3]
        print("  高配当側の例（推定 → 実際）: "
              + " / ".join(f"{e:.0f}倍→{a:.0f}倍" for e, a in big))


if __name__ == "__main__":
    main()
