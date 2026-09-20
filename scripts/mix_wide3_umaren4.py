#!/usr/bin/env python3
"""「ワイド3点厚張り + 馬連4頭BOX広め買い」を検証する。

本人が現在実際に使っている買い方（2026-09-20時点）:
  ワイド … スコア上位3頭BOX（3点）に**厚く**張る
  馬連   … スコア上位4頭BOX（6点）を**広めに**（3頭より広く）流す

`scripts/mix.py` は同じ幅どうし（3+3 / 4+4）しか比べられなかったので、
**幅が違う組み合わせ**（ワイド3頭・馬連4頭）専用に別スクリプトを立てた。
1レースの予算を比で分け、各券種の点数（ワイド3点・馬連6点）で均等に割る。

    python3 scripts/mix_wide3_umaren4.py --races 1-12 --target-races 9-12
"""
from __future__ import annotations

import argparse
import random
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keiba.scoring as sc
from backtest import load_race, load_race_info, race_date, race_number, race_venue
from keiba.cli import _load_horse_records
from keiba.marks import assign_marks
from keiba.racefiles import DEFAULT_RACES, parse_races, result_files

# ワイド:馬連 の予算比。10:0=ワイドのみ、0:10=馬連のみ（対照）。
# 「厚張り」側の実感に近い 7:3〜9:1 も足す
RATIOS = [(10, 0), (9, 1), (8, 2), (7, 3), (6, 4), (5, 5), (3, 7), (0, 10)]

WIDE_N = 3
UMAREN_N = 4


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


def bootstrap(pairs: list[tuple[float, float]], b: int = 10000) -> tuple[float, float, float]:
    if not pairs:
        return (0.0, 0.0, 0.0)
    rng = random.Random(20260920)
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
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES,
                    help="履歴として使う帯（前走ペア等には使わないが揃えておく）")
    ap.add_argument("--target-races", default=None,
                    help="採点・精算の対象帯。省略時は --races と同じ")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--records", default="data/profiles/jra/horse_records.csv")
    ap.add_argument("--budget", type=float, default=1000.0, help="1レースあたりの予算(円)")
    ap.add_argument("--by-tier", action="store_true", default=True,
                    help="1番人気オッズ帯ごとに分けて出す（既定でオン）")
    ap.add_argument("--year", help="この年のレースだけ見る（独立検証用）")
    args = ap.parse_args()

    target = args.target_races or args.races
    wanted = parse_races(target)
    kyori_by = load_race_info(args.race_info)
    records = _load_horse_records(args.records)
    d = Path(args.dir)

    series: dict[tuple[str, str], list[tuple[float, float]]] = {}
    n_races = 0
    for res in result_files(d, target):
        stem = res.name.replace("_結果.csv", "")
        if args.year and not stem.startswith(args.year):
            continue
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
                               records=records, as_of=race_date(stem),
                               venue=race_venue(stem))
        marked = assign_marks(scores, baba="良")
        if len(marked) < max(WIDE_N, UMAREN_N):
            continue
        n_races += 1
        order = [m.score.horse.umaban for m in marked]
        tier = ("1倍台" if fav.tansho_odds < 2.0
                else "2倍台" if fav.tansho_odds < 3.0 else "3倍以上")

        wide = [frozenset(c) for c in combinations(order[:WIDE_N], 2)]
        umaren = [frozenset(c) for c in combinations(order[:UMAREN_N], 2)]
        for rw, ru in RATIOS:
            bw = args.budget * rw / 10.0
            bu = args.budget * ru / 10.0
            ret = 0.0
            if bw:
                ret += payoff("ワイド", wide, race, bw / len(wide))
            if bu:
                ret += payoff("馬連", umaren, race, bu / len(umaren))
            key = (f"{rw}:{ru}", tier)
            series.setdefault(key, []).append((args.budget, ret))
            series.setdefault((f"{rw}:{ru}", "全体"), []).append((args.budget, ret))

    label = f"（{args.year}年のみ）" if args.year else ""
    tiers = ["全体"] + (["1倍台", "2倍台", "3倍以上"] if args.by_tier else [])
    print(f"{args.dir} {n_races:,}レース・1レース{args.budget:,.0f}円{label}")
    print(f"ワイド{WIDE_N}頭BOX({len(list(combinations(range(WIDE_N),2)))}点) + "
          f"馬連{UMAREN_N}頭BOX({len(list(combinations(range(UMAREN_N),2)))}点)")
    print("比は ワイド:馬連。10:0=ワイドのみ、0:10=馬連のみ（対照）\n")
    for tier in tiers:
        print(f"■ {tier}")
        print(f"{'比':<8}{'R数':>7}{'的中率':>7}{'回収率':>7}{'90%区間':>16}"
              f"{'黒字確率':>9}{'最大連敗':>9}{'最大DD':>12}")
        for rw, ru in RATIOS:
            key = (f"{rw}:{ru}", tier)
            pairs = series.get(key, [])
            if not pairs:
                continue
            inv = sum(i for i, _ in pairs)
            ret = sum(r for _, r in pairs)
            hit = sum(1 for _, r in pairs if r > 0)
            lo, hi, win = bootstrap(pairs)
            streak, dd = drawdown(pairs)
            print(f"{rw}:{ru:<6}{len(pairs):>7,}{hit/len(pairs):>7.0%}"
                  f"{ret/inv:>7.0%}{lo:>7.0%}〜{hi:<7.0%}{win:>9.0%}"
                  f"{streak:>9}連敗{dd:>10,.0f}円")
        print()


if __name__ == "__main__":
    main()
