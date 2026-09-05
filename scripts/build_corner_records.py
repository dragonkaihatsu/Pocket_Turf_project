#!/usr/bin/env python3
"""収集済みレースから「その馬が4角で何番手にいたか」の履歴を作る。

netkeiba の脚質ラベル（逃げ/先行/差し/追込）は事前に分かる唯一の位置情報
だが、実測すると当たりが悪い。とくに中央では「逃げ」の馬が4角1-2番手を
取れるのは41.7%しかなく、複勝率も差し馬と変わらない。

そこで**その馬自身が過去に4角で何番手にいたか**を履歴として持ち、
位置取りを推定する材料にする。頭数が違うと同じ「3番手」の意味が変わる
ため、相対位置 (順位-1)/(頭数-1) を併記する（0=先頭、1=最後方）。

    python3 scripts/build_corner_records.py --profile jra
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keiba.profile as profile
from backtest import race_date, race_number, race_venue
from keiba.course import parse_passing_order

COLUMNS = ["馬名", "日付", "場", "R", "4角", "頭数", "相対", "着順", "脚質"]


def build(directory: Path) -> list[dict]:
    rows: list[dict] = []
    for p in sorted(directory.glob("*_結果.csv")):
        stem = p.name.replace("_結果.csv", "")
        dt = race_date(stem)
        cpath = directory / f"{stem}_通過順.csv"
        if not (dt and cpath.exists()):
            continue
        corners = {r["コーナー"]: r["通過順"]
                   for r in csv.DictReader(open(cpath, encoding="utf-8-sig"))}
        pos = parse_passing_order(corners.get("4コーナー")
                                  or corners.get("3コーナー") or "")
        if not pos:
            continue
        n = len(pos)
        epath = directory / f"{stem}_出走馬.csv"
        kyaku = {}
        if epath.exists():
            kyaku = {r["馬名"]: (r.get("脚質") or "").strip()
                     for r in csv.DictReader(open(epath, encoding="utf-8-sig"))}
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            try:
                umaban, chaku = int(r["馬番"]), int(r["着順"])
            except (ValueError, KeyError, TypeError):
                continue
            c = pos.get(umaban)
            if c is None or not r.get("馬名"):
                continue
            rows.append({
                "馬名": r["馬名"], "日付": dt, "場": race_venue(stem) or "",
                "R": race_number(stem) or "", "4角": c, "頭数": n,
                "相対": round((c - 1) / max(n - 1, 1), 4),
                "着順": chaku, "脚質": kyaku.get(r["馬名"], ""),
            })
    rows.sort(key=lambda r: (r["馬名"], r["日付"]))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["nar", "jra"], default="jra")
    ap.add_argument("--dir")
    ap.add_argument("--output")
    args = ap.parse_args()

    prof = profile.use(args.profile)
    directory = Path(args.dir or ("data/collected" if args.profile == "nar"
                                  else "data/collected_jra"))
    rows = build(directory)
    out = Path(args.output or prof.path("corner_records.csv"))
    out.parent.mkdir(parents=True, exist_ok=True)
    # BOM付きUTF-8。WindowsのExcelがShift_JISと誤認しないようにする
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    horses = len({r["馬名"] for r in rows})
    print(f"{len(rows):,}行 / {horses:,}頭 を {out} に書き出し")


if __name__ == "__main__":
    main()
