#!/usr/bin/env python3
"""残りの検証対象の**該当母数を、人気帯ごとに数えるだけ**のスクリプト。

    python3 scripts/census.py --races 1-12 --target-races 9-12

## なぜ数えるだけのスクリプトを分けるか

馬体重の推移を測ったとき、全体で886頭あったのに人気帯へ割ると100〜300頭で、
そこで見える差は4〜15ptだった（期待する効果は数pt）。**着手前に数えていれば
「判定不能」と分かっていた。** CLAUDE.mdの仕分け条件3を
「同一人気帯内で判定するなら帯ごとに数える」に直した理由である。

だからこのスクリプトは**結論を出さない**。各仮説について

    帯ごとの該当数 → その母数で見分けられる差（MDD）

だけを出し、**測る価値があるかの判定材料にする**。MDDが期待する効果より
大きい仮説は、測る前に「判定不能」へ分類して終わりにする。

## 判定の目安（CLAUDE.mdの実測に基づく）
複勝率20〜50%の世界で単一要素が動かせるのは**数pt**である。既に確定した
ものの効果量は 乗り替わり+3.4p / ブリンカー解除−9.4p / 持ち時計+7.4p。
したがって

    MDD ≤ 5pt   … 測る価値がある（効いていれば見える）
    MDD 5〜8pt  … 大きい効果しか見えない（解除級なら見える）
    MDD > 8pt   … 測っても判定不能になる

レース単位の仮説（②逃げ先行の頭数・①週をまたぐ馬場）は人気帯で割らないので、
レース数と、レース単位の指標で見分けられる差を別に出す。
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import power
from keiba.racefiles import (DEFAULT_RACES, race_number, race_venue,
                             result_files)
from scripts.build_mochidokei import load_race_info, stem_date
from scripts.tenkai import band, build_pairs, load, to_o

BANDS = ["1-3番人気", "4-5番人気", "6-9番人気", "10番人気以下"]
GOOD, WEAK = 0.05, 0.08     # MDDの目安
SLOW_HI = 0.25              # 「超スロー」の閾値（pace.json の残差）


def verdict(mdd: float) -> str:
    if mdd <= GOOD:
        return "測れる"
    if mdd <= WEAK:
        return "大きい効果のみ"
    return "判定不能になる"


def census(title: str, groups, allc, key=lambda c: c["chaku"] <= 3,
           keyname="複勝率"):
    """groups は (ラベル, 今走の行の並び)。帯ごとに n と MDD を出す。"""
    print(f"\n■ {title}")
    base = {}
    for b in BANDS:
        ctl = [c for c in allc if band(c["ninki"]) == b]
        base[b] = (sum(1 for c in ctl if key(c)) / len(ctl), len(ctl)) if ctl else (0, 0)
    print(f"  対照の{keyname}: " + " / ".join(
        f"{b} {base[b][0]:.1%}(n={base[b][1]:,})" for b in BANDS))
    print(f"  {'区分':<26}{'全体':>7}" + "".join(f"{b:>16}" for b in BANDS))
    for label, rows in groups:
        cells = []
        for b in BANDS:
            rr = [c for c in rows if band(c["ninki"]) == b]
            p = base[b][0]
            if not rr or not p:
                cells.append(f"{'—':>16}")
                continue
            mdd = power.min_detectable_diff(len(rr), p)
            cells.append(f"{len(rr):>7,}/{mdd*100:>4.1f}p ")
        best = min((power.min_detectable_diff(
            len([c for c in rows if band(c["ninki"]) == b]), base[b][0])
            for b in BANDS if base[b][0] and
            [c for c in rows if band(c["ninki"]) == b]), default=1.0)
        print(f"  {label:<26}{len(rows):>7,}" + "".join(cells)
              + f"  → {verdict(best)}")
    print("  ※ 各セルは「該当数 / その母数で見分けられる差」")


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
    print(f"馬 {len(by_horse):,}頭 / 前走ペア {len(pairs):,}組 "
          f"（人気が分かる今走 {len(allc):,}）")

    # ---- B スローでの上がり差が大きい馬 -------------------------------
    ok = [(p, c) for p, c in pairs
          if c["ninki"] and p["pace"] is not None and p["agari_rank"]]
    g = [("前走スロー × 上がり1位", [c for p, c in ok
                             if p["pace"] > 0 and p["agari_rank"] == 1]),
         ("前走スロー × 上がり3位以内", [c for p, c in ok
                                if p["pace"] > 0 and p["agari_rank"] <= 3]),
         ("前走ハイ × 上がり3位以内", [c for p, c in ok
                               if p["pace"] < 0 and p["agari_rank"] <= 3])]
    census(f"B スローでの上がり差（前走のペースと上がり順位が分かる {len(ok):,}）",
           g, [c for _, c in ok])

    # ---- D 超スローで中団から着差をつけた馬 ---------------------------
    ok2 = [(p, c) for p, c in pairs
           if c["ninki"] and p["pace"] is not None and p["pos4"] and p["field"]]

    def chudan(p):
        return p["field"] / 3 <= p["pos4"] <= p["field"] * 2 / 3

    g2 = [("前走が超スロー × 中団 × 1-3着",
           [c for p, c in ok2 if p["pace"] >= SLOW_HI and chudan(p) and p["chaku"] <= 3]),
          ("前走が超スロー × 中団（着順不問）",
           [c for p, c in ok2 if p["pace"] >= SLOW_HI and chudan(p)]),
          ("前走が超スロー × 中団 × 1着",
           [c for p, c in ok2 if p["pace"] >= SLOW_HI and chudan(p) and p["chaku"] == 1])]
    census(f"D 超スローで中団から（前走のペースと4角が分かる {len(ok2):,}）",
           g2, [c for _, c in ok2])

    # ---- ④ 低レベルなスロー専用の馬 -----------------------------------
    hist = {}
    for name, lst in by_horse.items():
        for i, r in enumerate(lst):
            paces = [q["pace"] for q in lst[max(0, i - 3):i] if q["pace"] is not None]
            if len(paces) >= 3:
                hist[(name, r["date"], r["R"])] = paces

    def past(c, name):
        return hist.get((name, c["date"], c["R"]))

    name_of = {}
    for name, lst in by_horse.items():
        for r in lst:
            name_of[id(r)] = name
    ok4 = [c for c in allc if past(c, name_of.get(id(c), "")) is not None]
    g4 = [("前3走すべてスロー寄り",
           [c for c in ok4 if all(x > 0 for x in past(c, name_of[id(c)]))]),
          ("前3走すべてハイ寄り",
           [c for c in ok4 if all(x < 0 for x in past(c, name_of[id(c)]))])]
    census(f"④ スロー専用／ハイ経験（前3走のペースが分かる {len(ok4):,}）", g4, ok4)

    # ---- 多頭数を勝つ馬は強い ------------------------------------------
    win16 = collections.defaultdict(list)
    for name, lst in by_horse.items():
        for i, r in enumerate(lst):
            prev = lst[:i]
            win16[(name, r["date"], r["R"])] = (
                any(q["chaku"] == 1 and q["field"] >= 16 for q in prev),
                any(q["chaku"] == 1 for q in prev),
                len(prev))
    g5 = []
    for label, pick in (("16頭以上で勝ち鞍あり", lambda t: t[0]),
                        ("勝ち鞍はあるが16頭以上では無い",
                         lambda t: (not t[0]) and t[1]),
                        ("コーパス内に勝ち鞍が無い", lambda t: not t[1])):
        rows = [c for c in allc
                if (t := win16.get((name_of.get(id(c), ""), c["date"], c["R"])))
                and t[2] >= 3 and pick(t)]
        g5.append((label, rows))
    census("多頭数(16頭以上)での勝ち鞍（過去3走以上ある馬）", g5, allc)

    # ---- 斤量②（長距離のほうが斤量差が効く） --------------------------
    kin = collections.defaultdict(list)
    for f in result_files(a.dir, a.target_races):
        stem = f.name.replace("_結果.csv", "")
        ri = info.get(stem)
        if not ri:
            continue
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
        try:
            kyori = int(ri["距離"])
        except (ValueError, TypeError, KeyError):
            continue
        zone = ("短〜マイル(〜1600)" if kyori <= 1600
                else "中距離(1601-2000)" if kyori <= 2000
                else "長距離(2001〜)")
        for r in rows:
            nk = (r.get("人気") or "").strip()
            try:
                k = float(r["斤量"])
            except (ValueError, KeyError, TypeError):
                continue
            kin[zone].append({
                    "ninki": int(nk) if nk.isdigit() else None,
                    "chaku": int(r["着順"]), "d": k - m})
    print("\n■ 斤量②（レース平均との差・距離帯ごと）")
    for zone, rows in kin.items():
        rr = [c for c in rows if c["ninki"]]
        g6 = [("平均+1.5kg以上", [c for c in rr if c["d"] >= 1.5]),
              ("平均−1.5kg以下", [c for c in rr if c["d"] <= -1.5])]
        census(f"  {zone}（{len(rr):,}）", g6, rr)

    # ---- 前年人気（約1年前と比べて人気を落とした馬） -------------------
    oldpair = []
    for name, lst in by_horse.items():
        tgt = {int(x) for part in a.target_races.split(",")
               for x in ([part] if "-" not in part else
                         range(int(part.split("-")[0]), int(part.split("-")[1]) + 1))}
        for i, cur in enumerate(lst):
            if cur["R"] not in tgt or cur["ninki"] is None:
                continue
            for q in lst[:i]:
                if q["ninki"] and 300 <= to_o(cur["date"]) - to_o(q["date"]) <= 430:
                    oldpair.append((q, cur))
                    break
    g7 = [("1年前より人気を5以上落とした",
           [c for p, c in oldpair if c["ninki"] - p["ninki"] >= 5]),
          ("1年前より人気を2-4落とした",
           [c for p, c in oldpair if 2 <= c["ninki"] - p["ninki"] <= 4]),
          ("1年前とほぼ同じ(±1)",
           [c for p, c in oldpair if abs(c["ninki"] - p["ninki"]) <= 1])]
    census(f"前年人気（1年前(300-430日)の走りと突き合わせた {len(oldpair):,}）",
           g7, [c for _, c in oldpair])

    # ---- ② 逃げ先行の頭数（レース単位） --------------------------------
    races = []
    for f in result_files(a.dir, a.target_races):
        stem = f.name.replace("_結果.csv", "")
        try:
            ent = list(csv.DictReader(
                open(str(f).replace("_結果.csv", "_出走馬.csv"), encoding="utf-8-sig")))
        except FileNotFoundError:
            continue
        ks = [(e.get("脚質") or "").strip() for e in ent]
        n = len([k for k in ks if k])
        if n < 8:
            continue
        fwd = sum(1 for k in ks if k in ("逃げ", "先行"))
        races.append({"stem": stem, "n": n, "ratio": fwd / n, "fwd": fwd})
    print("\n■ ② 逃げ先行の頭数（レース単位・人気帯で割らない）")
    qs = sorted(r["ratio"] for r in races)
    print(f"  対象 {len(races):,}レース  先行勢の比率: "
          f"中央値{qs[len(qs)//2]:.0%} 10%点{qs[len(qs)//10]:.0%} "
          f"90%点{qs[9*len(qs)//10]:.0%}")
    for lo, hi, lab in ((0.0, 0.25, "25%未満"), (0.25, 0.4, "25-40%"),
                        (0.4, 0.55, "40-55%"), (0.55, 1.01, "55%以上")):
        sub = [r for r in races if lo <= r["ratio"] < hi]
        print(f"    先行勢{lab:<8} {len(sub):>5,}レース")
    print("  ※ レース単位の指標（上位3着の4角位置）は連続値なので、"
          "判定は率ではなく平均差で行う")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
