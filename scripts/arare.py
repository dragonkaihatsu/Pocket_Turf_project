#!/usr/bin/env python3
"""荒れ方を2つの型に分けて数える。

  A型「人気馬が飛んだ」  1番人気が着外。ただし3着内は9番人気以内で収まる
  B型「二桁人気が突入」  3着以内に10番人気以下がいる
  AB型                 その両方
  C型「相手が中穴」     1番人気は来たのに配当が跳ねた

型は重なるので、必ず4つに排他分類してから数える。
「どちらが多いか」は万馬券の中での構成比で見る。

    python3 scripts/arare.py --profile jra
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MANBAKEN = 10_000       # 馬連がこの額以上を「万馬券」とする
HITOKETA = 10           # この人気以下を「二桁人気」とする


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


def _num(x, default=None):
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return default


def load(directory: Path, info: dict, races: set[int]):
    out = []
    for p in sorted(directory.glob("*_結果.csv")):
        stem = p.name[: -len("_結果.csv")]
        rn = race_number(stem)
        if rn is None or rn not in races:
            continue
        rows = [r for r in csv.DictReader(open(p, encoding="utf-8-sig"))
                if (r.get("着順") or "").isdigit()]
        if len(rows) < 5:
            continue
        rows.sort(key=lambda r: int(r["着順"]))
        top3 = rows[:3]
        ninki = [_num(r.get("人気")) for r in top3]
        if any(n is None for n in ninki):
            continue

        pay = directory / f"{stem}_配当.csv"
        umaren = santan = None
        if pay.exists():
            for q in csv.DictReader(open(pay, encoding="utf-8-sig")):
                v = _num(q.get("配当"))
                if v is None:
                    continue
                if q.get("券種") == "馬連" and umaren is None:
                    umaren = v
                elif q.get("券種") == "3連単" and santan is None:
                    santan = v
        if umaren is None:
            continue

        # 全出走馬のオッズからエントロピー（市場がどれだけ割れているか）
        odds = sorted(o for o in (_num(r.get("単勝オッズ")) for r in rows) if o)
        ent = 0.0
        if len(odds) > 1:
            inv = [1 / o for o in odds]
            s = sum(inv)
            ps = [x / s for x in inv]
            ent = -sum(q * math.log(q) for q in ps if q > 0) / math.log(len(ps))

        fav_chaku = next((int(r["着順"]) for r in rows
                          if _num(r.get("人気")) == 1), None)
        m = info.get(stem, {})
        out.append({
            "stem": stem, "year": stem[:4], "開催場": race_venue(stem),
            "R": rn, "馬連": umaren, "3連単": santan,
            "1番人気の着順": fav_chaku,
            "1番人気着外": fav_chaku is None or fav_chaku > 3,
            "二桁人気が着内": any(n >= HITOKETA for n in ninki),
            "3着内の最低人気": max(ninki),
            "勝ち馬の人気": ninki[0],
            "エントロピー": ent,
            "頭数": _num(m.get("頭数")) or len(rows),
            "馬場種別": m.get("馬場種別", "") or "不明",
            "1番人気オッズ": odds[0] if odds else None,
        })
    return out


def classify(r):
    if r["1番人気着外"] and r["二桁人気が着内"]:
        return "AB型 両方"
    if r["1番人気着外"]:
        return "A型 人気馬が飛んだ"
    if r["二桁人気が着内"]:
        return "B型 二桁人気が突入"
    return "C型 相手が中穴"


ORDER = ["A型 人気馬が飛んだ", "B型 二桁人気が突入", "AB型 両方", "C型 相手が中穴"]


def breakdown(title, rows, key="馬連"):
    print(f"\n── {title}（{len(rows)}レース）" + "─" * 20)
    if not rows:
        return
    c = Counter(classify(r) for r in rows)
    print(f"{'型':<18}{'R数':>6}{'構成比':>8}{'馬連中央値':>12}"
          f"{'3連単中央値':>13}{'頭数':>6}{'ｴﾝﾄﾛﾋﾟｰ':>9}")
    for name in ORDER:
        g = [r for r in rows if classify(r) == name]
        if not g:
            continue
        st = [r["3連単"] for r in g if r["3連単"]]
        print(f"{name:<18}{len(g):>6}{len(g)/len(rows):>8.1%}"
              f"{statistics.median(r['馬連'] for r in g):>12,.0f}"
              f"{statistics.median(st) if st else 0:>13,.0f}"
              f"{statistics.median(r['頭数'] for r in g):>6.0f}"
              f"{statistics.mean(r['エントロピー'] for r in g):>9.3f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["nar", "jra"], default="jra")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--races", default="9,10,11,12")
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
    rows = load(d, info, {int(x) for x in args.races.split(",")})
    label = "中央" if args.profile == "jra" else "地方"
    print(f"{label} {args.races}R {len(rows)}レース")

    n_fav = sum(1 for r in rows if r["1番人気着外"])
    n_hit = sum(1 for r in rows if r["二桁人気が着内"])
    print(f"1番人気が着外          {n_fav:>5}レース ({n_fav/len(rows):.1%})")
    print(f"3着内に二桁人気がいる  {n_hit:>5}レース ({n_hit/len(rows):.1%})")

    breakdown("全レース", rows)
    man = [r for r in rows if r["馬連"] >= MANBAKEN]
    breakdown(f"万馬券（馬連{MANBAKEN:,}円以上）", man)
    big = [r for r in rows if r["3連単"] and r["3連単"] >= 1_000_000]
    breakdown("3連単100万馬券", big)

    print("\n── 型ごとの万馬券化率（その型になったとき、いくらの確率で万馬券か）")
    print(f"{'型':<18}{'R数':>6}{'万馬券':>7}{'率':>7}{'95%区間':>15}")
    for name in ORDER:
        g = [r for r in rows if classify(r) == name]
        if not g:
            continue
        k = sum(1 for r in g if r["馬連"] >= MANBAKEN)
        lo, hi = wilson(k, len(g))
        print(f"{name:<18}{len(g):>6}{k:>7}{k/len(g):>7.1%}"
              f"{f'{lo:.0%}〜{hi:.0%}':>15}")

    print("\n── 年ごとの構成比（万馬券の中で）")
    print(f"{'年':<8}" + "".join(f"{n.split()[0]:>10}" for n in ORDER) + f"{'R数':>7}")
    for y in sorted({r["year"] for r in rows}):
        g = [r for r in man if r["year"] == y]
        if not g:
            continue
        c = Counter(classify(r) for r in g)
        print(f"{y:<8}" + "".join(f"{c[n]/len(g):>10.0%}" for n in ORDER)
              + f"{len(g):>7}")

    print("\n── 頭数帯ごとの構成比（万馬券の中で）")
    def band(n):
        n = int(n)
        return "〜12頭" if n <= 12 else "13-15頭" if n <= 15 else "16頭〜"
    print(f"{'頭数':<10}" + "".join(f"{n.split()[0]:>10}" for n in ORDER) + f"{'R数':>7}")
    for b in ("〜12頭", "13-15頭", "16頭〜"):
        g = [r for r in man if band(r["頭数"]) == b]
        if not g:
            continue
        c = Counter(classify(r) for r in g)
        print(f"{b:<10}" + "".join(f"{c[n]/len(g):>10.0%}" for n in ORDER)
              + f"{len(g):>7}")


if __name__ == "__main__":
    main()
