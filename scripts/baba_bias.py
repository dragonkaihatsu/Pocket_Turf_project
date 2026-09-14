#!/usr/bin/env python3
"""当日の前半レースの「前残り/差し」傾向は、後半レースを予測するか。

CLAUDE.mdは以前からこう書いてきた:

  「渋った馬場=差し有利」と一律に決めつけない。**当日の他レースでの
   勝ち馬4角通過順・上がり3F傾向**（前残りか差し決着か）を確認してから
   脚質補正の方向を決める

**この規則自体は一度も検証していなかった。** 当日の前半を見るには
1-8Rが要るので、9-12Rだけ収集していた間は原理的に測れなかった。
21ヶ月ぶんの1-8Rが揃ったので初めて測れる。

## 測り方

各レースについて「**上位n着の馬が最終コーナーで何番手だったか**」を頭数で
正規化して平均する（0=先頭、1=最後方）。これを当日の前半(1-8R)と後半(9-12R)で
平均し、前半の値が後半の値を予測するかを見る。

最初は勝ち馬1頭だけで測ったが、**1レース1頭では雑音が大きい**（同じ日でも
偶然の逃げ切りが1本あれば前残り寄りに見える）。上位3着まで使うと1レース
あたりの推定が3倍の情報で決まる。既定は3着まで（`--top`）。

**距離とクラスの構造差を先に除く。** 1-8Rは短距離・下級条件が多く、
9-12Rは長距離・上級条件が多い。前残りのしやすさは距離でも変わるので、
生の平均を比べると「時間帯の差」を「馬場の差」と誤読する。そこで

    残差 = そのレースの値 − 同じ(競馬場 × 芝ダ × 距離帯)の全期間平均

を使う。残差の平均なら、その日その区分が普段より前残りか差しかだけが残る。

## 開催区分（競馬場 × 芝ダ）ごとに見る

芝が荒れるのは芝だけである。ダートと混ぜると薄まる。馬場の値と同じく
**開催区分が単位**（CLAUDE.md「競馬場ごと・芝ダートごとに馬場状態は別」）。

    python3 scripts/baba_bias.py --races 1-12
    python3 scripts/baba_bias.py --races 1-12 --surface 芝
"""
from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from keiba.power import wilson
from keiba.racefiles import (DEFAULT_RACES, race_month, race_number,
                             race_venue, result_files)
from roi_power import parse_corner


def dist_band(k: int) -> str:
    if k <= 1400:
        return "~1400"
    if k <= 1800:
        return "1401-1800"
    if k <= 2200:
        return "1801-2200"
    return "2201~"


def load_info(path: Path) -> dict[str, dict]:
    out = {}
    if path.exists():
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r.get("馬場種別") and (r.get("距離") or "").isdigit():
                    out[r["stem"]] = {"surface": r["馬場種別"],
                                      "kyori": int(r["距離"])}
    return out


def load_races(directory: str, races: str, info: dict,
               top_n: int = 3) -> list[dict]:
    """1レース1行。上位top_n着の最終コーナー位置を頭数で正規化して平均。"""
    out = []
    for p in result_files(directory, races):
        stem = p.name[: -len("_結果.csv")]
        meta = info.get(stem)
        if not meta:
            continue
        rows = [r for r in csv.DictReader(open(p, encoding="utf-8-sig"))
                if (r.get("着順") or "").isdigit()]
        if len(rows) < 8:          # 少頭数は位置取りの意味が変わる
            continue
        top = [r for r in rows
               if r["着順"].isdigit() and int(r["着順"]) <= top_n
               and (r.get("馬番") or "").isdigit()]
        if len(top) < top_n:
            continue
        try:
            cs = list(csv.DictReader(
                open(str(p).replace("_結果.csv", "_通過順.csv"),
                     encoding="utf-8-sig")))
        except FileNotFoundError:
            continue
        order = parse_corner(cs[-1].get("通過順") or "", len(rows)) if cs else None
        if not order or any(int(r["馬番"]) not in order for r in top):
            continue
        pos = statistics.mean(order.index(int(r["馬番"])) + 1 for r in top)
        out.append({
            "date": p.name[:10], "month": race_month(p.name),
            "venue": race_venue(p.name), "R": race_number(p.name),
            "surface": meta["surface"], "band": dist_band(meta["kyori"]),
            # 0=先頭で決着 / 1=最後方から差し決着
            "z": (pos - 1) / (len(order) - 1),
        })
    return out


