#!/usr/bin/env python3
"""騎手 × 条件（場・距離・馬場）の実測を引く。得意条件を探すための道具。

**これはスコアを動かす道具ではない。** 騎手補正は独立検証で平均−0.5pt、
効果を確認できず重み0.5に落としてある。ここは「三浦皇成の関東1600mは
回収率が高い」といった**思い込みを、手元の数字で確かめる**ためのもの。

だから出力は必ず**年ごとに分けて**出す。片方の年だけで高い区分は、
今日いくつも見たとおり翌年に反転する。両年で同じ向きに出て初めて、
参考にする価値がある。

    python3 scripts/jockey.py --jockey 三浦 --area 関東 --kyori 1600
    python3 scripts/jockey.py --find --min 40        # 回収率の高い組み合わせを探す
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keiba.profile as profile
from backtest import race_number, race_venue
from keiba.expectation import wilson

AREAS = {"関東": ("東京", "中山", "福島", "新潟"),
         "関西": ("京都", "阪神", "中京", "小倉"),
         "北海道": ("札幌", "函館")}
BANDS = ((0, 1400, "〜1400"), (1401, 1800, "1401-1800"), (1801, 9999, "1801〜"))


def band_of(kyori: int | None) -> str:
    if not kyori:
        return ""
    for lo, hi, name in BANDS:
        if lo <= kyori <= hi:
            return name
    return ""


def load(profile_name: str, directory: Path, races: set[int] | None) -> list[dict]:
    prof = profile.use(profile_name)
    info = {}
    p = prof.path("race_info.csv")
    if p.exists():
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            info[r["stem"]] = {
                "距離": int(r["距離"]) if (r.get("距離") or "").isdigit() else None,
                "種別": r.get("馬場種別", ""), "馬場": r.get("馬場", ""),
                "斤量": r.get("斤量条件", ""), "格": r.get("格", "")}

    rows = []
    for res in sorted(directory.glob("*_結果.csv")):
        stem = res.name.replace("_結果.csv", "")
        rn = race_number(stem)
        if races is not None and (rn is None or rn not in races):
            continue
        m = info.get(stem, {})
        venue = race_venue(stem) or ""
        year = stem[:4]
        # 複勝配当は 配当CSV から。馬番 → 100円あたりの払戻
        fuku: dict[int, int] = {}
        pay = directory / f"{stem}_配当.csv"
        if pay.exists():
            for q in csv.DictReader(open(pay, encoding="utf-8-sig")):
                if q["券種"] == "複勝":
                    try:
                        fuku[int(q["組み合わせ"])] = int(q["配当"])
                    except ValueError:
                        pass
        for r in csv.DictReader(open(res, encoding="utf-8-sig")):
            if not (r.get("着順") or "").isdigit():
                continue
            try:
                odds = float(r["単勝オッズ"])
            except (ValueError, KeyError, TypeError):
                odds = None
            umaban = int(r["馬番"]) if (r.get("馬番") or "").isdigit() else None
            rows.append({
                "年": year, "騎手": (r.get("騎手") or "").strip(), "場": venue,
                "着順": int(r["着順"]), "オッズ": odds,
                "人気": int(r["人気"]) if (r.get("人気") or "").isdigit() else None,
                "複勝": fuku.get(umaban), "距離": m.get("距離"),
                "帯": band_of(m.get("距離")), "種別": m.get("種別", ""),
                "格": m.get("格", "")})
    return rows


def tally(sel: list[dict]) -> dict:
    n = len(sel)
    if not n:
        return {"n": 0}
    win = sum(1 for r in sel if r["着順"] == 1)
    plc = sum(1 for r in sel if r["着順"] <= 3)
    tan = sum((r["オッズ"] or 0) * 100 for r in sel if r["着順"] == 1)
    fuku = sum(r["複勝"] or 0 for r in sel if r["着順"] <= 3)
    lo, hi = wilson(plc, n)
    return {"n": n, "勝率": win / n, "複勝率": plc / n,
            "単回収": tan / (n * 100), "複回収": fuku / (n * 100),
            "区間下": lo, "区間上": hi}


def line(label: str, t: dict, width: int = 24) -> str:
    if not t["n"]:
        return f"{label:<{width}}  データなし"
    return (f'{label:<{width}}{t["n"]:>6}{t["勝率"]:>8.1%}{t["複勝率"]:>8.1%}'
            f'{t["単回収"]:>9.0%}{t["複回収"]:>9.0%}')


HEAD = f'{"区分":<24}{"騎乗":>6}{"勝率":>8}{"複勝率":>8}{"単回収":>9}{"複回収":>9}'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["nar", "jra"], default="jra")
    ap.add_argument("--dir")
    ap.add_argument("--races", default=None, help="レース番号で絞る（例 9-12）")
    ap.add_argument("--jockey", help="騎手名（部分一致）")
    ap.add_argument("--area", choices=list(AREAS), help="関東 / 関西 / 北海道")
    ap.add_argument("--venue", help="競馬場（カンマ区切り）")
    ap.add_argument("--kyori", type=int, help="距離(m)。帯で絞る")
    ap.add_argument("--surface", choices=["芝", "ダ"])
    ap.add_argument("--find", action="store_true",
                    help="回収率の高い 騎手×場×距離帯 の組み合わせを探す")
    ap.add_argument("--min", type=int, default=40, help="--find の最低騎乗数")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    directory = Path(args.dir or ("data/collected" if args.profile == "nar"
                                  else "data/collected_jra"))
    races = None
    if args.races:
        lo, hi = (args.races.split("-") + [args.races])[:2]
        races = set(range(int(lo), int(hi) + 1))
    rows = load(args.profile, directory, races)
    years = sorted({r["年"] for r in rows})
    label = "地方" if args.profile == "nar" else "中央"
    print(f"{label} 延べ{len(rows):,}騎乗（{'・'.join(years)}年）")
    print("単回収・複回収は1点100円あたり。単勝の払戻率は80%、複勝も80%\n")

    if args.find:
        # 騎手×場×距離帯 を総当たりし、両年で見たときの回収率で並べる
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for r in rows:
            if r["騎手"] and r["場"] and r["帯"]:
                groups[(r["騎手"], r["場"], r["帯"])].append(r)
        cands = []
        for key, sel in groups.items():
            if len(sel) < args.min:
                continue
            t = tally(sel)
            per_year = {y: tally([r for r in sel if r["年"] == y]) for y in years}
            cands.append((key, t, per_year))
        cands.sort(key=lambda x: -x[1]["単回収"])
        print(f"騎手×場×距離帯　最低{args.min}騎乗　単勝回収率の高い順\n")
        print(f'{"組み合わせ":<24}{"騎乗":>6}{"勝率":>8}{"複勝率":>8}{"単回収":>9}{"複回収":>9}'
              + "".join(f'{y + "年単回収":>11}' for y in years))
        for (j, v, b), t, per in cands[:args.top]:
            tail = ""
            for y in years:
                p = per[y]
                tail += (f'{p["単回収"]:>10.0%}' + ("*" if p["n"] < 15 else " ")
                         if p["n"] else f'{"—":>11}')
            print(line(f"{j} {v}{b}", t) + tail)
        print("\n* は その年の騎乗が15回未満。年ごとに向きが揃っていない組み合わせは")
        print("  偶然の可能性が高い。両年とも高いものだけを参考にすること")
        return

    sel = rows
    if args.jockey:
        sel = [r for r in sel if args.jockey in r["騎手"]]
    venues = None
    if args.area:
        venues = set(AREAS[args.area])
    if args.venue:
        venues = set(args.venue.split(","))
    if venues:
        sel = [r for r in sel if r["場"] in venues]
    if args.kyori:
        b = band_of(args.kyori)
        sel = [r for r in sel if r["帯"] == b]
    if args.surface:
        sel = [r for r in sel if r["種別"] == args.surface]

    cond = " / ".join(filter(None, [
        args.jockey, args.area or args.venue,
        f"{band_of(args.kyori)}m" if args.kyori else "", args.surface]))
    print(f"■ {cond or '全体'}\n")
    print(HEAD)
    print(line("合計", tally(sel)))
    for y in years:
        print(line(f"  {y}年", tally([r for r in sel if r["年"] == y])))
    if not args.kyori:
        print()
        for _, _, b in BANDS:
            print(line(f"  {b}m", tally([r for r in sel if r["帯"] == b])))
    if not args.surface:
        print()
        for s in ("芝", "ダ"):
            print(line(f"  {s}", tally([r for r in sel if r["種別"] == s])))
    t = tally(sel)
    if t["n"]:
        print(f'\n複勝率の95%区間: {t["区間下"]:.1%} 〜 {t["区間上"]:.1%}')
        if t["n"] < 40:
            print("※ 騎乗数が少なく、偶然の振れが大きい区分です")


if __name__ == "__main__":
    main()
