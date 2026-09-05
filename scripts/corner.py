#!/usr/bin/env python3
"""4コーナー通過順を軸に、脚質・枠順・開催日目を突き合わせる。

通過順そのものはレース結果であって事前情報ではない。だからこの集計の
目的は「差し馬を切る」ことではなく、**事前に分かる脚質から4角の位置を
どれだけ読めるか**を測ることにある。読めないなら脚質の配点は下げるべきだし、
読めるなら前を取れる馬を高く評価してよい。

    python3 scripts/corner.py --profile jra
    python3 scripts/corner.py --profile nar --nichi   # 開催日目別（中央のみ）
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keiba.profile as profile
from backtest import race_number, parse_races
from keiba.course import parse_passing_order
from keiba.expectation import wilson

VENUE_CODES = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
               "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}

# 4角の位置をまとめる区分
POS_BANDS = [("4角1-2番手", 1, 2), ("3-5番手", 3, 5), ("6番手以下", 6, 99)]
KYAKUSHITSU = ("逃げ", "先行", "差し", "追込")


def load_race_meta(path: Path) -> dict[str, dict]:
    """stem → 開催情報。中央は race_id に開催回・日目が入っている。"""
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        rid = (r.get("race_id") or "").strip()
        meta = {"馬場種別": r.get("馬場種別", ""), "馬場": r.get("馬場", "")}
        if len(rid) == 12 and rid.isdigit():
            meta.update({"場": VENUE_CODES.get(rid[4:6], ""),
                         "開催回": int(rid[6:8]), "日目": int(rid[8:10])})
        out[r["stem"]] = meta
    return out


def collect(directory: Path, meta: dict[str, dict], races: set[int] | None) -> list[dict]:
    rows = []
    for p in sorted(directory.glob("*_結果.csv")):
        stem = p.name.replace("_結果.csv", "")
        rn = race_number(stem)
        if races is not None and (rn is None or rn not in races):
            continue
        cpath = directory / f"{stem}_通過順.csv"
        if not cpath.exists():
            continue
        corners = {r["コーナー"]: r["通過順"]
                   for r in csv.DictReader(open(cpath, encoding="utf-8-sig"))}
        pos = parse_passing_order(corners.get("4コーナー")
                                  or corners.get("3コーナー") or "")
        if not pos:
            continue
        epath = directory / f"{stem}_出走馬.csv"
        kyaku = {}
        if epath.exists():
            kyaku = {r["馬名"]: (r.get("脚質") or "").strip()
                     for r in csv.DictReader(open(epath, encoding="utf-8-sig"))}
        m = meta.get(stem, {})
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            try:
                ch, umaban, waku = int(r["着順"]), int(r["馬番"]), int(r["枠番"])
            except (ValueError, KeyError, TypeError):
                continue
            c = pos.get(umaban)
            if c is None:
                continue
            rows.append({"着順": ch, "馬番": umaban, "枠番": waku, "4角": c,
                         "脚質": kyaku.get(r["馬名"], ""), "頭数": len(pos), **m})
    return rows


def _line(label: str, sel: list[dict], width: int = 22) -> None:
    if len(sel) < 30:
        return
    n = len(sel)
    win = sum(1 for r in sel if r["着順"] == 1)
    plc = sum(1 for r in sel if r["着順"] <= 3)
    lo, hi = wilson(plc, n)
    print(f"{label:<{width}}{n:>7}{win / n:>8.1%}{plc / n:>8.1%}"
          f"{f'{lo:.1%} 〜 {hi:.1%}':>18}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["nar", "jra"], default="jra")
    ap.add_argument("--dir")
    ap.add_argument("--races", default=None, help="レース番号で絞る (例 9-12)")
    ap.add_argument("--surface", choices=["芝", "ダ"], help="馬場種別で絞る")
    ap.add_argument("--nichi", action="store_true", help="開催日目別も出す（中央のみ）")
    args = ap.parse_args()

    prof = profile.use(args.profile)
    directory = Path(args.dir or ("data/collected" if args.profile == "nar"
                                  else "data/collected_jra"))
    meta = load_race_meta(prof.path("race_info.csv"))
    rows = collect(directory, meta, parse_races(args.races) if args.races else None)
    if args.surface:
        rows = [r for r in rows if r.get("馬場種別") == args.surface]
    label = "地方" if args.profile == "nar" else "中央"
    scope = f"{label}{'・' + args.surface if args.surface else ''}"
    print(f"{scope}  {len(rows):,}頭（通過順が取れたレースのみ）\n")

    head = f"{'区分':<22}{'頭数':>7}{'勝率':>8}{'複勝率':>8}{'複勝率の95%区間':>18}"
    print("── 4コーナーの位置別（結果であって事前情報ではない） " + "─" * 12)
    print(head)
    for name, lo, hi in POS_BANDS:
        _line(name, [r for r in rows if lo <= r["4角"] <= hi])

    print("\n── 事前に分かる脚質から、4角の位置をどれだけ読めるか " + "─" * 11)
    print(f"{'脚質':<10}{'頭数':>7}{'4角平均':>9}{'1-2番手率':>11}{'6番手以下率':>12}")
    for k in KYAKUSHITSU:
        sel = [r for r in rows if r["脚質"] == k]
        if len(sel) < 30:
            continue
        avg = sum(r["4角"] for r in sel) / len(sel)
        front = sum(1 for r in sel if r["4角"] <= 2) / len(sel)
        back = sum(1 for r in sel if r["4角"] >= 6) / len(sel)
        print(f"{k:<10}{len(sel):>7}{avg:>9.1f}{front:>11.1%}{back:>12.1%}")

    print("\n── 脚質別の成績（事前情報としての価値） " + "─" * 22)
    print(head)
    for k in KYAKUSHITSU:
        _line(k, [r for r in rows if r["脚質"] == k])

    if args.nichi and any("日目" in r for r in rows):
        print("\n── 開催日目別: 「開幕週は前が残る／内が伸びる」の検証 " + "─" * 8)
        print(head)
        groups = [("開幕週(1-2日目)", 1, 2), ("中盤(3-6日目)", 3, 6), ("終盤(7日目〜)", 7, 99)]
        for gname, glo, ghi in groups:
            g = [r for r in rows if glo <= r.get("日目", 0) <= ghi]
            if len(g) < 50:
                continue
            _line(f"{gname} 4角1-2番手", [r for r in g if r["4角"] <= 2])
            _line(f"{gname} 内(1-3枠)", [r for r in g if r["枠番"] <= 3])
            _line(f"{gname} 外(7-8枠)", [r for r in g if r["枠番"] >= 7])
            print()

    print("\n注意: 4角の位置は結果であって事前に確定する情報ではない。"
          "\n      「差し馬を切る」ではなく「前を取れる馬を高く評価する」と読むこと。"
          "\n      信頼区間が重なる差は、母数が増えるまで結論にしない。")


if __name__ == "__main__":
    main()
