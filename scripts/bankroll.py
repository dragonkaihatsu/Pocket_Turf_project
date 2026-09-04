#!/usr/bin/env python3
"""仮想資金を持って開催を渡り歩いたときに、資金がどう推移するかを測る。

回収率は「無限に賭け続けられる人」の指標であり、手元に1万円しかない人の
指標ではない。実測の最大連敗は6〜13あるので、1万円で毎レース1,000円を
入れると10レースで破産する。ここでは以下を測る。

  * 最終資金 … 増えたか減ったか
  * 破産率   … 途中で買えなくなった割合（1点100円×点数を払えない）
  * 最大DD   … 途中でどこまで凹んだか
  * 生存率   … 元本を割らずに終えた割合

実際の制約も入れる:
  * 賭け金は100円単位
  * n点買うには最低 n×100円 必要（払えないレースは見送り）
  * **見送りも戦略**。期待値が負の帯を飛ばすことが最大の資金保全になる

    python3 scripts/bankroll.py --ratings <path> [--start 10000]
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
from backtest import load_race, load_race_info, parse_races, race_date, race_number
from keiba.cli import _load_horse_records
from keiba.marks import assign_marks

UNIT = 100  # 100円単位

# 帯ごとの買い方。(ワイドの頭数, 馬連の頭数, ワイド:馬連の比)
# 0頭ならその券種は買わない。CLAUDE.mdの配分表に対応する
RECIPES = {
    "1倍台":  (3, 3, 0.7),   # ワイド3点+馬連3点 を 7:3
    "2倍台":  (3, 0, 1.0),   # ワイド3点のみ
    "3倍以上": (0, 4, 0.0),   # 馬連 上位4頭BOX 6点のみ
}


def race_multiple(race, order, recipe) -> tuple[int, float]:
    """(必要点数, 1円あたりの払戻倍率) を返す。"""
    nw, nu, w_ratio = recipe
    wide = [frozenset(c) for c in combinations(order[:nw], 2)] if nw else []
    umaren = [frozenset(c) for c in combinations(order[:nu], 2)] if nu else []
    points = len(wide) + len(umaren)
    if not points:
        return 0, 0.0

    top2, top3 = race["top2"], race["top3"]
    wt = race["payouts"].get("ワイド", {})
    ut = race["payouts"].get("馬連", {})

    # 1円あたりの払戻。ワイド側に w_ratio、馬連側に 1-w_ratio を配分する
    ret = 0.0
    if wide:
        per = w_ratio / len(wide)
        ret += sum(wt.get(t, 0) / 100.0 * per for t in wide if t <= top3)
    if umaren:
        per = (1 - w_ratio) / len(umaren)
        ret += sum(ut.get(t, 0) / 100.0 * per for t in umaren if t == top2)
    return points, ret


def stake_for(bankroll: int, points: int, rule: str, frac: float) -> int:
    """このレースに入れる金額（100円単位）。0なら見送り。"""
    floor = points * UNIT
    if bankroll < floor:
        return 0
    if rule == "flat":
        target = int(frac)
    else:  # 資金比例
        target = int(bankroll * frac)
    target = (target // UNIT) * UNIT
    return max(floor, min(target, (bankroll // UNIT) * UNIT))


def simulate(races, rule, frac, start, skip_tiers, rng=None) -> dict:
    bankroll = start
    peak = start
    dd = 0
    played = skipped = 0
    for tier, points, mult in (races if rng is None else
                               [races[rng.randrange(len(races))] for _ in races]):
        if tier in skip_tiers or points == 0:
            skipped += 1
            continue
        stake = stake_for(bankroll, points, rule, frac)
        if stake == 0:
            skipped += 1
            continue
        played += 1
        bankroll += int(round(stake * mult)) - stake
        peak = max(peak, bankroll)
        dd = min(dd, bankroll - peak)
    return {"final": bankroll, "played": played, "skipped": skipped, "dd": dd}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected")
    ap.add_argument("--races", default="9-12")
    ap.add_argument("--ratings")
    ap.add_argument("--race-info", default="data/race_info.csv")
    ap.add_argument("--start", type=int, default=10000)
    ap.add_argument("--trials", type=int, default=5000)
    args = ap.parse_args()

    if args.ratings:
        table = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
        sc.load_ratings = lambda *a, **k: table

    wanted = parse_races(args.races)
    kyori_by = load_race_info(args.race_info)
    records = _load_horse_records()
    d = Path(args.dir)

    seq = []
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
        tier = ("1倍台" if fav.tansho_odds < 2.0
                else "2倍台" if fav.tansho_odds < 3.0 else "3倍以上")
        order = [m.score.horse.umaban for m in marked]
        points, mult = race_multiple(race, order, RECIPES[tier])
        seq.append((tier, points, mult))

    print(f"仮想資金{args.start:,}円で大井{args.races}R {len(seq)}レースを通す")
    print(f"賭け金は100円単位・n点買うには最低n×100円必要・払えないレースは見送り\n")

    ALL, ONLY3 = set(), {"1倍台", "2倍台"}
    plans = [
        ("定額1,000円/R・全帯",        "flat", 1000.0, ALL),
        ("定額600円/R・全帯",          "flat", 600.0, ALL),
        ("資金の5%・全帯",             "prop", 0.05, ALL),
        ("資金の5%・2倍台を見送り",      "prop", 0.05, {"2倍台"}),
        ("資金の20%・3倍以上のみ",       "prop", 0.20, ONLY3),
        ("資金の10%・3倍以上のみ",       "prop", 0.10, ONLY3),
        ("資金の5%・3倍以上のみ",        "prop", 0.05, ONLY3),
        ("資金の3%・3倍以上のみ",        "prop", 0.03, ONLY3),
        ("定額600円/R・3倍以上のみ",     "flat", 600.0, ONLY3),
    ]

    print(f"{'資金配分':<24}{'買った':>6}{'見送':>5}{'最終資金(実際の順)':>20}{'最大DD':>10}")
    actual = {}
    for label, rule, frac, skip in plans:
        r = simulate(seq, rule, frac, args.start, skip)
        actual[label] = r
        print(f"{label:<24}{r['played']:>6}{r['skipped']:>5}{r['final']:>17,}円{r['dd']:>+9,}円")

    print(f"\n順番を{args.trials:,}通りに引き直したときの分布")
    print(f"{'資金配分':<24}{'破産率':>7}{'元本割れ':>8}{'中央値':>11}{'5%点':>10}{'95%点':>11}")
    rng = random.Random(20260904)
    for label, rule, frac, skip in plans:
        finals = [simulate(seq, rule, frac, args.start, skip, rng)["final"]
                  for _ in range(args.trials)]
        finals.sort()
        ruin = sum(1 for f in finals if f < 600) / len(finals)
        under = sum(1 for f in finals if f < args.start) / len(finals)
        print(f"{label:<24}{ruin:>7.0%}{under:>8.0%}"
              f"{statistics.median(finals):>10,.0f}円"
              f"{finals[int(0.05*len(finals))]:>9,.0f}円"
              f"{finals[int(0.95*len(finals))]:>10,.0f}円")
    print("\n  破産率 = 資金600円未満（最低単位を払えない）で終わった割合")
    print("  元本割れ = 最終資金が開始資金を下回った割合")


if __name__ == "__main__":
    main()
