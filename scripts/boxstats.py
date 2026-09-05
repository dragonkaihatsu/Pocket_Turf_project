#!/usr/bin/env python3
"""点数別（上位n頭BOX）の実測成績を測り、data/box_stats.json に保存する。

予想画面に「4頭なら/5頭なら/6頭なら」を並べて出すための裏付け。
どれを選ぶかは買う人が決めるべきなので、システムの推奨だけでなく
各幅の実測値を併記できるようにする。

    python3 scripts/boxstats.py --races 9-12 --ratings <path>
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keiba.scoring as sc
import re
from backtest import (load_race, load_race_info, parse_races, race_date,
                      race_number, race_venue, settle)
from keiba.cli import _load_horse_records
from keiba.marks import assign_marks

WIDTHS = (3, 4, 5, 6)
KINDS = ("ワイド", "馬連")


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
    ap.add_argument("--dir", default="data/collected")
    ap.add_argument("--races", default="9-12")
    ap.add_argument("--ratings")
    ap.add_argument("--race-info", default="data/race_info.csv")
    ap.add_argument("--out", default="data/box_stats.json")
    args = ap.parse_args()

    if args.ratings:
        table = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
        sc.load_ratings = lambda *a, **k: table

    wanted = parse_races(args.races)
    kyori_by = load_race_info(args.race_info)
    records = _load_horse_records()
    d = Path(args.dir)

    series: dict[tuple, list] = {}
    used = 0
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
                               records=records, as_of=race_date(stem),
                               venue=race_venue(stem))
        marked = assign_marks(scores, baba="良")
        if len(marked) < max(WIDTHS):
            continue
        used += 1
        order = [m.score.horse.umaban for m in marked]
        tier = ("1倍台" if fav.tansho_odds < 2.0
                else "2倍台" if fav.tansho_odds < 3.0 else "3倍以上")
        for kind in KINDS:
            for w in WIDTHS:
                tickets = [frozenset(c) for c in combinations(order[:w], 2)]
                for scope in ("全体", tier):
                    series.setdefault((kind, w, scope), []).append(
                        settle(kind, tickets, race))

    payload = {"生成日": date.today().isoformat(), "対象": f"大井{args.races}R",
               "レース数": used, "点数別": {}}
    for (kind, w, scope), pairs in sorted(series.items()):
        inv = sum(i for i, _ in pairs)
        ret = sum(r for _, r in pairs)
        hit = sum(1 for _, r in pairs if r > 0)
        lo, hi, win = bootstrap(pairs)
        payload["点数別"].setdefault(kind, {}).setdefault(str(w), {})[scope] = {
            "n": len(pairs), "点数": len(list(combinations(range(w), 2))),
            "的中率": round(hit / len(pairs), 4), "回収率": round(ret / inv, 4),
            "区間下": round(lo, 4), "区間上": round(hi, 4), "黒字確率": round(win, 4),
        }

    out = Path(args.out)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{used}レースから作成 → {out}\n")
    print(f"{'券種':<6}{'頭数':>4}{'点数':>5}  {'帯':<8}{'的中率':>7}{'回収率':>7}"
          f"{'90%区間':>18}{'黒字確率':>9}")
    for kind in KINDS:
        for w in WIDTHS:
            for scope in ("全体", "1倍台", "2倍台", "3倍以上"):
                r = payload["点数別"][kind][str(w)].get(scope)
                if not r:
                    continue
                span = f"{r['区間下']:.0%} 〜 {r['区間上']:.0%}"
                print(f"{kind:<6}{w:>4}{r['点数']:>5}  {scope:<8}{r['的中率']:>7.0%}"
                      f"{r['回収率']:>7.0%}{span:>18}{r['黒字確率']:>9.0%}")
        print()


if __name__ == "__main__":
    main()
