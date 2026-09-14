#!/usr/bin/env python3
"""残りの検証対象のうち、`census.py` で「測れる」と出たものを測る。

    python3 scripts/nokori.py --races 1-12 --target-races 9-12

`scripts/census.py` が帯ごとの該当数と見分けられる差（MDD）を出し、
**MDDが5pt以下の帯を持つ仮説だけ**をここで測る。測る前に数える、という
CLAUDE.mdの仕分け条件3をそのまま手順にしたもの。

判定は同一人気帯内の複勝リフト＋期間再現（2025/2026で符号が揃うか）。

## 測る対象と、census が出した母数
| 仮説 | 該当 | いちばん良い帯のMDD |
|---|---|---|
| B 前走スロー × 上がり3位以内 | 3,285 | 2.7pt |
| D 前走が超スロー × 4角中団 | 1,822 | 2.9pt |
| ④ 前3走すべてスロー寄り | 2,569 | 2.2pt |
| 多頭数(16頭以上)での勝ち鞍 | 4,946 | 1.9pt |
| 斤量 平均±1.5kg（短〜マイル/中距離） | 1,557〜1,854 | 2.3pt |
| 前年人気（1年前と比べた落ち幅） | 2,158〜2,579 | 1.5pt |
| ② 先行勢が多いレースの先行馬 | レース1,842 | 下記 |

**測らないもの**（census で判定不能だった）:
- D の記事どおりの形（超スロー × 中団 × 1-3着 = 595・MDD 8.1pt）
- 斤量の**長距離**（168〜292・MDD 12〜24pt）。皮肉だが、
  「長距離のほうが斤量差が効く」を確かめたいのに長距離だけ母数が足りない
"""
from __future__ import annotations

import argparse
import collections
import csv
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import power
from keiba.racefiles import DEFAULT_RACES, result_files
from scripts.build_mochidokei import load_race_info
from scripts.tenkai import band, build_pairs, load, to_o

BANDS = ["1-3番人気", "4-5番人気", "6-9番人気", "10番人気以下"]
MIN_CELL = 60
MIN_CONTROL = 200
SLOW_HI = 0.25
FUKU = (lambda c: c["chaku"] <= 3, "複勝率")


