#!/usr/bin/env python3
"""「あの騎手は今年ダメ」「重賞では勝てない」といった感覚を実測で確かめる。

騎手の生の勝率は**乗る馬で決まる**ため、そのままでは比較にならない。
人気馬に乗る騎手は勝率が高いのが当たり前である。そこで

    期待勝利数 = Σ P(勝ち | その馬の人気)

を全データから作り、実際の勝利数と比べる。1.00を超えれば
「与えられた馬から期待される以上に勝った」ことになる。

    python3 scripts/jinx.py --jockey 川田 --by-year
    python3 scripts/jinx.py --jockey 横山武 --by-grade
    python3 scripts/jinx.py --age3
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - s) / d, (c + s) / d


def _num(x, default=None):
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return default


def race_number(stem):
    m = re.search(r"_\D+?(\d{2})R_", stem)
    return int(m.group(1)) if m else None


def load(directory: Path, info: dict, races: set[int]):
    """1行1頭。着順・人気・騎手・年齢と、レース条件をまとめる。"""
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
        m = info.get(stem, {})
        kyori = _num(m.get("距離"))
        grade = (m.get("格") or "").strip()
        for r in rows:
            nk = _num(r.get("人気"))
            if not nk:
                continue
            sei = (r.get("性齢") or "").strip()
            age = _num(sei[1:]) if len(sei) > 1 else None
            odds = _num(r.get("単勝オッズ"))
            out.append({
                "year": stem[:4], "stem": stem,
                "着順": int(r["着順"]), "人気": int(nk),
                "単勝オッズ": odds,
                "騎手": (r.get("騎手") or "").strip(),
                "年齢": age,
                "距離": kyori,
                "重賞": bool(grade and grade.startswith(("G", "Jpn"))),
                "格": grade or "平場",
                "クラス": m.get("クラス", ""),
                "頭数": len(rows),
            })
    return out


def baseline(rows):
    """人気ごとの勝率・複勝率。期待値の物差しにする。"""
    win = defaultdict(lambda: [0, 0])
    plc = defaultdict(lambda: [0, 0])
    for r in rows:
        k = min(r["人気"], 18)
        win[k][1] += 1
        plc[k][1] += 1
        if r["着順"] == 1:
            win[k][0] += 1
        if r["着順"] <= 3:
            plc[k][0] += 1
    return ({k: a / b for k, (a, b) in win.items() if b},
            {k: a / b for k, (a, b) in plc.items() if b})


def report(title, rows, pwin, pplc, min_n=30):
    n = len(rows)
    if n < min_n:
        print(f"  {title:<16}{n:>6}騎乗  ← 母数不足のため判断しない")
        return
    w = sum(1 for r in rows if r["着順"] == 1)
    p3 = sum(1 for r in rows if r["着順"] <= 3)
    ew = sum(pwin.get(min(r["人気"], 18), 0) for r in rows)
    ep = sum(pplc.get(min(r["人気"], 18), 0) for r in rows)
    ret = sum(r["単勝オッズ"] * 100 for r in rows
              if r["着順"] == 1 and r["単勝オッズ"])
    lo, hi = wilson(w, n)
    print(f"  {title:<16}{n:>6}{w/n:>8.1%}{f'{lo:.0%}〜{hi:.0%}':>14}"
          f"{p3/n:>8.1%}{w/ew if ew else 0:>8.2f}{p3/ep if ep else 0:>8.2f}"
          f"{ret/(n*100):>8.0%}")


HEAD = (f"  {'区分':<16}{'騎乗':>6}{'勝率':>8}{'95%区間':>14}"
        f"{'複勝率':>8}{'勝/期待':>8}{'複/期待':>8}{'単回収':>8}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["nar", "jra"], default="jra")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--races", default="9,10,11,12")
    ap.add_argument("--jockey", action="append", default=[])
    ap.add_argument("--by-year", action="store_true")
    ap.add_argument("--by-grade", action="store_true")
    ap.add_argument("--age3", action="store_true", help="3歳馬の古馬混合戦での通用度")
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
    pwin, pplc = baseline(rows)
    print(f"母数 {len(rows):,}頭 / {len({r['stem'] for r in rows}):,}レース")
    print("勝/期待 = 実際の勝利数 ÷ 人気から計算した期待勝利数。"
          "1.00超なら馬の格以上に勝っている\n")

    for j in args.jockey:
        g = [r for r in rows if r["騎手"] == j]
        if not g:
            print(f"『{j}』の騎乗が見つかりません")
            continue
        print(f"═══ {j}騎手（9-12R）")
        print(HEAD)
        report("通算", g, pwin, pplc)
        if args.by_year:
            for y in sorted({r["year"] for r in g}):
                report(f"{y}年", [r for r in g if r["year"] == y], pwin, pplc)
        if args.by_grade:
            report("平場", [r for r in g if not r["重賞"]], pwin, pplc)
            report("重賞(G1-G3)", [r for r in g if r["重賞"]], pwin, pplc)
            for y in sorted({r["year"] for r in g}):
                report(f"  {y}重賞",
                       [r for r in g if r["重賞"] and r["year"] == y],
                       pwin, pplc, min_n=15)
        print()

    if args.age3:
        # 3歳馬が古馬と一緒に走ったとき、どれだけ通用しているか
        mixed = [r for r in rows if r["年齢"] and r["年齢"] >= 3
                 and "3歳" not in (r["クラス"] or "")]
        print("═══ 3歳馬の通用度（古馬混合の9-12R）")
        for band, lo_k, hi_k in (("〜1400m", 0, 1400), ("1401-1800m", 1401, 1800),
                                 ("1801m〜", 1801, 9999)):
            part = [r for r in mixed if r["距離"] and lo_k <= r["距離"] <= hi_k]
            if not part:
                continue
            print(f"\n  【{band}】")
            print(HEAD)
            for y in sorted({r["year"] for r in part}):
                g = [r for r in part if r["year"] == y and r["年齢"] == 3]
                report(f"{y}年 3歳", g, pwin, pplc)


if __name__ == "__main__":
    main()