def carryover(rs: list[dict], min_races: int = 4) -> None:
    """① 外差し馬場の**持ち越し**を測る（当日内ではなく日をまたぐ）。

    当日の前半→後半は予測しないと分かった（2026-09-13）。記事①は別の主張で、
    「**荒れた馬場は翌日・翌週にも残る**」と読める。芝が剥がれる物理は日を
    またいで残るはずなので、こちらのほうが筋は通る。

    1日1値（その開催区分の全レースの残差の平均）にして、
    **翌日（土→日）・翌週・2週後**とペアにする。同じ開催区分（競馬場×芝ダ）
    の中だけで組む。
    """
    from datetime import date as _date

    def ordinal(s: str) -> int:
        y, m, d = (int(x) for x in s.split("-"))
        return _date(y, m, d).toordinal()

    days: dict[tuple, list[float]] = defaultdict(list)
    for r in rs:
        days[(r["venue"], r["surface"], r["date"])].append(r["res"])
    per_day = {k: statistics.mean(v) for k, v in days.items()
               if len(v) >= min_races}
    print(f"\n開催区分×日 {len(per_day):,}件（1日{min_races}本以上）")

    by_vs: dict[tuple, list[tuple[int, float]]] = defaultdict(list)
    for (v, sf, d), z in per_day.items():
        by_vs[(v, sf)].append((ordinal(d), z))
    for k in by_vs:
        by_vs[k].sort()

    for lo, hi, label in ((1, 1, "翌日（土→日）"), (6, 8, "翌週"),
                          (13, 15, "2週後"), (20, 30, "3〜4週後（対照）")):
        pairs = []
        for lst in by_vs.values():
            for i, (o1, z1) in enumerate(lst):
                for o2, z2 in lst[i + 1:]:
                    if o2 - o1 > hi:
                        break
                    if lo <= o2 - o1 <= hi:
                        pairs.append((z1, z2))
        if len(pairs) < 30:
            print(f"■ {label}: {len(pairs)}件（母数不足）")
            continue
        n = len(pairs)
        a = [x[0] for x in pairs]
        b = [x[1] for x in pairs]
        ma, mb = statistics.mean(a), statistics.mean(b)
        r = (sum((x - ma) * (y - mb) for x, y in pairs) / (n - 1)
             / (statistics.stdev(a) * statistics.stdev(b)))
        srt = sorted(pairs)
        q = n // 3
        low = statistics.mean([y for _, y in srt[:q]])
        high = statistics.mean([y for _, y in srt[-q:]])
        same = sum(1 for x, y in pairs if (x > 0) == (y > 0))
        ci = wilson(same, n)
        print(f"■ {label}  {n}件")
        print(f"  相関 r = {r:+.3f}")
        print(f"  前が前残り寄り(下位1/3) → 次の日の残差 {low:+.3f}")
        print(f"  前が差し寄り  (上位1/3) → 次の日の残差 {high:+.3f}")
        print(f"  差 {high - low:+.3f}  向きが一致 {same/n:.1%} "
              f"[{ci[0]:.1%}-{ci[1]:.1%}]（偶然なら50%）")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="1-12")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--surface", help="芝 か ダ に絞る")
    ap.add_argument("--top", type=int, default=3,
                    help="バイアスの推定に使う着順（既定3＝上位3着の平均）。"
                         "1頭だけだと1レースあたりの雑音が大きい")
    ap.add_argument("--early", default="1-8",
                    help="「前半」とみなすレース番号（既定1-8）")
    ap.add_argument("--late", default="9-12",
                    help="「後半」とみなすレース番号（既定9-12）。"
                         "`--early 1-4 --late 5-8` にすると、条件が近く"
                         "時間差も同じ対照として使える")
    ap.add_argument("--min-early", type=int, default=3)
    ap.add_argument("--min-late", type=int, default=2)
    ap.add_argument("--carryover", action="store_true",
                    help="当日内の前半→後半ではなく、翌日・翌週への"
                         "持ち越しを測る（記事①）")
    ap.add_argument("--min-races", type=int, default=4,
                    help="--carryover で1日を1値にするのに要求するレース数")
    args = ap.parse_args()

    info = load_info(Path(args.race_info))
    rs = load_races(args.dir, args.races, info, args.top)
    if args.surface:
        rs = [r for r in rs if r["surface"] == args.surface]
    print(f"{len(rs):,}レース（上位{args.top}着の最終コーナー位置が読めたもの）")

    # 構造差を除く: 同じ 競馬場×芝ダ×距離帯 の全期間平均を基準にする
    base: dict[tuple, list[float]] = defaultdict(list)
    for r in rs:
        base[(r["venue"], r["surface"], r["band"])].append(r["z"])
    avg = {k: statistics.mean(v) for k, v in base.items() if len(v) >= 20}
    for r in rs:
        r["res"] = r["z"] - avg.get((r["venue"], r["surface"], r["band"]), None) \
            if (r["venue"], r["surface"], r["band"]) in avg else None
    rs = [r for r in rs if r["res"] is not None]

    def band_of(spec: str) -> set[int]:
        lo, hi = (int(x) for x in spec.split("-"))
        return set(range(lo, hi + 1))

    if args.carryover:
        carryover(rs, args.min_races)
        return

    early_rs, late_rs = band_of(args.early), band_of(args.late)
    days: dict[tuple, dict[str, list]] = defaultdict(
        lambda: {"early": [], "late": []})
    for r in rs:
        k = (r["date"], r["venue"], r["surface"])
        if r["R"] in early_rs:
            days[k]["early"].append(r["res"])
        elif r["R"] in late_rs:
            days[k]["late"].append(r["res"])

    pairs = [(k, statistics.mean(v["early"]), statistics.mean(v["late"]),
              len(v["early"]), len(v["late"]))
             for k, v in days.items()
             if len(v["early"]) >= args.min_early and len(v["late"]) >= args.min_late]
    print(f"前半={args.early}R / 後半={args.late}R")
    print(f"開催区分×日 {len(pairs):,}件（前半{args.min_early}本以上・"
          f"後半{args.min_late}本以上）\n")

    def report(label: str, sub: list) -> None:
        if len(sub) < 30:
            print(f"■ {label}: {len(sub)}件（母数不足）")
            return
        e = [x[1] for x in sub]
        l = [x[2] for x in sub]
        n = len(sub)
        me, ml = statistics.mean(e), statistics.mean(l)
        se = statistics.stdev(e)
        cov = sum((a - me) * (b - ml) for a, b in zip(e, l)) / (n - 1)
        r = cov / (se * statistics.stdev(l))
        # 前半が「差し寄り」だった日の後半（上位1/3 vs 下位1/3）
        srt = sorted(sub, key=lambda x: x[1])
        k = n // 3
        lo = statistics.mean([x[2] for x in srt[:k]])
        hi = statistics.mean([x[2] for x in srt[-k:]])
        # 後半が前半と同じ向き（どちらも平均より差し／どちらも前）だった割合
        same = sum(1 for a, b in zip(e, l) if (a > 0) == (b > 0)) / n
        ci = wilson(sum(1 for a, b in zip(e, l) if (a > 0) == (b > 0)), n)
        print(f"■ {label}  {n}件")
        print(f"  相関 r = {r:+.3f}")
        print(f"  前半が前残り寄り(下位1/3)の日 → 後半の残差 {lo:+.3f}")
        print(f"  前半が差し寄り  (上位1/3)の日 → 後半の残差 {hi:+.3f}")
        print(f"  差 {hi - lo:+.3f}（勝ち馬の位置が頭数の{abs(hi-lo)*100:.1f}%ぶん動く）")
        print(f"  前後半で向きが一致 {same:.1%} [{ci[0]:.1%}-{ci[1]:.1%}]"
              f"（偶然なら50%）")

    report("全体", pairs)
    for s in ("芝", "ダ"):
        report(f"{s}のみ", [x for x in pairs if x[0][2] == s])
    print()
    for y in ("2025", "2026"):
        report(f"{y}年・芝", [x for x in pairs
                            if x[0][2] == "芝" and x[0][0].startswith(y)])


if __name__ == "__main__":
    main()
