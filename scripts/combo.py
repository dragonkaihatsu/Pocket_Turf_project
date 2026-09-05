#!/usr/bin/env python3
"""券種を組み合わせた買い方の安定性を測る。

「ワイド4頭BOX(6点)＋馬連5頭BOX(10点)が最も安定なのでは」という提案を
検証するために書いた。mix.py は1レースの予算を比で分ける方式だったが、
実際の買い方は「1点100円で両方買う」なので、こちらは点数×100円で測る。

安定性は回収率だけでは分からない。黒字確率・最大連敗・最大ドローダウンを
並べ、DDは「1レース分の投資の何倍か」に直して点数の違う構成を比べられる
ようにする。

    python3 scripts/combo.py --profile nar --dir data/collected --races 9-12
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

import keiba.profile as profile
import keiba.scoring as sc
from backtest import (load_race, load_race_info, parse_races, race_date,
                      race_number, race_venue)
from keiba.cli import _load_horse_records
from keiba.marks import assign_marks
from keiba.tenkai import load_corner_records

STAKE = 100

# 構成 = (券種, 上位何頭のBOX) のリスト。点数は組み合わせ数から出す
STRUCTURES: dict[str, list[tuple[str, int]]] = {
    "ワイド3頭(3点)":            [("ワイド", 3)],
    "ワイド4頭(6点)":            [("ワイド", 4)],
    "馬連4頭(6点)":              [("馬連", 4)],
    "馬連5頭(10点)":             [("馬連", 5)],
    "ワイド3頭+馬連4頭(9点)":    [("ワイド", 3), ("馬連", 4)],
    "ワイド4頭+馬連4頭(12点)":   [("ワイド", 4), ("馬連", 4)],
    "ワイド3頭+馬連5頭(13点)":   [("ワイド", 3), ("馬連", 5)],
    "ワイド4頭+馬連5頭(16点)":   [("ワイド", 4), ("馬連", 5)],
}


def tickets_for(legs: list[tuple[str, int]], order: list[int]) -> list[tuple[str, frozenset]]:
    out = []
    for kind, n in legs:
        for c in combinations(order[:n], 2):
            out.append((kind, frozenset(c)))
    return out


def settle(tickets, race) -> tuple[int, int]:
    invest = len(tickets) * STAKE
    ret = 0
    for kind, t in tickets:
        hit = (t <= race["top3"]) if kind == "ワイド" else (t == race["top2"])
        if hit:
            ret += race["payouts"].get(kind, {}).get(t, 0)
    return invest, ret


def bootstrap(pairs, b: int) -> tuple[float, float, float]:
    if not pairs:
        return (0.0, 0.0, 0.0)
    rng = random.Random(20260905)
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


def drawdown(pairs) -> tuple[int, float]:
    cum = peak = dd = 0.0
    streak = worst = 0
    for inv, ret in pairs:
        cum += ret - inv
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
        streak = 0 if ret > 0 else streak + 1
        worst = max(worst, streak)
    return worst, dd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["nar", "jra"], default="nar")
    ap.add_argument("--dir", default=None, help="既定は地方 data/collected / 中央 data/collected_jra")
    ap.add_argument("--races", default="9-12")
    ap.add_argument("--ratings", help="1-8R由来など、検証対象と別レースから作った補正")
    ap.add_argument("--race-info", default=None)
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--json", help="結果をJSONで書き出す")
    ap.add_argument("--no-corner", action="store_true",
                    help="4角履歴による位置推定を使わない（脚質ラベルのみ。A/B比較用）")
    args = ap.parse_args()

    prof = profile.use(args.profile)
    directory = Path(args.dir or ("data/collected" if args.profile == "nar" else "data/collected_jra"))
    info_path = args.race_info or str(prof.path("race_info.csv"))

    if args.ratings:
        table = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
        sc.load_ratings = lambda *a, **k: table

    wanted = parse_races(args.races)
    kyori_by = load_race_info(info_path)
    records = _load_horse_records(str(prof.path("horse_records.csv")))
    corners = None if args.no_corner else load_corner_records()

    series: dict[tuple[str, str], list[tuple[int, int]]] = {}
    n_races = 0
    for stem in sorted({p.name.replace("_結果.csv", "") for p in directory.glob("*_結果.csv")}):
        rn = race_number(stem)
        if rn is None or rn not in wanted:
            continue
        race = load_race(directory, stem)
        if race is None:
            continue
        fav = min((h for h in race["horses"] if h.ninki), key=lambda h: h.ninki, default=None)
        if fav is None or not fav.tansho_odds:
            continue
        scores = sc.score_race(race["horses"], None, kyori=kyori_by.get(stem),
                               records=records, as_of=race_date(stem),
                               venue=race_venue(stem), corner_records=corners)
        marked = assign_marks(scores, baba="良")
        if len(marked) < 6:
            continue
        n_races += 1
        order = [m.score.horse.umaban for m in marked]
        tier = ("1倍台" if fav.tansho_odds < 2.0
                else "2倍台" if fav.tansho_odds < 3.0 else "3倍以上")
        for name, legs in STRUCTURES.items():
            pair = settle(tickets_for(legs, order), race)
            series.setdefault((name, tier), []).append(pair)
            series.setdefault((name, "全体"), []).append(pair)

    label = "地方" if args.profile == "nar" else "中央"
    print(f"{label} {args.races}R {n_races}レース・1点{STAKE}円・"
          f"ブートストラップ{args.bootstrap:,}回")
    print("DD倍数 = 最大ドローダウン ÷ 1レース分の投資額（点数の違う構成を比べるため）\n")

    out: dict = {"profile": args.profile, "races": n_races, "rows": []}
    for tier in ["全体", "1倍台", "2倍台", "3倍以上"]:
        rows = []
        for name in STRUCTURES:
            pairs = series.get((name, tier))
            if not pairs:
                continue
            inv = sum(i for i, _ in pairs)
            ret = sum(r for _, r in pairs)
            hit = sum(1 for _, r in pairs if r > 0)
            lo, hi, win = bootstrap(pairs, args.bootstrap)
            streak, dd = drawdown(pairs)
            per = pairs[0][0]
            rows.append({"帯": tier, "構成": name, "R数": len(pairs), "点数": per // STAKE,
                         "的中率": hit / len(pairs), "回収率": ret / inv,
                         "下限": lo, "上限": hi, "黒字確率": win,
                         "最大連敗": streak, "最大DD": dd, "DD倍数": abs(dd) / per})
        if not rows:
            continue
        out["rows"].extend(rows)
        print(f"── {tier} ({rows[0]['R数']}レース) " + "─" * 44)
        print(f"{'構成':<26}{'点':>4}{'的中率':>7}{'回収率':>7}{'90%区間':>17}"
              f"{'黒字':>6}{'連敗':>5}{'最大DD':>11}{'DD倍':>7}")
        for r in sorted(rows, key=lambda r: -r["回収率"]):
            ci = "{:.0%} 〜 {:.0%}".format(r["下限"], r["上限"])
            print(f"{r['構成']:<26}{r['点数']:>4}{r['的中率']:>7.0%}{r['回収率']:>7.0%}"
                  f"{ci:>17}{r['黒字確率']:>6.0%}{r['最大連敗']:>5}"
                  f"{r['最大DD']:>+10,.0f}円{r['DD倍数']:>6.0f}")
        print()

    if args.json:
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"→ {args.json}")


if __name__ == "__main__":
    main()
