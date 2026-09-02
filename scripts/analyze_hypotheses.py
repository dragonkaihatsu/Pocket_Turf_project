#!/usr/bin/env python3
"""収集済みコーパスに対して、荒れ要因の仮説を検証する。

`collect` が貯めた 結果CSV / 出走馬CSV / 配当CSV / 通過順CSV を突き合わせ、
CLAUDE.md に記録している仮説を同じ手順で再検証できるようにしたもの。
母数が増えたときに結論が変わるかを確認するために使う。

    python3 scripts/analyze_hypotheses.py [--dir data/collected]
"""
from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path
from statistics import median

JRA_VENUES = {"札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"}
MIN_SAMPLE = 30


def parse_passing_order(text: str) -> dict[int, int]:
    pos, rank = {}, 0
    for tok in re.findall(r"\((?:\d+,?)+\)|\d+", text):
        rank += 1
        for n in re.findall(r"\d+", tok):
            pos[int(n)] = rank
    return pos


def _int(v):
    return int(v) if v and str(v).strip().lstrip("+-").isdigit() else None


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load(directory: Path):
    """レース単位・馬単位のレコードを組み立てる。"""
    races, runners = [], []
    for res in sorted(directory.glob("*_結果.csv")):
        stem = res.name.replace("_結果.csv", "")
        rows = [r for r in csv.DictReader(open(res, encoding="utf-8")) if _int(r.get("着順"))]
        if len(rows) < 5:
            continue

        entries = {}
        ent_path = directory / f"{stem}_出走馬.csv"
        if ent_path.exists():
            for e in csv.DictReader(open(ent_path, encoding="utf-8")):
                if (u := _int(e.get("馬番"))) is not None:
                    entries[u] = e

        umaren = None
        pay_path = directory / f"{stem}_配当.csv"
        if pay_path.exists():
            for p in csv.DictReader(open(pay_path, encoding="utf-8")):
                if p["券種"] == "馬連":
                    umaren = _int(p["配当"])

        corner = {}
        cn_path = directory / f"{stem}_通過順.csv"
        if cn_path.exists():
            cs = {r["コーナー"]: r["通過順"] for r in csv.DictReader(open(cn_path, encoding="utf-8"))}
            if t := (cs.get("4コーナー") or cs.get("3コーナー")):
                corner = parse_passing_order(t)

        by_chaku = sorted(rows, key=lambda r: _int(r["着順"]))
        race = {
            "stem": stem, "頭数": len(rows), "馬連": umaren,
            "牝馬限定": all(r.get("性齢", "").startswith("牝") for r in rows),
            "1着人気": _int(by_chaku[0].get("人気")),
            "2着人気": _int(by_chaku[1].get("人気")) if len(by_chaku) > 1 else None,
        }
        races.append(race)

        for r in rows:
            u = _int(r["馬番"])
            e = entries.get(u, {})
            runners.append({
                "race": stem, "着順": _int(r["着順"]), "馬番": u,
                "人気": _int(r.get("人気")), "オッズ": _float(r.get("単勝オッズ")),
                "枠番": _int(r.get("枠番")), "頭数": len(rows),
                "4角": corner.get(u),
                "脚質": e.get("脚質") or "",
                "間隔": _int(e.get("前走間隔日数")),
                "前走場": e.get("前走開催場") or "",
                "転入初戦": e.get("転入初戦") == "Y",
                "長期休養明け": e.get("長期休養明け") == "Y",
                "血統父": e.get("血統父") or "",
            })
    return races, runners


def wilson(k: int, n: int) -> tuple[float, float]:
    """二項比率の95%信頼区間（Wilson score interval）。母数の少なさを可視化する。"""
    if n == 0:
        return (0.0, 0.0)
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def rate_line(label: str, sub: list, width: int = 24) -> str:
    n = len(sub)
    if n == 0:
        return f"  {label:<{width}}  該当なし"
    w = sum(1 for e in sub if e["着順"] == 1)
    p = sum(1 for e in sub if e["着順"] <= 3)
    lo, hi = wilson(p, n)
    warn = " ※母数少" if n < MIN_SAMPLE else ""
    return (f"  {label:<{width}}{n:>5}頭  勝率{w/n:>6.1%}  "
            f"複勝率{p/n:>6.1%} [{lo:.0%}-{hi:.0%}]{warn}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected")
    args = ap.parse_args()

    races, runners = load(Path(args.dir))
    print("=" * 70)
    print(f" 仮説の検証（{len(races)}レース / 延べ{len(runners)}頭）")
    print(" 複勝率の[ ]は95%信頼区間。区間が広いほど母数不足を意味する")
    print("=" * 70)

    print("\n── 仮説1: JRA転入初戦は危険か " + "─" * 36)
    print(rate_line("転入初戦(前走が中央)", [r for r in runners if r["転入初戦"]]))
    print(rate_line("地方継続", [r for r in runners if not r["転入初戦"] and r["前走場"]]))

    print("\n── 仮説2: 長期休養明けは飛ぶか " + "─" * 35)
    for label, lo, hi in [("中1〜2週(〜20日)", 0, 21), ("中3〜4週(21-35日)", 21, 36),
                          ("中5〜8週(36-63日)", 36, 64), ("2〜6ヶ月(64-180日)", 64, 181),
                          ("半年超(181日〜)", 181, 10**9)]:
        print(rate_line(label, [r for r in runners if r["間隔"] is not None and lo <= r["間隔"] < hi]))

    print("\n── 仮説3: 牝馬限定戦は荒れるか " + "─" * 35)
    for label, flag in [("牝馬限定戦", True), ("混合戦", False)]:
        sub = [r for r in races if r["牝馬限定"] is flag]
        ums = [r["馬連"] for r in sub if r["馬連"]]
        if not sub:
            continue
        fav = sum(1 for r in sub if r["1着人気"] == 1) / len(sub)
        print(f"  {label:<24}{len(sub):>5}R  1人気勝率{fav:>6.1%}  "
              f"馬連中央値{median(ums) if ums else 0:>7,.0f}円")

    print("\n── 1番人気の信頼度: 4角の位置別 " + "─" * 33)
    favs = [r for r in runners if r["人気"] == 1]
    for label, lo, hi in [("1番手", 1, 1), ("2番手", 2, 2), ("3番手", 3, 3),
                          ("4-5番手", 4, 5), ("6番手以下", 6, 99)]:
        print(rate_line(label, [r for r in favs if r["4角"] and lo <= r["4角"] <= hi]))

    print("\n── 1番人気の信頼度: 脚質別（事前に分かる指標）" + "─" * 21)
    for k in ("逃げ", "先行", "差し", "追込"):
        print(rate_line(k, [r for r in favs if r["脚質"] == k]))

    print("\n── 1番人気の信頼度: 単勝オッズ別 " + "─" * 32)
    for label, lo, hi in [("1.0-1.4倍", 0, 1.5), ("1.5-1.9倍", 1.5, 2.0),
                          ("2.0-2.4倍", 2.0, 2.5), ("2.5-2.9倍", 2.5, 3.0),
                          ("3.0-3.9倍", 3.0, 4.0), ("4.0倍以上", 4.0, 10**9)]:
        print(rate_line(label, [r for r in favs if r["オッズ"] and lo <= r["オッズ"] < hi]))

    print("\n── 全馬の脚質別成績 " + "─" * 45)
    for k in ("逃げ", "先行", "差し", "追込"):
        print(rate_line(k, [r for r in runners if r["脚質"] == k]))


if __name__ == "__main__":
    main()