def report(title, groups, allc, key=FUKU[0], keyname=FUKU[1], period=True):
    print(f"\n■ {title}")
    for b in BANDS:
        ctl = [c for c in allc if band(c["ninki"]) == b]
        if len(ctl) < MIN_CONTROL:
            continue
        ch = sum(1 for c in ctl if key(c))
        print(f"  {b}  対照 n={len(ctl):,} {keyname}{ch/len(ctl):.1%}")
        for label, rows in groups:
            rr = [c for c in rows if band(c["ninki"]) == b]
            if len(rr) < MIN_CELL:
                print(f"    {label:<28} n={len(rr):>5}  母数不足")
                continue
            h = sum(1 for c in rr if key(c))
            v = power.judge(label, h, len(rr), ch, len(ctl))
            line = (f"    {label:<28} n={len(rr):>5}  {h/len(rr):>5.1%}"
                    f"  {(h/len(rr)-ch/len(ctl))*100:>+5.1f}p"
                    f"  要る差{v.mdd*100:>4.1f}p  {v.code}")
            if period:
                ps = []
                for y in (2025, 2026):
                    yy = [c for c in rr if c["date"].startswith(str(y))]
                    cc = [c for c in ctl if c["date"].startswith(str(y))]
                    if len(yy) < 40 or not cc:
                        ps.append(f"{y}:n={len(yy)}")
                        continue
                    r = sum(1 for x in yy if key(x)) / len(yy)
                    bb = sum(1 for x in cc if key(x)) / len(cc)
                    ps.append(f"{y}:{(r-bb)*100:+.1f}p")
                line += "  [" + " ".join(ps) + "]"
            print(line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="1-12")
    ap.add_argument("--target-races", default=DEFAULT_RACES)
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    a = ap.parse_args()

    info = load_race_info(Path(a.race_info))
    by_horse = load(a.dir, a.races)
    pairs = build_pairs(by_horse, a.target_races)
    allc = [c for _, c in pairs if c["ninki"] is not None]
    name_of = {id(r): n for n, lst in by_horse.items() for r in lst}
    print(f"馬 {len(by_horse):,}頭 / 前走ペア {len(pairs):,}組")

    # ---- B スローでの上がり差 ------------------------------------------
    ok = [(p, c) for p, c in pairs
          if c["ninki"] and p["pace"] is not None and p["agari_rank"]]
    report(f"B 前走の上がり順位をペースで条件付ける（{len(ok):,}）",
           [("前走スロー × 上がり3位以内",
             [c for p, c in ok if p["pace"] > 0 and p["agari_rank"] <= 3]),
            ("前走ハイ × 上がり3位以内",
             [c for p, c in ok if p["pace"] < 0 and p["agari_rank"] <= 3]),
            ("前走スロー × 上がり下位(4位以下)",
             [c for p, c in ok if p["pace"] > 0 and p["agari_rank"] > 3])],
           [c for _, c in ok])

    # ---- D 超スローで中団 ----------------------------------------------
    ok2 = [(p, c) for p, c in pairs
           if c["ninki"] and p["pace"] is not None and p["pos4"] and p["field"]]

    def chudan(p):
        return p["field"] / 3 <= p["pos4"] <= p["field"] * 2 / 3

    report(f"D 前走が超スロー × 4角中団（{len(ok2):,}）",
           [("超スロー × 中団", [c for p, c in ok2
                            if p["pace"] >= SLOW_HI and chudan(p)]),
            ("超スロー × 4角前(1/3以内)", [c for p, c in ok2
                                  if p["pace"] >= SLOW_HI
                                  and p["pos4"] < p["field"] / 3]),
            ("超スロー × 4角後方", [c for p, c in ok2
                             if p["pace"] >= SLOW_HI
                             and p["pos4"] > p["field"] * 2 / 3])],
           [c for _, c in ok2])

    # ---- ④ スロー専用 ---------------------------------------------------
    hist = {}
    for name, lst in by_horse.items():
        for i, r in enumerate(lst):
            ps = [q["pace"] for q in lst[max(0, i - 3):i] if q["pace"] is not None]
            if len(ps) >= 3:
                hist[(name, r["date"], r["R"])] = ps
    ok4 = [c for c in allc if (name_of.get(id(c)), c["date"], c["R"]) in hist]

    def h(c):
        return hist[(name_of[id(c)], c["date"], c["R"])]

    report(f"④ 前3走のペース経験（{len(ok4):,}）",
           [("前3走すべてスロー寄り", [c for c in ok4 if all(x > 0 for x in h(c))]),
            ("前3走すべてハイ寄り", [c for c in ok4 if all(x < 0 for x in h(c))])],
           ok4)

    # ---- 多頭数での勝ち鞍 ------------------------------------------------
    win16 = {}
    for name, lst in by_horse.items():
        for i, r in enumerate(lst):
            prev = lst[:i]
            win16[(name, r["date"], r["R"])] = (
                any(q["chaku"] == 1 and q["field"] >= 16 for q in prev),
                any(q["chaku"] == 1 for q in prev), len(prev))
    ok5 = [c for c in allc
           if (t := win16.get((name_of.get(id(c)), c["date"], c["R"]))) and t[2] >= 3]

    def w(c):
        return win16[(name_of[id(c)], c["date"], c["R"])]

    report(f"多頭数(16頭以上)での勝ち鞍（過去3走以上ある {len(ok5):,}）",
           [("16頭以上で勝ち鞍あり", [c for c in ok5 if w(c)[0]]),
            ("勝ち鞍はあるが16頭未満のみ", [c for c in ok5 if not w(c)[0] and w(c)[1]]),
            ("勝ち鞍が無い", [c for c in ok5 if not w(c)[1]])],
           ok5)

    # ---- 斤量②（距離帯ごと・レース平均との差） --------------------------
    kin = collections.defaultdict(list)
    for f in result_files(a.dir, a.target_races):
        ri = info.get(f.name.replace("_結果.csv", ""))
        if not ri:
            continue
        try:
            kyori = int(ri["距離"])
        except (ValueError, TypeError, KeyError):
            continue
        zone = ("短〜マイル(〜1600)" if kyori <= 1600
                else "中距離(1601-2000)" if kyori <= 2000 else "長距離(2001〜)")
        rows = [r for r in csv.DictReader(open(f, encoding="utf-8-sig"))
                if (r.get("着順") or "").isdigit()]
        ks = []
        for r in rows:
            try:
                ks.append(float(r["斤量"]))
            except (ValueError, KeyError, TypeError):
                pass
        if len(ks) < 5:
            continue
        m = statistics.fmean(ks)
        d = f.name[:10]
        for r in rows:
            nk = (r.get("人気") or "").strip()
            try:
                k = float(r["斤量"])
            except (ValueError, KeyError, TypeError):
                continue
            kin[zone].append({"date": d, "ninki": int(nk) if nk.isdigit() else None,
                              "chaku": int(r["着順"]), "d": k - m})
    for zone in ("短〜マイル(〜1600)", "中距離(1601-2000)", "長距離(2001〜)"):
        rr = [c for c in kin.get(zone, []) if c["ninki"]]
        if not rr:
            continue
        report(f"斤量 レース平均との差 — {zone}（{len(rr):,}）",
               [("平均+1.5kg以上", [c for c in rr if c["d"] >= 1.5]),
                ("平均+0.5〜1.4kg", [c for c in rr if 0.5 <= c["d"] < 1.5]),
                ("平均−1.5kg以下", [c for c in rr if c["d"] <= -1.5])], rr)

    # ---- 前年人気 --------------------------------------------------------
    tgt = set()
    for part in a.target_races.split(","):
        if "-" in part:
            x, y = part.split("-")
            tgt |= set(range(int(x), int(y) + 1))
        else:
            tgt.add(int(part))
    oldp = []
    for name, lst in by_horse.items():
        for i, cur in enumerate(lst):
            if cur["R"] not in tgt or cur["ninki"] is None:
                continue
            for q in lst[:i]:
                if q["ninki"] and 300 <= to_o(cur["date"]) - to_o(q["date"]) <= 430:
                    oldp.append((q, cur))
                    break
    report(f"前年人気（1年前の走りと比べた落ち幅・{len(oldp):,}）",
           [("5以上落とした", [c for p, c in oldp if c["ninki"] - p["ninki"] >= 5]),
            ("2-4落とした", [c for p, c in oldp if 2 <= c["ninki"] - p["ninki"] <= 4]),
            ("ほぼ同じ(±1)", [c for p, c in oldp if abs(c["ninki"] - p["ninki"]) <= 1]),
            ("2以上上げた", [c for p, c in oldp if c["ninki"] - p["ninki"] <= -2])],
           [c for _, c in oldp])

    # ---- ② 先行勢が多いレースで、先行馬は潰れるか -----------------------
    # 記事は「逃げ先行が多い→前総潰れ」。**発走前に分かる形**にすると
    # 「そのレースの先行勢の比率」× 「その馬の脚質」になる。
    ratio = {}
    for f in result_files(a.dir, a.target_races):
        stem = f.name.replace("_結果.csv", "")
        try:
            ent = list(csv.DictReader(
                open(str(f).replace("_結果.csv", "_出走馬.csv"), encoding="utf-8-sig")))
        except FileNotFoundError:
            continue
        ks = [(e.get("脚質") or "").strip() for e in ent]
        n = len([k for k in ks if k])
        if n >= 8:
            ratio[stem] = sum(1 for k in ks if k in ("逃げ", "先行")) / n
    stem_of = {}
    for f in result_files(a.dir, a.target_races):
        stem_of[(f.name[:10], f.name)] = stem_of
    # 今走の行に比率を付ける（date と R から stem を引く）
    by_key = {}
    for f in result_files(a.dir, a.target_races):
        stem = f.name.replace("_結果.csv", "")
        by_key.setdefault((f.name[:10], int(f.name.split("R_")[0][-2:])), stem)
    fwd = []
    for c in allc:
        st = by_key.get((c["date"], c["R"]))
        if st and st in ratio and c["kyaku"]:
            fwd.append({**c, "ratio": ratio[st]})
    print(f"\n■ ② 先行勢の比率 × その馬の脚質（{len(fwd):,}）")
    for lab, pick in (("逃げ・先行の馬", lambda c: c["kyaku"] in ("逃げ", "先行")),
                      ("差し・追込の馬", lambda c: c["kyaku"] in ("差し", "追込"))):
        sub = [c for c in fwd if pick(c)]
        report(f"  {lab}（{len(sub):,}）",
               [("先行勢が多いレース(55%以上)", [c for c in sub if c["ratio"] >= 0.55]),
                ("ふつう(25-55%)", [c for c in sub if 0.25 <= c["ratio"] < 0.55]),
                ("先行勢が少ないレース(25%未満)", [c for c in sub if c["ratio"] < 0.25])],
               sub)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
