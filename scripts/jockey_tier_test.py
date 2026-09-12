#!/usr/bin/env python3
"""騎手の「一軍」判定を騎乗数で決めるか複勝率で決めるかを独立検証で比べる。

CLAUDE.md は一軍を `ratings.json` の騎乗数 n>=400 で定義している
（`keiba/scoring.py` の `is_tier1_jockey`）。騎乗数は「機会の多さ」であって
「複勝に持ってくる率」ではないため、この2つが同じものを指しているかを測る。

後知恵を避けるため、名簿は **2025年の騎乗だけ** から作り、**2026年で検証** する。
同じデータから上位を選んで同じデータで測ると、差は必ず出てしまう。

    python3 scripts/jockey_tier_test.py
    python3 scripts/jockey_tier_test.py --races 1-12   # 1-8Rの収集後に母数を増やす
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.power import min_detectable_diff, wilson
from keiba.racefiles import DEFAULT_RACES, result_paths

TIER1_RIDES = 400   # keiba/scoring.py の JOCKEY_TIER1_RIDES と同じ
TOP_N = 16          # 騎乗数400以上がちょうど16人なので人数を揃えて比べる
MIN_RIDES = 100     # 名簿を作る側の最低騎乗数（率が0/1に振れるのを避ける）
BANDS = (("1-3番人気", 1, 3), ("4-5番人気", 4, 5), ("6-9番人気", 6, 9), ("10番人気以下", 10, 99))


def load_rides(directory: str, races: str) -> list[dict]:
    rides: list[dict] = []
    for path in result_paths(directory, races):
        text = str(path)
        m = re.search(r"(\d{4})-\d{2}-\d{2}_", text)
        if not m:
            continue
        year = int(m.group(1))
        with open(text, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                try:
                    chaku = int(row.get("着順"))
                    ninki = int(row.get("人気"))
                except (TypeError, ValueError):
                    continue
                try:
                    odds = float(row.get("単勝オッズ"))
                except (TypeError, ValueError):
                    odds = None
                rides.append({
                    "jockey": (row.get("騎手") or "").strip(),
                    "chaku": chaku,
                    "ninki": ninki,
                    "year": year,
                    "odds": odds,
                })
    return rides


def place_rate_roster(rides: list[dict], top_n: int, min_rides: int) -> list[tuple[float, str, int]]:
    agg: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for r in rides:
        a = agg[r["jockey"]]
        a[0] += 1
        a[1] += r["chaku"] <= 3
    cand = [(a[1] / a[0], j, a[0]) for j, a in agg.items() if a[0] >= min_rides]
    return sorted(cand, reverse=True)[:top_n]


def judge(rides: list[dict], roster: set[str], lo: int, hi: int) -> dict | None:
    band = [r for r in rides if lo <= r["ninki"] <= hi]
    base = [r for r in band if r["jockey"] not in roster]
    test = [r for r in band if r["jockey"] in roster]
    if not base or not test:
        return None
    p_base = sum(1 for r in base if r["chaku"] <= 3) / len(base)
    hits = sum(1 for r in test if r["chaku"] <= 3)
    rate = hits / len(test)
    ci = wilson(hits, len(test))
    mdd = min_detectable_diff(len(test), p_base)
    if not ci[0] <= p_base <= ci[1]:
        code = "差あり"
    elif mdd <= 0.05:
        code = "差なし"
    else:
        code = "判定不能"
    return {"n": len(test), "n_base": len(base), "rate": rate, "p_base": p_base,
            "ci": ci, "mdd": mdd, "code": code}


def show(rides: list[dict], roster: set[str], title: str) -> None:
    print(f"  --- {title}")
    print(f"    {'人気帯':<14}{'n':>7}{'複勝率':>9}{'対照':>8}{'95%CI':>18}{'判定':>18}")
    for label, lo, hi in BANDS:
        v = judge(rides, roster, lo, hi)
        if not v:
            continue
        verdict = "%s %+.1fpt" % (v["code"], (v["rate"] - v["p_base"]) * 100)
        print(f"    {label:<14}{v['n']:>7,}{v['rate'] * 100:>8.1f}%{v['p_base'] * 100:>7.1f}%"
              f"   [{v['ci'][0] * 100:.1f}%-{v['ci'][1] * 100:.1f}%]{verdict:>18}")


def tansho_roi(rides: list[dict], roster: set[str], inside: bool) -> float:
    v = [r for r in rides if (r["jockey"] in roster) == inside and r["odds"]]
    if not v:
        return 0.0
    return sum(r["odds"] for r in v if r["chaku"] == 1) / len(v)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--ratings", default="data/profiles/jra/ratings.json",
                    help="騎乗数による一軍判定に使う実測表（プロファイル任せにしない）")
    args = ap.parse_args()

    rides = load_rides(args.dir, args.races)
    y2025 = [r for r in rides if r["year"] == 2025]
    y2026 = [r for r in rides if r["year"] == 2026]
    print(f"延べ {len(rides):,}騎乗  材料2025 {len(y2025):,} / 検証2026 {len(y2026):,}\n")

    ratings = json.load(open(args.ratings, encoding="utf-8"))["騎手"]
    by_rides = {j for j, v in ratings.items() if (v.get("n") or 0) >= TIER1_RIDES}
    print(f"■ 現行の一軍判定（{args.ratings} の騎乗数 {TIER1_RIDES} 以上・{len(by_rides)}人）")
    print("  " + " ".join(sorted(by_rides)))
    show(y2026, by_rides, "2026年（この名簿は全期間由来なので厳密な独立検証ではない）")
    print()

    roster = place_rate_roster(y2025, TOP_N, MIN_RIDES)
    by_place = {j for _, j, _ in roster}
    print(f"■ 2025年の複勝率で選んだ{TOP_N}人（2025の騎乗{MIN_RIDES}以上から選出）")
    print("  " + " ".join(f"{j}({r * 100:.0f}%/{n})" for r, j, n in roster))
    missing = sorted(by_place - by_rides)
    extra = sorted(by_rides - by_place)
    print(f"  現行判定に入っていない: {' '.join(missing) or 'なし'}")
    print(f"  現行判定にだけ入る    : {' '.join(extra) or 'なし'}")
    show(y2025, by_place, "2025年（材料・後知恵なので差が出るのは当然）")
    show(y2026, by_place, "2026年（独立検証）")
    print(f"  2026 単勝回収率: 名簿内 {tansho_roi(y2026, by_place, True) * 100:.0f}%"
          f" / 名簿外 {tansho_roi(y2026, by_place, False) * 100:.0f}%")
    print()

    print("■ 頑健性: 名簿の中身を削っても2026年の差が残るか")
    print(f"  {'区分':<30}{'帯':<14}{'n':>7}{'差':>9}{'判定':>10}")
    variants = [
        ("そのまま", by_place),
        ("上位2人を除く", by_place - {j for _, j, _ in roster[:2]}),
        ("上位4人を除く", by_place - {j for _, j, _ in roster[:4]}),
        ("下半分だけ", {j for _, j, _ in roster[TOP_N // 2:]}),
    ]
    for name, s in variants:
        for label, lo, hi in (("1-3番人気", 1, 3), ("10番人気以下", 10, 99)):
            v = judge(y2026, s, lo, hi)
            if not v:
                continue
            print(f"  {name:<30}{label:<14}{v['n']:>7,}"
                  f"{(v['rate'] - v['p_base']) * 100:>8.1f}pt{v['code']:>10}")


if __name__ == "__main__":
    main()
