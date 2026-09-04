#!/usr/bin/env python3
"""ワイドと馬連を組み合わせたときの資金配分をシミュレーションする。

同額で併買すると、ワイドの利益を馬連の損失が食い潰す（9/3の10Rで実際に
そうなった）。しかし比重を変えれば話は別なので、配分ごとに測る。

1レースあたりの予算を固定し、ワイド:馬連 の比で分けて各券種の点数で
均等に割る。払戻CSVは100円あたりなので、賭け金に応じて按分する。

    python3 scripts/mix.py --races 9-12 --ratings <path> [--budget 1000]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keiba.scoring as sc
from backtest import load_race, load_race_info, parse_races, race_date, race_number
from keiba.cli import _load_horse_records
from keiba.marks import assign_marks

# ワイド:馬連 の比。100:0 と 0:100 は片張りの対照
RATIOS = [(10, 0), (9, 1), (8, 2), (7, 3), (5, 5), (0, 10)]

STRUCTURES = {
    "ワイド3点+馬連3点": (3, 3),   # どちらも上位3頭BOX
    "ワイド6点+馬連6点": (4, 4),   # どちらも上位4頭BOX
}


def payoff(kind: str, tickets: list[frozenset], race: dict, stake: float) -> float:
    """賭け金 stake（1点あたり）での払戻。配当CSVは100円あたり。"""
    table = race["payouts"].get(kind, {})
    top2, top3 = race["top2"], race["top3"]
    total = 0.0
    for t in tickets:
        hit = (t <= top3) if kind == "ワイド" else (t == top2)
        if hit:
            total += table.get(t, 0) * stake / 100.0
    return total


def bootstrap(pairs: list[tuple[float, float]], b: int) -> tuple[float, float, float]:
    if not pairs:
        return (0.0, 0.0, 0.0)
    rng = random.Random(20260904)
    n = len(pairs)
    rates = []
    for _ in range(b):
        inv = ret = 0.0
        for _ in range(n):
            i, r = pairs[rng.randrange(n)]
            inv += i
            ret += r
        rates.append(ret / inv if inv else 0.0)
    rates.sort()
    return (rates[int(0.05 * len(rates))], rates[int(0.95 * len(rates))],
            sum(1 for r in rates if r >= 1.0) / len(rates))


def drawdown(pairs: list[tuple[float, float]]) -> tuple[int, float]:
    cum = peak = dd = streak = worst = 0.0
    for inv, ret in pairs:
        cum += ret - inv
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
        streak = 0 if ret > 0 else streak + 1
        worst = max(worst, streak)
    return int(worst), dd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected")
    ap.add_argument("--races", default="9-12")
    ap.add_argument("--ratings")
    ap.add_argument("--race-info", default="data/race_info.csv")
    ap.add_argument("--budget", type=float, default=1000.0, help="1レースあたりの予算(円)")
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--by-tier", action="store_true", help="1番人気オッズ帯ごとに分けて出す")
    args = ap.parse_args()

    if args.ratings:
        table = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
        sc.load_ratings = lambda *a, **k: table

    wanted = parse_races(args.races)
    kyori_by = load_race_info(args.race_info)
    records = _load_horse_records()
    d = Path(args.dir)

    series: dict[tuple[str, str, str], list[tuple[float, float]]] = {}
    n_races = 0
    for stem in sorted({p.name.replace("_結果.csv", "") for p in d.glob("*_結果.csv")}):
        rn = race_number(stem)
        if rn is None or rn not in wanted:
            continue
        race = load_race(d, stem)
        if race is None:
            continue
        fav = min((h for h in race["horses"] if h.ninki), key=lambda h: h.ninki, default=None)
        if fav is None or not fav.tansho_odds:
            continue
        scores = sc.score_race(race["horses"], None, kyori=kyori_by.get(stem),
                               records=records, as_of=race_date(stem))
        marked = assign_marks(scores, baba="良")
        if len(marked) < 6:
            continue
        n_races += 1
        order = [m.score.horse.umaban for m in marked]
        tier = ("1倍台" if fav.tansho_odds < 2.0
                else "2倍台" if fav.tansho_odds < 3.0 else "3倍以上")

        for sname, (nw, nu) in STRUCTURES.items():
            wide = [frozenset(c) for c in combinations(order[:nw], 2)]
            umaren = [frozenset(c) for c in combinations(order[:nu], 2)]
            for rw, ru in RATIOS:
                bw = args.budget * rw / 10.0
                bu = args.budget * ru / 10.0
                ret = 0.0
                if bw:
                    ret += payoff("ワイド", wide, race, bw / len(wide))
                if bu:
                    ret += payoff("馬連", umaren, race, bu / len(umaren))
                key = (sname, f"{rw}:{ru}", tier)
                series.setdefault(key, []).append((args.budget, ret))
                series.setdefault((sname, f"{rw}:{ru}", "全体"), []).append((args.budget, ret))

    tiers = ["全体"] + (["1倍台", "2倍台", "3倍以上"] if args.by_tier else [])
    print(f"大井{args.races}R {n_races}レース・1レース{args.budget:,.0f}円・"
          f"ブートストラップ{args.bootstrap:,}回")
    print("比は ワイド:馬連。10:0=ワイドのみ、0:10=馬連のみ（対照）\n")
    for tier in tiers:
        print(f"── {tier} " + "─" * 56)
        print(f"{'構成':<20}{'比':>7}{'R数':>5}{'的中率':>7}{'回収率':>7}"
              f"{'90%区間':>17}{'100%超':>7}{'最大連敗':>7}{'最大DD':>11}")
        for sname in STRUCTURES:
            rows = []
            for rw, ru in RATIOS:
                pairs = series.get((sname, f"{rw}:{ru}", tier))
                if not pairs:
                    continue
                inv = sum(i for i, _ in pairs)
                ret = sum(r for _, r in pairs)
                hit = sum(1 for _, r in pairs if r > 0)
                lo, hi, win = bootstrap(pairs, args.bootstrap)
                streak, dd = drawdown(pairs)
                rows.append((f"{rw}:{ru}", len(pairs), hit / len(pairs), ret / inv,
                             lo, hi, win, streak, dd))
            for r in rows:
                print(f"{sname:<20}{r[0]:>7}{r[1]:>5}{r[2]:>7.0%}{r[3]:>7.0%}"
                      f"{f'{r[4]:.0%} 〜 {r[5]:.0%}':>17}{r[6]:>7.0%}"
                      f"{r[7]:>6}連{r[8]:>+10,.0f}円")
            print()


if __name__ == "__main__":
    main()
