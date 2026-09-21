#!/usr/bin/env python3
"""レース水準の表（予想時に引く）を作る。通信ゼロ。

    python3 scripts/build_race_level.py --races 1-12 \
        --out data/profiles/jra/race_levels.json

水準の定義・検算・分解の実測は `keiba/racelevel.py` の冒頭と
`scripts/race_level.py` にある。**計算は `keiba.racelevel.build_levels` を
通す**（測る側と作る側で同じ計算を2か所に書くと静かにずれる）。
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import profile
from keiba.racelevel import (CLASS_ORDER, GRADE_ORDER, build_levels,
                             class_label, save_table)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="1-12",
                    help="水準を作る帯。既定1-12（前走が平場の走りも水準が要る）")
    ap.add_argument("--months", default=None)
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--base-times", default="data/profiles/jra/base_times.json")
    ap.add_argument("--out", default="data/profiles/jra/race_levels.json")
    ap.add_argument("--csv", default=None,
                    help="分析用に全列のCSVも書く（既定は書かない）")
    args = ap.parse_args()

    profile.assert_same_profile(args.dir, args.out)

    races, _ = build_levels(args.dir, args.races, args.months,
                            args.race_info, args.base_times)
    save_table(races, args.out)
    print(f"{len(races):,}レースの水準を {args.out} に書いた\n")

    print(f"{'クラス':<8}{'n':>7}{'水準(中央値)':>14}{'言い換え':>16}")
    for c in CLASS_ORDER:
        vs = [r["水準"] for r in races.values() if r["クラス"] == c]
        if vs:
            m = statistics.median(vs)
            print(f"{c:<8}{len(vs):>7,}{m:>+14.3f}{class_label(m):>16}")
    print()
    print(f"{'等級':<8}{'n':>7}{'水準(中央値)':>14}")
    for g in GRADE_ORDER:
        vs = [r["水準"] for r in races.values() if r["等級"] == g]
        if vs:
            print(f"{g:<8}{len(vs):>7,}{statistics.median(vs):>+14.3f}")
    print("→ 等級は単調に並ばない。**オープン以上の格は時計では測れない**")

    if args.csv:
        cols = ["stem", "日付", "場", "R", "芝ダ", "距離", "馬場", "レース名",
                "クラス", "等級", "頭数", "指数頭数", "水準", "勝ち馬指数"]
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in sorted(races.values(), key=lambda r: r["stem"]):
                w.writerow({k: (f"{r[k]:.4f}" if isinstance(r[k], float)
                                else r[k]) for k in cols})
        print(f"\n分析用CSVを {out} に書いた")


if __name__ == "__main__":
    main()
