#!/usr/bin/env python3
"""ベタで全部買った場合の収支を円で出す。

回収率は「無限に賭け続けられる人」の指標であって、手元にいくら要るかは
言わない。ここでは実際の開催順に賭けていったときの

    投資額 / 払戻額 / 収支 / 累積収支の最安値（＝必要だった資金）/ 最大連敗

を円で出す。1点100円・全レース機械的に購入・見送りなし。

    python3 scripts/shushi.py --profile jra --year 2026
"""
from __future__ import annotations

import argparse
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

STAKE = 100
STRATEGIES = [("馬連", 4), ("馬連", 5), ("ワイド", 3), ("ワイド", 4)]


def settle(kind, tickets, race):
    table = race["payouts"].get(kind, {})
    ret = 0
    for t in tickets:
        hit = (t <= race["top3"]) if kind == "ワイド" else (t == race["top2"])
        if hit:
            ret += table.get(t, 0)
    return len(tickets) * STAKE, ret


def cashflow(pairs):
    """(投資, 払戻) の並びから円ベースの指標を出す。"""
    inv = sum(i for i, _ in pairs)
    ret = sum(r for _, r in pairs)
    cum = 0
    low = 0          # 累積収支の最安値 = 用意しておくべきだった額
    peak = 0
    dd = 0           # 山からの最大下落
    streak = worst = 0
    for i, r in pairs:
        cum += r - i
        low = min(low, cum)
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
        if r > 0:
            streak = 0
        else:
            streak += 1
            worst = max(worst, streak)
    hit = sum(1 for _, r in pairs if r > 0)
    return {"n": len(pairs), "inv": inv, "ret": ret, "pl": ret - inv,
            "roi": ret / inv if inv else 0.0, "hit": hit / len(pairs),
            "low": low, "dd": dd, "streak": worst}


def run(order_of, races):
    out = {}
    for kind, k in STRATEGIES:
        pairs = []
        for r in races:
            order = order_of(r)
            if not order or len(order) < k:
                continue
            pairs.append(settle(kind, [frozenset(c)
                                       for c in combinations(order[:k], 2)], r))
        if pairs:
            out[(kind, k)] = cashflow(pairs)
    return out


def show(title, res):
    print(f"\n── {title} " + "─" * max(0, 56 - len(title)))
    print(f"{'買い方':<16}{'R数':>5}{'1R':>7}{'投資':>11}{'払戻':>11}"
          f"{'収支':>11}{'回収率':>7}{'必要資金':>10}{'連敗':>5}")
    for kind, k in STRATEGIES:
        d = res.get((kind, k))
        if not d:
            continue
        pts = k * (k - 1) // 2
        name = f"{kind} 上位{k}頭({pts}点)"
        print(f"{name:<16}{d['n']:>5}{pts * STAKE:>7,}{d['inv']:>11,}"
              f"{d['ret']:>11,}{d['pl']:>+11,}{d['roi']:>7.0%}"
              f"{-d['low']:>10,}{d['streak']:>5}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["nar", "jra"], default="jra")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--races", default="9-12")
    ap.add_argument("--year", help="この年だけ")
    args = ap.parse_args()

    import keiba.profile as profile
    prof = profile.use(args.profile)
    kyori_by = load_race_info(str(prof.path("race_info.csv")))
    records = _load_horse_records(str(prof.path("horse_records.csv")))
    wanted = parse_races(args.races)
    d = Path(args.dir or ("data/collected" if args.profile == "nar"
                          else "data/collected_jra"))

    races = []
    for stem in sorted({p.name[:-len("_結果.csv")] for p in d.glob("*_結果.csv")}):
        rn = race_number(stem)
        if rn is None or rn not in wanted:
            continue
        if args.year and not stem.startswith(args.year):
            continue
        race = load_race(d, stem)
        if race is None:
            continue
        scores = sc.score_race(race["horses"], None, kyori=kyori_by.get(stem),
                               records=records, as_of=race_date(stem),
                               venue=race_venue(stem))
        marked = assign_marks(scores, baba="良")
        race["score_order"] = [m.score.horse.umaban for m in marked]
        race["ninki_order"] = [h.umaban for h in
                               sorted(race["horses"],
                                      key=lambda h: h.ninki or 99)]
        races.append(race)

    label = ("中央" if args.profile == "jra" else "地方") + \
            (f" {args.year}年" if args.year else "")
    print(f"{label} {args.races}R {len(races)}レース・1点{STAKE}円・"
          f"全レース機械的に購入（見送りなし）")
    print("必要資金 = 累積収支がいちばん沈んだ額。ここを耐えられないと途中で買えなくなる")

    show(f"{label}  スコア順（本システム）", run(lambda r: r["score_order"], races))
    show(f"{label}  人気順（対照）", run(lambda r: r["ninki_order"], races))


if __name__ == "__main__":
    main()
