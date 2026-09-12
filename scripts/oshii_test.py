#!/usr/bin/env python3
"""「惜しい馬」——前走で僅差の4-5着に負けた馬は、次走で報われるか。

本人が挙げた例（2026-09-12）: 阪神9R ネッタイヤライ / 阪神11R マリアイリダータ /
中山11R ゲイルライダー。いずれも勝ち馬から2馬身以内の4着。

CLAUDE.md の設計原則にあてはめると、着差も上がり3Fも**馬柱にそのまま載って
いる**ので市場に織り込まれている側である。実際に「前走 上がり3F上位3位×6着以下」
（代理A）は既に棄却済み。ここで測るのは着順帯を 4-5着 に限った区分で、
代理Aとは別のセルになる。

判定は信頼区間＋最小検出差（`keiba/power.py`）で足りる。区分を作るのは
**前走**の結果で、窓が重なる構造は無いため（調子の検証で必要だった並べ替え
検定は不要。`scripts/form_test.py` の注記を参照）。

    python3 scripts/oshii_test.py
    python3 scripts/oshii_test.py --horses 2026-09-12   # その日の惜敗馬を一覧する
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import date
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.power import min_detectable_diff, wilson
from keiba.racefiles import DEFAULT_RACES, result_paths

DATE_RE = re.compile(r".*/(\d{4}-\d{2}-\d{2})_")
WORDS = {"同着": 0.0, "ハナ": 0.05, "アタマ": 0.1, "クビ": 0.25, "大差": 10.0}
BANDS = (("1-3番人気", 1, 3), ("4-5番人気", 4, 5), ("6-9番人気", 6, 9),
         ("10番人気以下", 10, 99), ("（全体）", 1, 99))


def parse_margin(text: str) -> float | None:
    """netkeibaの着差表記を馬身に直す。'1.1/4' → 1.25、'クビ' → 0.25。"""
    s = (text or "").strip()
    if not s:
        return 0.0
    if s in WORDS:
        return WORDS[s]
    m = re.fullmatch(r"(\d+)?\.?(\d+)/(\d+)", s)
    if m:
        whole = int(m.group(1) or 0)
        return whole + float(Fraction(int(m.group(2)), int(m.group(3))))
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    return None


def load(directory: str, races: str) -> dict[str, list[dict]]:
    by_horse: dict[str, list[dict]] = defaultdict(list)
    for f in result_paths(directory, races):
        m = DATE_RE.match(f)
        if not m:
            continue
        day = m.group(1)
        pay_t, pay_f = {}, {}
        try:
            for p in csv.DictReader(open(f.replace("_結果.csv", "_配当.csv"),
                                         encoding="utf-8-sig")):
                if p.get("券種") == "単勝":
                    pay_t[int(p["組み合わせ"])] = int(p["配当"])
                elif p.get("券種") == "複勝":
                    pay_f[int(p["組み合わせ"])] = int(p["配当"])
        except (FileNotFoundError, ValueError, KeyError):
            pass
        intervals: dict[str, int | None] = {}
        try:
            for e in csv.DictReader(open(f.replace("_結果.csv", "_出走馬.csv"),
                                         encoding="utf-8-sig")):
                nm = (e.get("馬名") or "").strip()
                iv = e.get("前走間隔日数") or ""
                if nm:
                    intervals[nm] = int(iv) if iv.isdigit() else None
        except FileNotFoundError:
            pass
        rows = [r for r in csv.DictReader(open(f, encoding="utf-8-sig"))
                if (r.get("着順") or "").isdigit()]
        if not rows:
            continue
        rows.sort(key=lambda r: int(r["着順"]))
        # 上がり3Fのレース内順位（速い順）
        agari = sorted((float(r["上がり3F"]), r["馬番"]) for r in rows
                       if (r.get("上がり3F") or "").replace(".", "", 1).isdigit())
        agari_rank = {ub: i for i, (_, ub) in enumerate(agari, start=1)}
        # 勝ち馬からの累計着差
        total = 0.0
        broken = False
        for r in rows:
            gap = parse_margin(r.get("着差"))
            if gap is None:
                broken = True
            elif int(r["着順"]) > 1:
                total += gap
            r["_margin"] = None if broken else total
        for r in rows:
            nm = (r.get("馬名") or "").strip()
            ub = r.get("馬番") or ""
            nk = r.get("人気") or ""
            if not (nm and ub.isdigit()):
                continue
            by_horse[nm].append({
                "date": day, "race": Path(f).name, "chaku": int(r["着順"]),
                "field": len(rows), "ninki": int(nk) if nk.isdigit() else None,
                "margin": r["_margin"], "agari_rank": agari_rank.get(ub),
                "interval": intervals.get(nm),
                "tan": pay_t.get(int(ub), 0), "fuku": pay_f.get(int(ub), 0),
            })
    for runs in by_horse.values():
        runs.sort(key=lambda x: x["date"])
    return by_horse


def build_pairs(by_horse: dict[str, list[dict]]) -> list[tuple[dict, dict]]:
    """馬柱の前走間隔日数と日付差が一致するペアだけを採る（既存検証と同じ規則）。"""
    def ordinal(s: str) -> int:
        y, m, d = (int(x) for x in s.split("-"))
        return date(y, m, d).toordinal()

    pairs = []
    for runs in by_horse.values():
        for i in range(1, len(runs)):
            cur = runs[i]
            if cur["interval"] is None:
                continue
            target = ordinal(cur["date"]) - cur["interval"]
            for cand in runs[:i][::-1]:
                if abs(ordinal(cand["date"]) - target) <= 2:
                    pairs.append((cand, cur))
                    break
    return pairs


def band_rows(rows: list[dict], lo: int, hi: int) -> list[dict]:
    return [r for r in rows if r["ninki"] and lo <= r["ninki"] <= hi]


def show(groups: list[tuple[str, list[dict]]], base_label: str) -> None:
    base = dict(groups)[base_label]
    print(f"  {'人気帯':<14}{'区分':<26}{'n':>7}{'複勝率':>9}{'勝率':>8}"
          f"{'差':>9}{'判定':>10}{'単回収':>8}")
    for label, lo, hi in BANDS:
        b = band_rows(base, lo, hi)
        if len(b) < 30:
            continue
        p_base = sum(1 for r in b if r["chaku"] <= 3) / len(b)
        for name, rows in groups:
            v = band_rows(rows, lo, hi)
            if len(v) < 30:
                continue
            hits = sum(1 for r in v if r["chaku"] <= 3)
            p = hits / len(v)
            win = sum(1 for r in v if r["chaku"] == 1) / len(v)
            roi = sum(r["tan"] for r in v if r["chaku"] == 1) / (len(v) * 100) * 100
            if name == base_label:
                mark = "（対照）"
                diff = ""
            else:
                ci = wilson(hits, len(v))
                mdd = min_detectable_diff(len(v), p_base)
                mark = ("差あり" if not ci[0] <= p_base <= ci[1]
                        else ("差なし" if mdd <= 0.05 else "判定不能"))
                diff = f"{(p - p_base) * 100:+.1f}pt"
            print(f"  {label:<14}{name:<26}{len(v):>7,}{p * 100:>8.1f}%{win * 100:>7.1f}%"
                  f"{diff:>9}{mark:>10}{roi:>7.0f}%")
        print()


def list_day(by_horse: dict[str, list[dict]], day: str) -> None:
    print(f"■ {day} の惜敗馬（4-5着・勝ち馬から2馬身以内）")
    found = []
    for name, runs in by_horse.items():
        for r in runs:
            if r["date"] == day and 4 <= r["chaku"] <= 5 and (r["margin"] or 99) <= 2.0:
                found.append((r["race"], r["chaku"], name, r))
    for race, chaku, name, r in sorted(found):
        label = race.replace("_結果.csv", "").replace(f"{day}_", "")
        print(f"  {label:<28}{chaku}着 {name:<16}{r['ninki']:>3}人気 "
              f"勝ち馬から{r['margin']:.2f}馬身 上がり{r['agari_rank']}位/{r['field']}頭")
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--horses", help="この日の惜敗馬を一覧する（YYYY-MM-DD）")
    ap.add_argument("--close", type=float, default=0.75, help="「惜しい」と見なす累計着差")
    ap.add_argument("--far", type=float, default=1.5, help="「離された」と見なす累計着差")
    args = ap.parse_args()

    by_horse = load(args.dir, args.races)
    if args.horses:
        list_day(by_horse, args.horses)

    pairs = build_pairs(by_horse)
    usable = [(p, c) for p, c in pairs if p["margin"] is not None]
    print(f"前走ペア {len(pairs):,}組 / 前走の着差が読めた {len(usable):,}組\n")

    def sel(pred) -> list[dict]:
        return [c for p, c in usable if pred(p)]

    def is45(p):
        return 4 <= p["chaku"] <= 5

    print(f"■ 前走4-5着を、勝ち馬からの累計着差で割る"
          f"（惜しい≤{args.close}馬身 / 離された>{args.far}馬身）")
    show([
        ("前走4-5着 すべて（対照）", sel(is45)),
        (f"うち 惜しい(≤{args.close}馬身)", sel(lambda p: is45(p) and p["margin"] <= args.close)),
        (f"うち 離された(>{args.far}馬身)", sel(lambda p: is45(p) and p["margin"] > args.far)),
    ], "前走4-5着 すべて（対照）")

    print("■ 前走4-5着を、前走の上がり3F順位で割る")
    show([
        ("前走4-5着 すべて（対照）", sel(is45)),
        ("うち 上がり3位以内", sel(lambda p: is45(p) and (p["agari_rank"] or 99) <= 3)),
        ("うち 上がり4位以下", sel(lambda p: is45(p) and (p["agari_rank"] or 0) >= 4)),
    ], "前走4-5着 すべて（対照）")

    print("■ 期間で割って再現するか（惜しい vs 離された・複勝率）")
    print(f"  {'年':<8}{'惜しい n':>10}{'複勝率':>9}{'離された n':>11}{'複勝率':>9}{'差':>9}")
    for year in ("2025", "2026"):
        out = []
        for pred in (lambda p: p["margin"] <= args.close, lambda p: p["margin"] > args.far):
            v = [c for p, c in usable if is45(p) and pred(p) and c["date"].startswith(year)]
            out.append((len(v), sum(1 for r in v if r["chaku"] <= 3) / len(v) if v else 0))
        print(f"  {year:<8}{out[0][0]:>10,}{out[0][1] * 100:>8.1f}%"
              f"{out[1][0]:>11,}{out[1][1] * 100:>8.1f}%"
              f"{(out[0][1] - out[1][1]) * 100:>8.1f}pt")


if __name__ == "__main__":
    main()
