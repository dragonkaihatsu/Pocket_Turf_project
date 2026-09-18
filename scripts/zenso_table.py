#!/usr/bin/env python3
"""前走着順→素点（`ZENSO_TABLE`）を実測から作り直す。

    python3 scripts/zenso_table.py --races 1-12 --target-races 9-12

## なぜ作り直すか
CLAUDE.mdが繰り返し記録してきたとおり、**現行の表は上位で実測と順序が逆**:

    ZENSO_TABLE = {1:20, 2:17, 3:14, 4:11, 5:9}   6-9着=6  10着以下=3

しかし前走1着馬の今走複勝率は前走2着・3着より低い。前走1着は昇級初戦に
なりやすく、クラスの壁に当たるためで、本人が指摘した「昇級戦の壁」が
そのまま数字に出ている。**順序が逆の表は、前走1着馬を機械的に持ち上げる。**

## どう作るか（勘で決めない）
素点を**今走複勝率の線形写像**にする。写像の両端は現行の表と揃える
（最良=20点・最低=3点）ので、**項目の配点20点は変わらない**。変えるのは
配点ではなく順序と間隔だけで、これは持ち時計指数を入れたときと同じ方針
（「配点は変えない。変えたのは尺度＝何を測るかだけ」）。

    素点 = 3 + 17 × (その着順の複勝率 − 最低の複勝率) / (最高 − 最低)

## 乗り替わり補正も一緒に出し直す
`NORIKAE_KAKUAGE_POINTS` は「前走二桁の素点を前走6-9着の素点に読み替える」
大きさとして校正してある。表が変われば差も変わるので、**同じスクリプトで
両方を出す**（2か所に根拠を分けると静かにずれる）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import power
from keiba.racefiles import DEFAULT_RACES
from scripts.tenkai import build_pairs, load

# 現行表の両端。ここを動かすと配点が変わるので、既定では動かさない
LOW, HIGH = 3.0, 20.0
BUCKETS = [("1着", lambda c: c == 1), ("2着", lambda c: c == 2),
           ("3着", lambda c: c == 3), ("4着", lambda c: c == 4),
           ("5着", lambda c: c == 5),
           ("6-9着", lambda c: 6 <= c <= 9), ("10着以下", lambda c: c >= 10)]
CURRENT = {"1着": 20, "2着": 17, "3着": 14, "4着": 11, "5着": 9,
           "6-9着": 6, "10着以下": 3}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="1-12", help="履歴として読む帯")
    ap.add_argument("--target-races", default=DEFAULT_RACES, help="今走の帯")
    ap.add_argument("--low", type=float, default=LOW)
    ap.add_argument("--high", type=float, default=HIGH)
    a = ap.parse_args()

    pairs = build_pairs(load(a.dir, a.races), a.target_races)
    print(f"前走ペア {len(pairs):,}組"
          f"（履歴{a.races}R → 今走{a.target_races}R）\n")

    rates: dict[str, float] = {}
    print(f"{'前走着順':<10}{'n':>7}{'今走複勝率':>10}{'95%CI':>16}"
          f"{'現行':>6}{'実測ベース':>10}{'差':>7}")
    stats = []
    for label, pred in BUCKETS:
        rows = [cur for prev, cur in pairs if pred(prev["chaku"])]
        if not rows:
            continue
        hit = sum(1 for r in rows if r["chaku"] <= 3)
        rate = hit / len(rows)
        rates[label] = rate
        stats.append((label, len(rows), rate, power.wilson(hit, len(rows))))

    lo, hi = min(rates.values()), max(rates.values())
    new = {lab: a.low + (a.high - a.low) * (r - lo) / (hi - lo)
           for lab, r in rates.items()}

    for label, n, rate, ci in stats:
        cur, nx = CURRENT[label], new[label]
        print(f"{label:<10}{n:>7,}{rate:>10.1%}"
              f"  [{ci[0]:>5.1%}-{ci[1]:>5.1%}]"
              f"{cur:>6}{nx:>10.1f}{nx - cur:>+7.1f}")

    print("\n■ 書き換え案（keiba/scoring.py）")
    tbl = ", ".join(f"{i}: {new[f'{i}着']:.1f}" for i in range(1, 6))
    print(f"  ZENSO_TABLE = {{{tbl}}}")
    print(f"  6-9着  → {new['6-9着']:.1f}   10着以下 → {new['10着以下']:.1f}")

    gap = new["6-9着"] - new["10着以下"]
    print("\n■ 乗り替わり補正の校正（前走二桁 → 前走6-9着 相当への読み替え）")
    print(f"  現行 NORIKAE_KAKUAGE_POINTS = 3.0"
          f"（旧表の 6 − 3）")
    print(f"  新表では 6-9着{new['6-9着']:.1f} − 10着以下{new['10着以下']:.1f}"
          f" = {gap:.1f}")

    # 期間で割って順序が再現するか。1年ぶんの偶然で表を書き換えないため
    print("\n■ 期間再現（年で割った今走複勝率）")
    print(f"  {'前走着順':<10}{'2025 n':>9}{'複勝率':>8}{'2026 n':>9}{'複勝率':>8}")
    per: dict[str, list[float]] = {}
    for label, pred in BUCKETS:
        line, vals = f"  {label:<10}", []
        for y in ("2025", "2026"):
            rows = [cur for prev, cur in pairs
                    if pred(prev["chaku"]) and cur["date"].startswith(y)]
            if not rows:
                line += f"{0:>9}{'—':>8}"
                vals.append(None)
                continue
            r = sum(1 for x in rows if x["chaku"] <= 3) / len(rows)
            line += f"{len(rows):>9,}{r:>8.1%}"
            vals.append(r)
        per[label] = vals
        print(line)
    for i, y in enumerate(("2025", "2026")):
        got = [lab for lab in sorted(
            (k for k, v in per.items() if v[i] is not None),
            key=lambda k: -per[k][i])]
        print(f"  {y}の順序: {' > '.join(got)}")

    # 順序が実測どおりか（現行表が壊れている点の確認）
    order_now = sorted(CURRENT, key=lambda k: -CURRENT[k])
    order_real = sorted(rates, key=lambda k: -rates[k])
    print("\n■ 順序")
    print(f"  現行表: {' > '.join(order_now)}")
    print(f"  実測  : {' > '.join(order_real)}")
    print("  " + ("一致" if order_now == order_real else "**食い違っている**"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
