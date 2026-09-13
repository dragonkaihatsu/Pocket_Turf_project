#!/usr/bin/env python3
"""記事から拾った「測れる3つ」を同一人気帯内で検証する。

    python3 scripts/kiji_ninki.py --races 1-12 --target-races 9-12

1. **前走人気してて今走人気していない馬はお買い得**（記事の例: サリオス
   3人気→8人気で3着）。人気は馬柱に載るが、**2走の人気の差は2枚を
   突き合わせないと見えない**ので、設計原則でいう「組み合わせ」側。
2. **距離短縮は買える／延長は…**
3. **馬体重410kg前後は軽視**（記事「馬はアスリート。ムキムキの馬が強い」）

**必ず今走の人気帯の中で測る。** 人気が落ちた馬は当然オッズが長いので、
帯で統制しないと「人気薄は来ない」を再発見するだけになる。
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import power
from keiba.racefiles import DEFAULT_RACES, race_number, result_files

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")
BANDS = ["1-3番人気", "4-5番人気", "6-9番人気", "10番人気以下"]


def band(n):
    if n is None:
        return None
    return ("1-3番人気" if n <= 3 else "4-5番人気" if n <= 5
            else "6-9番人気" if n <= 9 else "10番人気以下")


def load(directory, races, race_info):
    info = {r["stem"]: r for r in csv.DictReader(open(race_info, encoding="utf-8-sig"))}
    by_horse = defaultdict(list)
    for p in result_files(directory, races):
        stem = p.name.replace("_結果.csv", "")
        m = DATE_RE.match(stem)
        if not m:
            continue
        ri = info.get(stem, {})
        ent = {}
        try:
            for e in csv.DictReader(open(str(p).replace("_結果.csv", "_出走馬.csv"),
                                         encoding="utf-8-sig")):
                nm = (e.get("馬名") or "").strip()
                iv = e.get("前走間隔日数") or ""
                if nm:
                    ent[nm] = int(iv) if iv.isdigit() else None
        except FileNotFoundError:
            pass
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            nm = (r.get("馬名") or "").strip()
            ch = (r.get("着順") or "").strip()
            nk = (r.get("人気") or "").strip()
            if not (nm and ch.isdigit()):
                continue
            bw = re.match(r"(\d+)", (r.get("馬体重") or "").strip())
            by_horse[nm].append({
                "date": m.group(1), "R": race_number(p.name), "chaku": int(ch),
                "ninki": int(nk) if nk.isdigit() else None,
                "kyori": int(ri["距離"]) if (ri.get("距離") or "").isdigit() else None,
                "bataiju": int(bw.group(1)) if bw else None,
                "interval": ent.get(nm)})
    for v in by_horse.values():
        v.sort(key=lambda x: x["date"])
    return by_horse


def pairs_of(by_horse, target_races):
    tgt = set()
    for part in target_races.split(","):
        if "-" in part:
            a, b = part.split("-")
            tgt |= set(range(int(a), int(b) + 1))
        else:
            tgt.add(int(part))

    def o(s):
        y, mm, dd = (int(x) for x in s.split("-"))
        return date(y, mm, dd).toordinal()

    out = []
    for lst in by_horse.values():
        for i in range(1, len(lst)):
            cur = lst[i]
            if cur["interval"] is None or cur["R"] not in tgt:
                continue
            t = o(cur["date"]) - cur["interval"]
            for cand in lst[:i][::-1]:
                if abs(o(cand["date"]) - t) <= 2:
                    out.append((cand, cur))
                    break
    return out


def by_band(title, groups, rows_all, key=lambda c: c["chaku"] <= 3):
    """groups は (ラベル, [今走の行]) の並び。今走の人気帯ごとに対照と比べる。"""
    print(f"\n■ {title}")
    for b in BANDS:
        ctl = [c for c in rows_all if band(c["ninki"]) == b]
        if len(ctl) < 200:
            continue
        ch = sum(1 for c in ctl if key(c))
        print(f"  {b}  対照 n={len(ctl):,} 複勝率{ch/len(ctl):.1%}")
        for label, rows in groups:
            rr = [c for c in rows if band(c["ninki"]) == b]
            if len(rr) < 60:
                print(f"    {label:<26} n={len(rr):>5}  母数不足")
                continue
            h = sum(1 for c in rr if key(c))
            v = power.judge(label, h, len(rr), ch, len(ctl))
            print(f"    {label:<26} n={len(rr):>5}  {h/len(rr):>5.1%}"
                  f"  {(h/len(rr)-ch/len(ctl))*100:>+5.1f}p  要る差{v.mdd*100:>4.1f}p  {v.code}")


def period(title, groups, rows_all):
    print(f"\n  {title} 期間で割る（今走の人気帯を混ぜず 1-3番人気で）")
    for label, rows in groups:
        line = []
        for y in (2025, 2026):
            rr = [c for c in rows if c["date"].startswith(str(y)) and band(c["ninki"]) == "1-3番人気"]
            cc = [c for c in rows_all if c["date"].startswith(str(y)) and band(c["ninki"]) == "1-3番人気"]
            if len(rr) < 60 or not cc:
                line.append(f"{y}: n={len(rr)} 母数不足")
                continue
            r = sum(1 for x in rr if x["chaku"] <= 3) / len(rr)
            bb = sum(1 for x in cc if x["chaku"] <= 3) / len(cc)
            line.append(f"{y}: {r:.1%} ({(r-bb)*100:+.1f}p, n={len(rr)})")
        print(f"    {label:<26} " + " / ".join(line))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="1-12")
    ap.add_argument("--target-races", default=DEFAULT_RACES)
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    a = ap.parse_args()

    by_horse = load(a.dir, a.races, a.race_info)
    pairs = pairs_of(by_horse, a.target_races)
    print(f"馬 {len(by_horse):,}頭 / 前走ペア {len(pairs):,}組")
    allc = [c for _, c in pairs]

    # 1. 人気の落ち幅（今走人気 − 前走人気。正なら人気を落とした）
    ok = [(p, c) for p, c in pairs if p["ninki"] and c["ninki"]]
    print(f"  人気が両走で分かるペア {len(ok):,}")
    g = [("人気を5以上落とした", [c for p, c in ok if c["ninki"] - p["ninki"] >= 5]),
         ("人気を2-4落とした", [c for p, c in ok if 2 <= c["ninki"] - p["ninki"] <= 4]),
         ("ほぼ同じ(±1)", [c for p, c in ok if abs(c["ninki"] - p["ninki"]) <= 1]),
         ("人気を2-4上げた", [c for p, c in ok if -4 <= c["ninki"] - p["ninki"] <= -2]),
         ("人気を5以上上げた", [c for p, c in ok if c["ninki"] - p["ninki"] <= -5])]
    by_band("記事「前走人気→今走人気薄はお買い得」", g, [c for _, c in ok])
    period("同上", g, [c for _, c in ok])

    # 2. 距離の短縮・延長
    kk = [(p, c) for p, c in pairs if p["kyori"] and c["kyori"]]
    print(f"\n  距離が両走で分かるペア {len(kk):,}")
    g2 = [("短縮(400m以上)", [c for p, c in kk if c["kyori"] - p["kyori"] <= -400]),
          ("短縮(200m)", [c for p, c in kk if -399 <= c["kyori"] - p["kyori"] <= -100]),
          ("同距離", [c for p, c in kk if c["kyori"] == p["kyori"]]),
          ("延長(200m)", [c for p, c in kk if 100 <= c["kyori"] - p["kyori"] <= 399]),
          ("延長(400m以上)", [c for p, c in kk if c["kyori"] - p["kyori"] >= 400])]
    by_band("記事「距離短縮は買える／延長は…」", g2, [c for _, c in kk])

    # 3. 絶対馬体重
    bw = [c for c in allc if c["bataiju"]]
    print(f"\n  馬体重が分かる出走 {len(bw):,}")
    g3 = [("430kg未満", [c for c in bw if c["bataiju"] < 430]),
          ("430-459kg", [c for c in bw if 430 <= c["bataiju"] < 460]),
          ("460-489kg", [c for c in bw if 460 <= c["bataiju"] < 490]),
          ("490-519kg", [c for c in bw if 490 <= c["bataiju"] < 520]),
          ("520kg以上", [c for c in bw if c["bataiju"] >= 520])]
    by_band("記事「410kg前後は軽視。ムキムキの馬が強い」", g3, bw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
