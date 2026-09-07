#!/usr/bin/env python3
"""3連単の高額配当が出たレースを条件別に集計する。

100万馬券は珍しい（9-12Rで約3%）ため、率だけ見ると母数不足で
いくらでも「傾向」が作れてしまう。そこで必ず

    - 母数(レース数)と実際の本数を併記する
    - Wilson信頼区間を付ける
    - 3連単配当の中央値も併記する（裾の1本に振り回されない指標）
    - 前半2年(2023-24)と後半2年(2025-26)で再現するか確かめる

    python3 scripts/oana.py --profile jra
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BANDS = [(1_000_000, "100万↑"), (500_000, "50万↑"), (100_000, "10万↑")]


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - s) / d, (c + s) / d


def race_number(stem):
    m = re.search(r"_\D+?(\d{2})R_", stem)
    return int(m.group(1)) if m else None


def race_venue(stem):
    m = re.search(r"_(\D+?)\d{2}R_", stem)
    return m.group(1) if m else ""


def dist_band(k):
    if not k:
        return ""
    k = int(k)
    return "〜1400m" if k <= 1400 else "1401-1800m" if k <= 1800 else "1801m〜"


def head_band(n):
    if not n:
        return ""
    n = int(n)
    return "〜9頭" if n <= 9 else "10-12頭" if n <= 12 else "13-15頭" if n <= 15 else "16頭〜"


def odds_band(o):
    if not o:
        return "不明"
    return "1倍台" if o < 2 else "2倍台" if o < 3 else "3倍台" if o < 4 else "4倍〜"


def load(directory: Path, info: dict, races: set[int]):
    out = []
    for p in sorted(directory.glob("*_配当.csv")):
        stem = p.name[: -len("_配当.csv")]
        rn = race_number(stem)
        if rn is None or rn not in races:
            continue
        santan = None
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            if r.get("券種") == "3連単":
                try:
                    santan = int(r["配当"])
                except (ValueError, TypeError):
                    pass
                break
        if santan is None:
            continue

        # 1番人気の単勝オッズ（発走前に分かる唯一の信頼度指標）
        fav = None
        ent = directory / f"{stem}_出走馬.csv"
        if ent.exists():
            best = None
            for e in csv.DictReader(open(ent, encoding="utf-8-sig")):
                try:
                    nk, od = int(e["人気"]), float(e["単勝オッズ"])
                except (ValueError, TypeError, KeyError):
                    continue
                if best is None or nk < best[0]:
                    best = (nk, od)
            if best:
                fav = best[1]

        m = info.get(stem, {})
        out.append({
            "stem": stem, "year": stem[:4], "配当": santan,
            "開催場": race_venue(stem),
            "馬場種別": m.get("馬場種別", "") or "不明",
            "馬場": m.get("馬場", "") or "不明",
            "天候": m.get("天候", "") or "不明",
            "距離帯": dist_band(m.get("距離")),
            "頭数帯": head_band(m.get("頭数")),
            "クラス": m.get("クラス", "") or "不明",
            "格": m.get("格") or "平場",
            "斤量条件": m.get("斤量条件", "") or "不明",
            "1番人気オッズ帯": odds_band(fav),
            "R": f"{rn}R",
        })
    return out


def tabulate(rows, key, threshold, title=None, min_n=40):
    groups = defaultdict(list)
    for r in rows:
        v = r.get(key)
        if v:
            groups[v].append(r)
    lines = []
    for name, g in groups.items():
        n = len(g)
        if n < min_n:
            continue
        k = sum(1 for r in g if r["配当"] >= threshold)
        lo, hi = wilson(k, n)
        lines.append({
            "name": name, "n": n, "k": k, "rate": k / n, "lo": lo, "hi": hi,
            "med": statistics.median(r["配当"] for r in g),
        })
    lines.sort(key=lambda x: -x["rate"])
    label = title or key
    print(f"\n── {label}（3連単{threshold:,}円以上の出現率） " + "─" * 12)
    print(f"{'区分':<12}{'R数':>6}{'本数':>5}{'出現率':>7}{'95%区間':>15}"
          f"{'3連単配当の中央値':>18}")
    for d in lines:
        ci = f"{d['lo']:.1%}〜{d['hi']:.1%}"
        print(f"{d['name']:<12}{d['n']:>6}{d['k']:>5}{d['rate']:>7.1%}"
              f"{ci:>15}{d['med']:>18,.0f}")
    return lines


def reproduce(rows, key, threshold, min_n=40):
    """前半2年と後半2年で順位が再現するかを見る。"""
    early = [r for r in rows if r["year"] in ("2023", "2024")]
    late = [r for r in rows if r["year"] in ("2025", "2026")]
    def rate(part, name):
        g = [r for r in part if r.get(key) == name]
        if len(g) < min_n // 2:
            return None, len(g)
        return sum(1 for r in g if r["配当"] >= threshold) / len(g), len(g)
    names = {r[key] for r in rows if r.get(key)}
    out = []
    for name in names:
        a, na = rate(early, name)
        b, nb = rate(late, name)
        if a is None or b is None:
            continue
        out.append((name, a, na, b, nb))
    if not out:
        return
    out.sort(key=lambda x: -(x[1] + x[3]))
    print(f"\n  前半(2023-24) 対 後半(2025-26) — {key}")
    print(f"  {'区分':<12}{'前半':>16}{'後半':>16}{'向き':>6}")
    for name, a, na, b, nb in out:
        same = "○" if (a >= 0.03) == (b >= 0.03) else "×"
        print(f"  {name:<12}{f'{a:.1%} (n={na})':>16}{f'{b:.1%} (n={nb})':>16}{same:>6}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["nar", "jra"], default="jra")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--races", default="9,10,11,12",
                    help="対象レース番号。既定は9-12R（収集帯を揃えるため）")
    ap.add_argument("--threshold", type=int, default=1_000_000)
    args = ap.parse_args()

    import keiba.profile as profile
    prof = profile.use(args.profile)
    info = {}
    p = prof.path("race_info.csv")
    if p.exists():
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            info[r["stem"]] = r

    d = Path(args.dir or ("data/collected" if args.profile == "nar"
                          else "data/collected_jra"))
    wanted = {int(x) for x in args.races.split(",")}
    rows = load(d, info, wanted)

    label = "中央" if args.profile == "jra" else "地方"
    print(f"{label} {args.races}R {len(rows)}レース（3連単の配当が取れたもの）")
    for th, nm in BANDS:
        k = sum(1 for r in rows if r["配当"] >= th)
        print(f"  {nm:<6} {k:>5}本  出現率 {k/len(rows):>5.1%}")
    print(f"  3連単配当の中央値 {statistics.median(r['配当'] for r in rows):,.0f}円")

    for key in ("1番人気オッズ帯", "頭数帯", "馬場", "馬場種別", "距離帯",
                "クラス", "格", "斤量条件", "開催場", "R", "天候"):
        tabulate(rows, key, args.threshold)

    print("\n" + "=" * 66)
    print("再現性チェック（前半2年 対 後半2年）")
    print("=" * 66)
    for key in ("1番人気オッズ帯", "頭数帯", "馬場種別", "距離帯", "クラス"):
        reproduce(rows, key, args.threshold)


if __name__ == "__main__":
    main()
