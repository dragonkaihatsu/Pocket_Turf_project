#!/usr/bin/env python3
"""前走の展開（ペース）と位置取りの組み合わせで、今走の成績が変わるかを測る。

    python3 scripts/tenkai.py --races 1-12 --target-races 9-12

## 何を測るか（記事の主張を検証可能な形に落としたもの）

差し馬の見分け方として紹介された主張は、詰めると**1つの組み合わせ**になる:

  「前が潰れたレース（ハイペース）を差し切った馬は強くない（＝バテ差し）。
    逆に、前残り（スロー）の流れを差し切った馬は強い」

これは CLAUDE.md の設計原則の**後者**（組み合わせでしか見えない）に当たる。
馬柱に出るのは着順だけで、**その着順がどんなペースの中で出たかは並べて
突き合わせないと見えない**。既に生き残っている代理B（前に行く脚質なのに
4角後方＝出遅れ疑い）の鏡像にあたる。

## ペース指標は収集ゼロで作る（`data/profiles/jra/pace.json`）

勝ち馬の **前半の1F平均 − 上がり3Fの1F平均** を、同じ(場×芝ダ×距離)の
平均からの残差で持つ。正なら前半が相対的に遅い＝スロー＝前残り寄り。

netkeiba自身の `ペース:S/M/H` と突き合わせると
**S +0.246 / M +0.004 / H −0.232（3,747本）** と完全に単調一致した。
ラップ表のキャッシュは68%しか無いが、この代理は**結果CSVだけで99%**作れる。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import power
from keiba.racefiles import DEFAULT_RACES, race_number, result_paths

STAKE = 100
DATE_RE = re.compile(r".*/(\d{4}-\d{2}-\d{2})_")
# 「差した」の閾値。代理B と同じ 4角6番手以下に合わせて比較可能にする
BACK_POS = 6


def parse_corner(s, n):
    toks = re.findall(r"\d+", s)
    out = []
    for t in toks:
        v = int(t)
        if v <= 18:
            out.append(v)
        else:
            out.extend(int(c) for c in t)
    if len(set(out)) != len(out) or not (n - 2 <= len(out) <= n):
        return None
    return out


def load(directory: str, races: str) -> dict[str, list[dict]]:
    pace = json.loads(Path("data/profiles/jra/pace.json").read_text(encoding="utf-8"))
    # 4コーナーの隊列。netkeibaの通過順表記は馬身差を記号で持っている
    #   (..)=併走  ,=1馬身以内  -=2〜4馬身  ==5馬身以上
    # ここから「1頭あたり平均間隔」を出すと、ハイペース0.46馬身→スロー0.30馬身と
    # 単調に動く（物理的に正しい向き。5,889レース=99%で読める）
    taire = json.loads(Path("data/profiles/jra/taire.json").read_text(encoding="utf-8"))
    by_horse: dict[str, list[dict]] = defaultdict(list)
    for f in result_paths(directory, races):
        m = DATE_RE.match(f)
        if not m:
            continue
        d = m.group(1)
        stem = Path(f).name.replace("_結果.csv", "")
        pay_t, pay_f = {}, {}
        try:
            for p in csv.DictReader(open(f.replace("_結果.csv", "_配当.csv"),
                                         encoding="utf-8-sig")):
                if p.get("券種") == "単勝":
                    pay_t[int(p["組み合わせ"])] = int(p["配当"])
                elif p.get("券種") == "複勝":
                    pay_f[int(p["組み合わせ"])] = int(p["配当"])
        except (FileNotFoundError, ValueError):
            pass
        ent = {}
        try:
            for e in csv.DictReader(open(f.replace("_結果.csv", "_出走馬.csv"),
                                         encoding="utf-8-sig")):
                nm = (e.get("馬名") or "").strip()
                iv = e.get("前走間隔日数") or ""
                if nm:
                    ent[nm] = {"interval": int(iv) if iv.isdigit() else None,
                               "kyaku": (e.get("脚質") or "").strip()}
        except FileNotFoundError:
            pass
        rows = [r for r in csv.DictReader(open(f, encoding="utf-8-sig"))
                if (r.get("着順") or "").isdigit()]
        if not rows:
            continue
        ag = []
        for r in rows:
            try:
                ag.append((float(r["上がり3F"]), r["馬番"]))
            except (ValueError, KeyError):
                pass
        ag.sort()
        agari_rank = {ub: i for i, (_, ub) in enumerate(ag, start=1)}
        pos4 = {}
        try:
            cs = list(csv.DictReader(open(f.replace("_結果.csv", "_通過順.csv"),
                                          encoding="utf-8-sig")))
            lc = parse_corner(cs[-1].get("通過順") or "", len(rows)) if cs else None
            if lc:
                pos4 = {ub: i for i, ub in enumerate(lc, start=1)}
        except FileNotFoundError:
            pass
        for r in rows:
            nm = (r.get("馬名") or "").strip()
            ub = r.get("馬番") or ""
            nk = r.get("人気") or ""
            if not (nm and ub.isdigit()):
                continue
            e = ent.get(nm, {})
            by_horse[nm].append({
                "date": d, "R": race_number(Path(f).name), "chaku": int(r["着順"]),
                "field": len(rows), "ninki": int(nk) if nk.isdigit() else None,
                "agari_rank": agari_rank.get(ub), "pos4": pos4.get(int(ub)),
                "kyaku": e.get("kyaku", ""), "interval": e.get("interval"),
                "pace": pace.get(stem),
                "tate": (taire.get(stem) or {}).get("縦長"),
                "tan": pay_t.get(int(ub), 0), "fuku": pay_f.get(int(ub), 0)})
    for v in by_horse.values():
        v.sort(key=lambda x: x["date"])
    return by_horse


def to_o(s):
    y, m, dd = (int(x) for x in s.split("-"))
    return date(y, m, dd).toordinal()


def build_pairs(by_horse, target_races: str) -> list[tuple[dict, dict]]:
    tgt = set()
    for part in target_races.split(","):
        if "-" in part:
            a, b = part.split("-")
            tgt |= set(range(int(a), int(b) + 1))
        else:
            tgt.add(int(part))
    pairs = []
    for lst in by_horse.values():
        for i in range(1, len(lst)):
            cur = lst[i]
            if cur["interval"] is None or cur["R"] not in tgt:
                continue
            t = to_o(cur["date"]) - cur["interval"]
            for cand in lst[:i][::-1]:
                if abs(to_o(cand["date"]) - t) <= 2:
                    pairs.append((cand, cur))
                    break
    return pairs


def band(n):
    if n is None:
        return None
    return ("1-3番人気" if n <= 3 else "4-5番人気" if n <= 5
            else "6-9番人気" if n <= 9 else "10番人気以下")


def sashi(p) -> bool:
    """前走で後方から運んだか。4角位置が取れなければ脚質で代替。"""
    if p["pos4"] is not None:
        return p["pos4"] >= BACK_POS
    return p["kyaku"] in ("差し", "追込")


def maeni(p) -> bool:
    if p["pos4"] is not None:
        return p["pos4"] <= 3
    return p["kyaku"] in ("逃げ", "先行")


def report(title, cells, control, period=None):
    print(f"\n■ {title}")
    print(power.HEADER)
    ck = sum(1 for r in control if r["chaku"] <= 3)
    cw = sum(1 for r in control if r["chaku"] == 1)
    print(f"{'対照: 前走3着以内（全体）':<32}{len(control):>6}"
          f"{ck/len(control):>7.1%}{'':>16}{'':>6}{'':>7}{'':>8}  —")
    for label, rows, use_win in cells:
        if not rows:
            print(f"{label:<32} 該当なし")
            continue
        hits = sum(1 for r in rows if (r["chaku"] == 1 if use_win else r["chaku"] <= 3))
        base_h, base_n = (cw, len(control)) if use_win else (ck, len(control))
        v = power.judge(label, hits, len(rows), base_h, base_n)
        roi = sum(r["tan"] if use_win else r["fuku"] for r in rows) / (len(rows) * STAKE)
        print(f"{v.label:<32}{v.n:>6}{v.rate:>7.1%}  {v.ci[0]:>6.1%}-{v.ci[1]:<7.1%}"
              f"{v.diff*100:>+6.1f}{v.mdd*100:>7.1f}{v.need_n:>8}  {v.code}"
              f"  回収{roi:>5.0%}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="1-12")
    ap.add_argument("--target-races", default=DEFAULT_RACES)
    ap.add_argument("--slow", type=float, default=0.15,
                    help="この残差以上を前残り(スロー)寄りとする")
    a = ap.parse_args()

    by_horse = load(a.dir, a.races)
    pairs = build_pairs(by_horse, a.target_races)
    pairs = [(p, c) for p, c in pairs if p["pace"] is not None]
    print(f"馬 {len(by_horse):,}頭 / 前走ペアでペースが分かるもの {len(pairs):,}組")

    slow = [(p, c) for p, c in pairs if p["pace"] >= a.slow]
    fast = [(p, c) for p, c in pairs if p["pace"] <= -a.slow]
    print(f"  前走が前残り(スロー)寄り {len(slow):,} / 前崩れ(ハイ)寄り {len(fast):,}")

    good = [(p, c) for p, c in pairs if p["chaku"] <= 3]
    control = [c for _, c in good]

    # 記事の③「縦長スローで差し損ねた本当は強い馬を探す」
    tates = sorted(p["tate"] for p, _ in pairs if p["tate"] is not None)
    if tates:
        hi = tates[2 * len(tates) // 3]      # 縦長（上位1/3）
        lo = tates[len(tates) // 3]          # 団子（下位1/3）
        miss = [(p, c) for p, c in pairs if p["chaku"] >= 4]
        ctl_miss = [c for _, c in miss]
        cells_m = [
            ("差し損ね × 前走が縦長スロー",
             [c for p, c in miss if sashi(p) and p["tate"] is not None
              and p["tate"] >= hi and p["pace"] >= a.slow], False),
            ("差し損ね × 前走が団子スロー",
             [c for p, c in miss if sashi(p) and p["tate"] is not None
              and p["tate"] <= lo and p["pace"] >= a.slow], False),
            ("差し損ね × 前走が縦長ハイ",
             [c for p, c in miss if sashi(p) and p["tate"] is not None
              and p["tate"] >= hi and p["pace"] <= -a.slow], False),
        ]
        print(f"\n（隊列の四分位: 団子 ≦{lo:.2f} / 縦長 ≧{hi:.2f} 馬身）")
        report(f"記事③ 前走で差し損ねた馬（対照: 前走4着以下 全体・{len(ctl_miss):,}）",
               cells_m, ctl_miss)
        print("\n  期間で割る")
        for label, rows, _ in cells_m:
            line = []
            for y in (2025, 2026):
                rr = [c for c in rows if c["date"].startswith(str(y))]
                cc = [c for c in ctl_miss if c["date"].startswith(str(y))]
                if len(rr) < 40 or not cc:
                    line.append(f"{y}: n={len(rr)} 母数不足")
                    continue
                r = sum(1 for x in rr if x["chaku"] <= 3) / len(rr)
                b = sum(1 for x in cc if x["chaku"] <= 3) / len(cc)
                line.append(f"{y}: {r:.1%} ({(r-b)*100:+.1f}p, n={len(rr)})")
            print(f"    {label:<30} " + " / ".join(line))

    cells_p = [
        ("差して好走 × 前走が前残り", [c for p, c in slow if p["chaku"] <= 3 and sashi(p)], False),
        ("差して好走 × 前走が前崩れ(バテ差し疑い)", [c for p, c in fast if p["chaku"] <= 3 and sashi(p)], False),
        ("前で好走 × 前走が前残り(恵まれ疑い)", [c for p, c in slow if p["chaku"] <= 3 and maeni(p)], False),
        ("前で好走 × 前走が前崩れ(粘った)", [c for p, c in fast if p["chaku"] <= 3 and maeni(p)], False),
    ]
    report(f"複勝率（今走{a.target_races}R・前走3着以内を対照）", cells_p, control)
    cells_w = [(lab, rows, True) for lab, rows, _ in cells_p]
    report("勝率（同じ区分）", cells_w, control)

    print("\n■ 人気帯の中での複勝リフト（価格を固定して精度だけ比べる）")
    for b in ("1-3番人気", "4-5番人気", "6-9番人気", "10番人気以下"):
        sub = [c for c in control if band(c["ninki"]) == b]
        if len(sub) < 60:
            continue
        base = sum(1 for r in sub if r["chaku"] <= 3)
        print(f"  {b}  対照 n={len(sub):,} 複勝率{base/len(sub):.1%}")
        for label, rows, _ in cells_p:
            rr = [c for c in rows if band(c["ninki"]) == b]
            if len(rr) < 40:
                print(f"    {label:<34} n={len(rr):>4}  母数不足")
                continue
            h = sum(1 for r in rr if r["chaku"] <= 3)
            v = power.judge(label, h, len(rr), base, len(sub))
            print(f"    {label:<34} n={len(rr):>4}  {h/len(rr):>5.1%}"
                  f"  {(h/len(rr)-base/len(sub))*100:>+5.1f}p  要る差{v.mdd*100:>4.1f}p  {v.code}")

    print("\n■ 期間で割る（2025 / 2026）")
    for label, rows, _ in cells_p:
        line = []
        for y in (2025, 2026):
            rr = [c for c in rows if c["date"].startswith(str(y))]
            cc = [c for c in control if c["date"].startswith(str(y))]
            if len(rr) < 40 or not cc:
                line.append(f"{y}: n={len(rr)} 母数不足")
                continue
            r = sum(1 for x in rr if x["chaku"] <= 3) / len(rr)
            b = sum(1 for x in cc if x["chaku"] <= 3) / len(cc)
            line.append(f"{y}: {r:.1%} ({(r-b)*100:+.1f}p, n={len(rr)})")
        print(f"  {label:<34} " + " / ".join(line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
