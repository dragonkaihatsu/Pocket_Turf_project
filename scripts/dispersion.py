#!/usr/bin/env python3
"""「オッズがばらけているレースほど配当が良い」という仮説を測る。

1番人気のオッズは市場の集中度を1点だけ見た指標である。市場全体の
ばらけ方（エントロピー）を測れば、同じ1番人気オッズでも「2番手以下が
拮抗しているレース」と「1頭だけ離れた2番手がいるレース」を区別できる。

肝心なのは**1番人気オッズ帯の中で、さらに情報があるか**。帯だけで説明が
つくならエントロピーを足す意味はない。そこで帯ごとに分けた上で
エントロピー上位半分・下位半分に切って比べる。

    python3 scripts/dispersion.py --profile nar --races 9-12
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
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

STAKE = 100


def market(horses) -> dict | None:
    """単勝オッズから市場の確率分布を作る。控除率ぶんは正規化で落ちる。"""
    odds = [h.tansho_odds for h in horses if h.tansho_odds and h.tansho_odds > 0]
    if len(odds) < 5:
        return None
    raw = [1.0 / o for o in odds]
    total = sum(raw)
    p = sorted((r / total for r in raw), reverse=True)
    n = len(p)
    h = -sum(x * math.log(x) for x in p if x > 0)
    return {"n": n,
            "エントロピー": h / math.log(n),      # 0=1頭に集中, 1=全馬同確率
            "HHI": sum(x * x for x in p),          # 集中度
            "1位/2位": p[0] / p[1] if p[1] > 0 else float("inf"),
            "上位3頭シェア": sum(p[:3])}


def bootstrap(rows, b: int = 10000) -> tuple[float, float, float]:
    """回収率の90%区間と、100%を超えた割合。区分を分けると母数が減るため、
    差が偶然の範囲かどうかを必ず見る。"""
    if not rows:
        return (0.0, 0.0, 0.0)
    rng = random.Random(20260905)
    n = len(rows)
    rates = []
    for _ in range(b):
        inv = ret = 0.0
        for _ in range(n):
            r = rows[rng.randrange(n)]
            inv += r["投資"]
            ret += r["払戻"]
        rates.append(ret / inv if inv else 0.0)
    rates.sort()
    return (rates[int(0.05 * b)], rates[int(0.95 * b)],
            sum(1 for x in rates if x >= 1.0) / b)


def summarize(rows, label: str) -> None:
    if not rows:
        return
    umaren = [r["馬連配当"] for r in rows if r["馬連配当"]]
    fav_win = sum(1 for r in rows if r["1人気連対"]) / len(rows)
    fav_pl = sum(1 for r in rows if r["1人気着内"]) / len(rows)
    inv = sum(r["投資"] for r in rows)
    ret = sum(r["払戻"] for r in rows)
    lo, hi, win = bootstrap(rows)
    ci = "{:.0%} 〜 {:.0%}".format(lo, hi)
    print(f"{label:<22}{len(rows):>5}"
          f"{statistics.median(umaren) if umaren else 0:>9,.0f}円"
          f"{statistics.mean(umaren) if umaren else 0:>10,.0f}円"
          f"{fav_win:>8.0%}{fav_pl:>8.0%}{ret / inv if inv else 0:>9.0%}"
          f"{ci:>16}{win:>7.0%}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["nar", "jra"], default="nar")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--races", default="9-12")
    ap.add_argument("--ratings")
    ap.add_argument("--strategy", default="馬連4", help="回収率を測る買い方（馬連4 / ワイド3）")
    args = ap.parse_args()

    prof = profile.use(args.profile)
    directory = Path(args.dir or ("data/collected" if args.profile == "nar" else "data/collected_jra"))
    if args.ratings:
        table = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
        sc.load_ratings = lambda *a, **k: table

    kind, n_box = ("馬連", 4) if args.strategy == "馬連4" else ("ワイド", 3)
    wanted = parse_races(args.races)
    kyori_by = load_race_info(str(prof.path("race_info.csv")))
    records = _load_horse_records(str(prof.path("horse_records.csv")))

    rows = []
    for stem in sorted({p.name.replace("_結果.csv", "") for p in directory.glob("*_結果.csv")}):
        rn = race_number(stem)
        if rn is None or rn not in wanted:
            continue
        race = load_race(directory, stem)
        if race is None:
            continue
        m = market(race["horses"])
        if m is None:
            continue
        fav = min((h for h in race["horses"] if h.ninki), key=lambda h: h.ninki, default=None)
        if fav is None or not fav.tansho_odds:
            continue
        scores = sc.score_race(race["horses"], None, kyori=kyori_by.get(stem),
                               records=records, as_of=race_date(stem),
                               venue=race_venue(stem))
        marked = assign_marks(scores, baba="良")
        if len(marked) < 6:
            continue
        order = [x.score.horse.umaban for x in marked]
        tickets = [frozenset(c) for c in combinations(order[:n_box], 2)]
        table_pay = race["payouts"].get(kind, {})
        ret = sum(table_pay.get(t, 0) for t in tickets
                  if (t <= race["top3"] if kind == "ワイド" else t == race["top2"]))
        win_pay = race["payouts"].get("馬連", {}).get(race["top2"])
        rows.append({**m, "stem": stem, "1人気オッズ": fav.tansho_odds,
                     "馬連配当": win_pay,
                     "1人気連対": fav.umaban in race["top2"],
                     "1人気着内": fav.umaban in race["top3"],
                     "投資": len(tickets) * STAKE, "払戻": ret})

    label = "地方" if args.profile == "nar" else "中央"
    print(f"{label} {args.races}R {len(rows)}レース / 回収率は{kind}上位{n_box}頭BOX\n")

    print("── エントロピー全体 " + "─" * 45)
    print(f"{'区分':<22}{'R数':>5}{'馬連中央値':>10}{'馬連平均':>11}{'1人気連対':>8}{'1人気着内':>8}{'回収率':>9}{'90%区間':>16}{'黒字':>7}")
    rows.sort(key=lambda r: r["エントロピー"])
    q = len(rows) // 4
    for i, name in enumerate(["エントロピー低(集中)", "やや低", "やや高", "エントロピー高(拮抗)"]):
        chunk = rows[i * q:(i + 1) * q] if i < 3 else rows[3 * q:]
        summarize(chunk, name)

    print("\n── 1番人気オッズ帯の中でさらに二分 " + "─" * 30)
    print(f"{'区分':<22}{'R数':>5}{'馬連中央値':>10}{'馬連平均':>11}{'1人気連対':>8}{'1人気着内':>8}{'回収率':>9}{'90%区間':>16}{'黒字':>7}")
    tiers = [("1倍台", lambda o: o < 2.0), ("2倍台", lambda o: 2.0 <= o < 3.0),
             ("3倍以上", lambda o: o >= 3.0)]
    for tname, pred in tiers:
        sub = sorted((r for r in rows if pred(r["1人気オッズ"])),
                     key=lambda r: r["エントロピー"])
        if len(sub) < 20:
            continue
        half = len(sub) // 2
        summarize(sub[:half], f"{tname}・集中側")
        summarize(sub[half:], f"{tname}・拮抗側")
        print()

    print("── 相関（エントロピーと馬連配当の対数） " + "─" * 25)
    pairs = [(r["エントロピー"], math.log(r["馬連配当"])) for r in rows if r["馬連配当"]]
    if len(pairs) > 10:
        xs = [a for a, _ in pairs]
        ys = [b for _, b in pairs]
        print(f"n={len(pairs)}  相関係数 r = {statistics.correlation(xs, ys):+.3f}")
    pairs2 = [(math.log(r["1人気オッズ"]), math.log(r["馬連配当"])) for r in rows if r["馬連配当"]]
    if len(pairs2) > 10:
        xs = [a for a, _ in pairs2]
        ys = [b for _, b in pairs2]
        print(f"参考: log(1番人気オッズ) との相関 r = {statistics.correlation(xs, ys):+.3f}")


if __name__ == "__main__":
    main()
