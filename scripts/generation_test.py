#!/usr/bin/env python3
"""世代の強さを、同じ年齢・同じ時期・同じ人気帯で比べる。

「4歳世代は幅広いメンバー、3歳世代は世代間ではあまり強くなさそう」（本人の
言葉・2026-09-12）を測る。世代同士を直接は比べられないので、

  2025年の3歳（クロワデュノール・ジョバンニ世代 ＝ 2026年の4歳）
  2026年の3歳（ロブチェン・マテンロウゲイル世代）

を **同じ3歳という年齢・同じ6〜9月・同じ人気帯** で並べる。古馬混合戦だけを
対象にするのは、世代限定戦では世代間の比較にならないため。混合戦かどうかは
レース名ではなく出走馬の年齢構成から判定する（レース名の表記ゆれを踏まない）。

6〜9月に限るのは、2026年が9月までしか収集できていないことと、3歳の斤量の
恩恵が月を追って減っていくため（実測で6月2.7kg → 12月1.0kg）。

    python3 scripts/generation_test.py
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.power import min_detectable_diff, wilson
from keiba.racefiles import DEFAULT_RACES, result_paths

BANDS = (("1-3番人気", 1, 3), ("4-5番人気", 4, 5), ("6-9番人気", 6, 9),
         ("10番人気以下", 10, 99), ("（全体）", 1, 99))


def load(directory: str, races: str) -> list[dict]:
    """古馬混合戦（3歳と4歳以上が同じレースに出ている）の延べ出走だけ返す。"""
    rows: list[dict] = []
    for path in result_paths(directory, races):
        text = str(path)
        m = re.search(r"(\d{4})-(\d{2})-\d{2}_", text)
        if not m:
            continue
        year, month = int(m.group(1)), int(m.group(2))
        runners = []
        with open(text, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                age = re.search(r"(\d+)$", (row.get("性齢") or "").strip())
                try:
                    chaku = int(row.get("着順"))
                    ninki = int(row.get("人気"))
                except (TypeError, ValueError):
                    continue
                if not age:
                    continue
                try:
                    kin = float(row.get("斤量"))
                except (TypeError, ValueError):
                    kin = None
                runners.append({"age": int(age.group(1)), "chaku": chaku,
                                "ninki": ninki, "year": year, "month": month, "kin": kin})
        ages = {r["age"] for r in runners}
        if 3 in ages and any(a >= 4 for a in ages):
            rows.extend(runners)
    return rows


def rate(rows: list[dict]) -> tuple[int, float, float]:
    n = len(rows)
    return n, sum(1 for r in rows if r["chaku"] == 1) / n, sum(1 for r in rows if r["chaku"] <= 3) / n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--months", default="6-9", help="比較する月の範囲")
    args = ap.parse_args()

    lo_m, hi_m = (int(x) for x in args.months.split("-"))
    rows = load(args.dir, args.races)
    print(f"古馬混合戦 延べ {len(rows):,}出走\n")

    print("■ 年齢別（全月・人気で統制していないので斤量と人気の効果が混ざる）")
    print(f"  {'年齢':<10}{'n':>7}{'勝率':>8}{'複勝率':>9}{'95%CI':>18}")
    groups = collections.defaultdict(list)
    for r in rows:
        groups["3歳" if r["age"] == 3 else ("4歳" if r["age"] == 4 else "5歳以上")].append(r)
    for key in ("3歳", "4歳", "5歳以上"):
        n, win, place = rate(groups[key])
        ci = wilson(int(place * n), n)
        print(f"  {key:<10}{n:>7,}{win * 100:>7.1f}%{place * 100:>8.1f}%"
              f"   [{ci[0] * 100:.1f}%-{ci[1] * 100:.1f}%]")

    print(f"\n■ 3歳の月別（斤量の恩恵が減っていく）")
    print(f"  {'月':<6}{'n':>7}{'勝率':>8}{'複勝率':>9}{'斤量差(古馬-3歳)':>20}")
    for month in range(1, 13):
        v = [r for r in groups["3歳"] if r["month"] == month]
        if len(v) < 30:
            print(f"  {month:>2}月  {len(v):>7,}   母数不足")
            continue
        n, win, place = rate(v)
        own = [r["kin"] for r in v if r["kin"]]
        old = [r["kin"] for r in rows if r["month"] == month and r["age"] >= 4 and r["kin"]]
        diff = (sum(old) / len(old) - sum(own) / len(own)) if own and old else 0.0
        print(f"  {month:>2}月  {n:>7,}{win * 100:>7.1f}%{place * 100:>8.1f}%{diff:>17.1f}kg")

    print(f"\n■ 世代比較: 同じ3歳・同じ{args.months}月・同じ人気帯")
    print("  2025の3歳 = クロワデュノール/ジョバンニ世代 / 2026の3歳 = ロブチェン世代")
    sub = [r for r in rows if lo_m <= r["month"] <= hi_m]
    print(f"  {'人気帯':<14}{'世代':<12}{'n':>7}{'勝率':>8}{'複勝率':>9}{'95%CI':>18}")
    for label, lo, hi in BANDS:
        cells = {}
        for year in (2025, 2026):
            v = [r for r in sub if r["age"] == 3 and r["year"] == year and lo <= r["ninki"] <= hi]
            if not v:
                continue
            n, win, place = rate(v)
            ci = wilson(int(round(place * n)), n)
            cells[year] = (n, place, ci)
            print(f"  {label:<14}{f'{year}の3歳':<12}{n:>7,}{win * 100:>7.1f}%{place * 100:>8.1f}%"
                  f"   [{ci[0] * 100:.1f}%-{ci[1] * 100:.1f}%]")
        if len(cells) == 2:
            n25, p25, _ = cells[2025]
            n26, p26, ci26 = cells[2026]
            mdd = min_detectable_diff(min(n25, n26), p25)
            code = "区別できない" if ci26[0] <= p25 <= ci26[1] else "差あり(境界)"
            print(f"  {'':<14}→ 複勝率 {(p26 - p25) * 100:+.1f}pt / "
                  f"この母数で見える差 {mdd * 100:.1f}pt / {code}")
        print()

    print("■ 対照: 古馬側も同じ2期間で（年ごとの馬場・配当差を切り分ける）")
    print(f"  {'年齢':<10}{'2025 n/複勝率':>20}{'2026 n/複勝率':>20}")
    for label, pred in (("4歳", lambda r: r["age"] == 4), ("5歳以上", lambda r: r["age"] >= 5)):
        cols = []
        for year in (2025, 2026):
            v = [r for r in sub if pred(r) and r["year"] == year]
            n, _, place = rate(v)
            cols.append(f"{n:,} / {place * 100:.1f}%")
        print(f"  {label:<10}{cols[0]:>20}{cols[1]:>20}")


if __name__ == "__main__":
    main()
