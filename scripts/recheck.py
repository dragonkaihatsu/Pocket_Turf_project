#!/usr/bin/env python3
"""終わったレースを現在のスコアリングで採点し直し、実結果と突き合わせる。

「システムを直した結果、あのレースは当たるようになったのか」を測る。

後知恵の排除:
    馬別戦績にはそのレース当日の結果も含まれるため、必ず --date を渡して
    それより前の戦績だけを使う。渡さないと当日の着順を見て採点してしまう。

    python3 scripts/recheck.py --date 2026-09-03 --venue 大井 --races 10-12
"""
from __future__ import annotations

import argparse
import csv
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.betting import make_betting_plan
from keiba.marks import assign_marks
from keiba.models import load_horses
from keiba.scoring import score_race

STAKE = 100


def load_result(path: Path) -> tuple[list[int], dict[str, dict]]:
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8"))
            if (r.get("着順") or "").isdigit()]
    rows.sort(key=lambda r: int(r["着順"]))
    order = [int(r["馬番"]) for r in rows if (r.get("馬番") or "").isdigit()]
    pay: dict[str, dict] = {}
    p = path.with_name(path.name.replace("_結果.csv", "_配当.csv"))
    if p.exists():
        for r in csv.DictReader(open(p, encoding="utf-8")):
            try:
                combo = frozenset(int(x) for x in r["組み合わせ"].split("-"))
                pay.setdefault(r["券種"], {})[combo] = int(r["配当"])
            except ValueError:
                continue
    return order, pay


def settle(kind: str, tickets: list[frozenset], order: list[int],
           pay: dict) -> tuple[int, int, list[str]]:
    top2, top3 = frozenset(order[:2]), frozenset(order[:3])
    table = pay.get(kind, {})
    ret, hits = 0, []
    for t in tickets:
        hit = (t <= top3) if kind == "ワイド" else (
            t == top2 if kind == "馬連" else t == top3)
        if hit:
            amount = table.get(t, 0)
            ret += amount
            hits.append("-".join(str(x) for x in sorted(t))
                        + (f"({amount}円)" if amount else "(配当不明)"))
    return len(tickets) * STAKE, ret, hits


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--venue", default="大井")
    ap.add_argument("--races", default="10-12")
    ap.add_argument("--entries-dir", default="data")
    ap.add_argument("--results-dir", default="data/collected")
    ap.add_argument("--race-info", default="data/race_info.csv")
    args = ap.parse_args()

    lo, hi = (args.races.split("-") + [None])[:2]
    numbers = [int(x) for x in args.races.split(",")] if hi is None \
        else list(range(int(lo), int(hi) + 1))

    from keiba.cli import _load_horse_records
    records = _load_horse_records()

    kyori_by_no: dict[int, int] = {}
    info = Path(args.race_info)
    if info.exists():
        for row in csv.DictReader(open(info, encoding="utf-8")):
            if row["stem"].startswith(f"{args.date}_{args.venue}") and (row.get("距離") or "").isdigit():
                kyori_by_no[int(row["stem"].split("_")[1][len(args.venue):][:2])] = int(row["距離"])

    grand_inv = grand_ret = 0
    for no in numbers:
        ent = next(Path(args.entries_dir).glob(f"{args.date}_{args.venue}{no:02d}R_*_出走馬.csv"), None)
        res = next(Path(args.results_dir).glob(f"{args.date}_{args.venue}{no:02d}R_*_結果.csv"), None)
        if ent is None or res is None:
            print(f"{no}R: 出走馬または結果が見つかりません")
            continue

        horses = load_horses(ent)
        kyori = kyori_by_no.get(no)
        scores = score_race(horses, None, kyori=kyori,
                            records=records, as_of=args.date)
        marked = assign_marks(scores, baba="良")
        order, pay = load_result(res)
        name_of = {h.umaban: h.name for h in horses}
        mark_of = {m.score.horse.umaban: m.mark for m in marked}
        cover = sum(1 for h in horses if records and h.name in records)

        fav = min((h for h in horses if h.ninki), key=lambda h: h.ninki, default=None)
        plan = make_betting_plan(marked, baba="良",
                                 favorite_odds=fav.tansho_odds if fav else None)

        print("=" * 70)
        print(f"■ {no}R（{kyori}m・戦績データ {cover}/{len(horses)}頭）")
        print("  確定: " + " → ".join(
            f"{u}{name_of.get(u, '')}({mark_of.get(u, '無')})" for u in order[:3]))
        print("  新スコア上位: " + " ".join(
            f"{m.mark}{m.score.horse.umaban}{m.score.horse.name}" for m in marked[:5]))

        top4 = [m.score.horse.umaban for m in marked[:4]]
        top3n = [m.score.horse.umaban for m in marked[:3]]
        candidates = {
            f"{plan.strategy}型（システム）": (
                ("ワイド", [frozenset(m.score.horse.umaban for m in t.horses)
                            for t in plan.wide]) if plan.wide
                else ("馬連", [frozenset(m.score.horse.umaban for m in t.horses)
                               for t in plan.umaren])),
            "馬連 上位4頭BOX(6点)": ("馬連", [frozenset(c) for c in combinations(top4, 2)]),
            "ワイド 上位3頭BOX(3点)": ("ワイド", [frozenset(c) for c in combinations(top3n, 2)]),
        }
        for label, (kind, tickets) in candidates.items():
            inv, ret, hits = settle(kind, tickets, order, pay)
            mark = "的中" if ret else "不的中"
            print(f"    {label:<22}{kind} {len(tickets)}点 {inv:>5}円 → "
                  f"{ret:>6}円 {mark} {' '.join(hits)}")
            if label.endswith("（システム）"):
                grand_inv += inv
                grand_ret += ret

    if grand_inv:
        print("=" * 70)
        print(f"システムの型どおり3レース合計: {grand_inv}円 → {grand_ret}円"
              f"（回収率 {grand_ret / grand_inv:.0%}）")


if __name__ == "__main__":
    main()
