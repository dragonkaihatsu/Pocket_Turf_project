#!/usr/bin/env python3
"""合成オッズを設計して1レースの予算を不等分配するシミュレーション。

考え方（均等払戻し方式）:
    オッズ O_i の馬券に P/O_i ずつ賭けると、どれが当たっても払戻は P で揃う。
    人気薄ほど賭け金が薄く、人気馬ほど厚くなる。このとき

        合成オッズ = P / 総投資 = 1 / Σ(1/O_i)

    となり、買う組み合わせを決めた時点で確定する。買い目を増やすほど
    的中率は上がるが合成オッズは下がる。**そのトレードオフを設計する。**

    回収率 = 合成オッズ × 的中率

    なので、150%を狙うなら「合成オッズ3.0倍 × 的中率50%」のような
    組み合わせを探すことになる。

オッズの出どころ:
    買う前に全組み合わせのオッズが要るが、収集できるのは的中組の確定配当
    だけなので、単勝オッズから Harville モデルで推定する（keiba/oddsmodel）。
    **配分の計算にだけ推定値を使い、精算は実際の確定配当で行う。**
    推定の精度は scripts/validate_odds.py で確認すること（馬連は91%が±50%内）。

    python3 scripts/gosei.py --races 9-12 --ratings <path> --budget 5000
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keiba.scoring as sc
from backtest import (load_race, load_race_info, parse_races, race_date,
                      race_number, race_venue)
from keiba.cli import _load_horse_records
from keiba.marks import assign_marks
from keiba.oddsmodel import estimate_umaren, estimate_wide

UNIT = 100


def candidates(kind: str, order: list[int], odds: dict[int, float], pool: int):
    """(組, 推定オッズ) をオッズの安い順（＝来やすい順）に並べて返す。"""
    est = estimate_umaren if kind == "馬連" else estimate_wide
    out = []
    for a, b in combinations(order[:pool], 2):
        o = est(odds, a, b)
        if o and o > 0:
            out.append((frozenset({a, b}), o))
    out.sort(key=lambda x: x[1])
    return out


def select_for_target(cands, target: float):
    """合成オッズが target を下回らない範囲で、来やすい順に買い足す。"""
    chosen, inv_sum = [], 0.0
    for combo, o in cands:
        nxt = inv_sum + 1.0 / o
        if nxt > 0 and 1.0 / nxt < target and chosen:
            break
        chosen.append((combo, o))
        inv_sum = nxt
    gosei = 1.0 / inv_sum if inv_sum > 0 else 0.0
    return chosen, gosei


def allocate_flat(chosen, budget: int) -> dict[frozenset, int]:
    """均等配分（比較用）。全点に同じ金額を賭ける。"""
    if not chosen:
        return {}
    each = max(UNIT, int(budget / len(chosen) / UNIT) * UNIT)
    return {combo: each for combo, _ in chosen}


def allocate(chosen, budget: int) -> dict[frozenset, int]:
    """均等払戻しになるよう100円単位で配分する。人気薄ほど薄くなる。

    賭け金が100円単位なので払戻は完全には揃わない。予算5,000円・
    オッズ2/5/10倍なら 3,100/1,300/600円 となり払戻は約8%ばらつく。
    予算が小さいほど、また点数が多いほどこのずれは大きくなる。
    """
    inv_sum = sum(1.0 / o for _, o in chosen)
    if inv_sum <= 0:
        return {}
    payout = budget / inv_sum          # どれが当たってもこの額を狙う
    stakes = {}
    for combo, o in chosen:
        s = int(round(payout / o / UNIT)) * UNIT
        stakes[combo] = max(UNIT, s)   # 最低100円
    return stakes


def settle(kind: str, stakes: dict[frozenset, int], race: dict) -> tuple[int, int]:
    table = race["payouts"].get(kind, {})
    top2, top3 = race["top2"], race["top3"]
    inv = sum(stakes.values())
    ret = 0
    for combo, s in stakes.items():
        hit = (combo <= top3) if kind == "ワイド" else (combo == top2)
        if hit:
            ret += int(table.get(combo, 0) * s / 100)
    return inv, ret


def bootstrap(pairs, b=10000):
    if not pairs:
        return (0.0, 0.0, 0.0)
    rng = random.Random(20260904)
    n = len(pairs)
    rates = []
    for _ in range(b):
        inv = ret = 0
        for _ in range(n):
            i, r = pairs[rng.randrange(n)]
            inv += i
            ret += r
        rates.append(ret / inv if inv else 0.0)
    rates.sort()
    return (rates[int(0.05 * len(rates))], rates[int(0.95 * len(rates))],
            sum(1 for r in rates if r >= 1.0) / len(rates))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["nar", "jra"], default="nar")
    ap.add_argument("--dir", default=None,
                    help="既定は地方 data/collected / 中央 data/collected_jra")
    ap.add_argument("--races", default="9-12")
    ap.add_argument("--ratings")
    ap.add_argument("--race-info", default=None)
    ap.add_argument("--year", help="この年のレースだけ（年またぎの検証用）")
    ap.add_argument("--budget", type=int, default=5000)
    ap.add_argument("--pool", type=int, default=6, help="買い目を作るスコア上位の頭数")
    ap.add_argument("--kinds", default="馬連,ワイド")
    ap.add_argument("--targets", default="1.5,2,2.5,3,4,5,7,10")
    ap.add_argument("--by-tier", action="store_true")
    args = ap.parse_args()

    import keiba.profile as profile
    prof = profile.use(args.profile)
    if args.ratings:
        table = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
        sc.load_ratings = lambda *a, **k: table

    wanted = parse_races(args.races)
    kyori_by = load_race_info(args.race_info or str(prof.path("race_info.csv")))
    # 戦績を渡さないとコース適性・距離適性が全馬中立に倒れる
    records = _load_horse_records(str(prof.path("horse_records.csv")))
    targets = [float(x) for x in args.targets.split(",")]
    kinds = args.kinds.split(",")
    d = Path(args.dir or ("data/collected" if args.profile == "nar"
                          else "data/collected_jra"))

    res: dict = {}
    n_races = 0
    for stem in sorted({p.name.replace("_結果.csv", "") for p in d.glob("*_結果.csv")}):
        rn = race_number(stem)
        if rn is None or rn not in wanted:
            continue
        if args.year and not stem.startswith(args.year):
            continue
        race = load_race(d, stem)
        if race is None:
            continue
        odds = {h.umaban: h.tansho_odds for h in race["horses"] if h.tansho_odds}
        if len(odds) < 5:
            continue
        fav = min((h for h in race["horses"] if h.ninki), key=lambda h: h.ninki, default=None)
        if fav is None or not fav.tansho_odds:
            continue
        tier = ("1倍台" if fav.tansho_odds < 2.0
                else "2倍台" if fav.tansho_odds < 3.0 else "3倍以上")
        scores = sc.score_race(race["horses"], None, kyori=kyori_by.get(stem),
                               records=records, as_of=race_date(stem),
                               venue=race_venue(stem))
        marked = assign_marks(scores, baba="良")
        if len(marked) < args.pool:
            continue
        n_races += 1
        order = [m.score.horse.umaban for m in marked]

        for kind in kinds:
            cands = candidates(kind, order, odds, args.pool)
            if not cands:
                continue
            for t in targets:
                chosen, gosei = select_for_target(cands, t)
                for mode, fn in (("均等払戻", allocate), ("均等配分", allocate_flat)):
                    stakes = fn(chosen, args.budget)
                    if not stakes:
                        continue
                    inv, ret = settle(kind, stakes, race)
                    for scope in ("全体", tier) if args.by_tier else ("全体",):
                        r = res.setdefault((kind, t, scope, mode),
                                           {"pairs": [], "n_tickets": [], "gosei": []})
                        r["pairs"].append((inv, ret))
                        r["n_tickets"].append(len(stakes))
                        r["gosei"].append(gosei)

    scopes = ["全体"] + (["1倍台", "2倍台", "3倍以上"] if args.by_tier else [])
    label = "中央" if args.profile == "jra" else "地方"
    print(f"{label}{args.races}R {n_races}レース・1レース{args.budget:,}円・"
          f"スコア上位{args.pool}頭から選択")
    print("均等払戻し配分（人気薄ほど薄く、人気馬ほど厚く）。"
          "配分は推定オッズ、精算は実配当\n")
    for scope in scopes:
        print(f"── {scope} " + "─" * 60)
        print(f"{'券種':<5}{'目標':>6}{'合成':>7}{'点数':>5}{'配分':<9}"
              f"{'的中率':>7}{'回収率':>7}{'90%区間':>17}{'100%超':>7}")
        for kind in kinds:
            for t in targets:
                for mode in ("均等払戻", "均等配分"):
                    r = res.get((kind, t, scope, mode))
                    if not r:
                        continue
                    pairs = r["pairs"]
                    inv = sum(i for i, _ in pairs)
                    ret = sum(x for _, x in pairs)
                    hit = sum(1 for _, x in pairs if x > 0)
                    lo, hi, win = bootstrap(pairs)
                    print(f"{kind:<5}{t:>5.1f}倍{statistics.median(r['gosei']):>6.1f}倍"
                          f"{statistics.median(r['n_tickets']):>5.0f} {mode:<8}"
                          f"{hit/len(pairs):>7.0%}{ret/inv:>7.0%}"
                          f"{f'{lo:.0%} 〜 {hi:.0%}':>17}{win:>7.0%}")
            print()


if __name__ == "__main__":
    main()
