#!/usr/bin/env python3
"""馬体重の**推移**を同一人気帯内で検証する（絶対値ではなく増減のトレンド）。

    python3 scripts/bataijyu.py --races 1-12 --target-races 9-12

記事の主張（本人が「次にやる候補として筋が良い」と挙げた形）:

    デビューから**減り続け**ている馬は疑問視する
    デビューから**増え続け**ている馬は本格化のサイン

絶対馬体重（410kg前後は軽視）は既に測って「人気馬に限って正しいが該当2.8%」
という結果だった。こちらは**2走以上を突き合わせないと見えない**side で、
設計原則（馬柱にそのまま載っているものは織り込み済み／組み合わせでしか
見えないものは織り込まれていない）の後者に当たる。

## 「デビューから」は測れないので直近3走で近似する
コーパスは2年ぶん（2025-01〜2026-09）なので、馬のキャリア全体は見えない。
`前3走の増減がすべて同符号` を代理にする。**これは記事の主張そのものでは
ない**（デビューからの単調性より弱い条件）ので、結論もそこまでしか言えない。

増減は結果CSVの `馬体重` 列の括弧（netkeiba自身が出している前走比）を読む。
自分でペアを組むより取りこぼしが少ない（前走がコーパス外でも値が入っている）。
ただし**3走ぶんの括弧が要る**ので、コーパス内に3走以上ある馬に限られる。

## 年齢で必ず割る
3歳以下は成長で増えるので、「増え続け」が効いても**若馬を拾っているだけ**
かもしれない。年齢を分けないとこの交絡を分離できない。
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import power
from keiba.racefiles import DEFAULT_RACES, parse_months, race_number, result_files

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")
WEIGHT_RE = re.compile(r"(\d+)\(([+-]?\d+)\)")
AGE_RE = re.compile(r"(\d+)")
BANDS = ["1-3番人気", "4-5番人気", "6-9番人気", "10番人気以下"]
RUNS = 3           # 何走ぶんの増減を見るか
MIN_BAND_N = 60    # 帯ごとに表示する下限
MIN_CONTROL = 200


def band(n):
    if n is None:
        return None
    return ("1-3番人気" if n <= 3 else "4-5番人気" if n <= 5
            else "6-9番人気" if n <= 9 else "10番人気以下")


def parse_races(spec):
    out = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out |= set(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def load(directory, races, months=None):
    by_horse = defaultdict(list)
    for p in result_files(directory, races):
        m = DATE_RE.match(p.name)
        if not m:
            continue
        d = m.group(1)
        if months and d[:7] not in months:
            continue
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            nm = (r.get("馬名") or "").strip()
            ch = (r.get("着順") or "").strip()
            if not (nm and ch.isdigit()):
                continue
            w = WEIGHT_RE.search((r.get("馬体重") or "").strip())
            nk = (r.get("人気") or "").strip()
            od = (r.get("単勝オッズ") or "").strip()
            age = AGE_RE.search((r.get("性齢") or "").strip())
            try:
                odds = float(od)
            except ValueError:
                odds = None
            by_horse[nm].append({
                "date": d, "R": race_number(p.name), "chaku": int(ch),
                "ninki": int(nk) if nk.isdigit() else None,
                "odds": odds,
                "age": int(age.group(1)) if age else None,
                "weight": int(w.group(1)) if w else None,
                "delta": int(w.group(2)) if w else None,
            })
    for v in by_horse.values():
        v.sort(key=lambda x: x["date"])
    return by_horse


def build(by_horse, target_races):
    """今走が対象帯で、直近RUNS走ぶんの増減が分かる出走を集める。"""
    tgt = parse_races(target_races)
    rows = []
    for lst in by_horse.values():
        for i, cur in enumerate(lst):
            if cur["R"] not in tgt or cur["ninki"] is None:
                continue
            prev = [x["delta"] for x in lst[max(0, i - RUNS):i]]
            if len(prev) < RUNS or any(x is None for x in prev):
                continue
            rows.append({**cur, "deltas": prev, "cum": sum(prev)})
    return rows


def tanpuku_pay(c):
    """単勝の払戻（1点100円あたり）。外れは0。"""
    if c["chaku"] == 1 and c["odds"]:
        return c["odds"] * 100.0
    return 0.0


def report(title, groups, rows_all, key, keyname):
    print(f"\n■ {title}（{keyname}）")
    for b in BANDS:
        ctl = [c for c in rows_all if band(c["ninki"]) == b]
        if len(ctl) < MIN_CONTROL:
            continue
        ch = sum(1 for c in ctl if key(c))
        print(f"  {b}  対照 n={len(ctl):,} {keyname}{ch/len(ctl):.1%}")
        for label, rows in groups:
            rr = [c for c in rows if band(c["ninki"]) == b]
            if len(rr) < MIN_BAND_N:
                print(f"    {label:<22} n={len(rr):>5}  母数不足")
                continue
            h = sum(1 for c in rr if key(c))
            v = power.judge(label, h, len(rr), ch, len(ctl))
            print(f"    {label:<22} n={len(rr):>5}  {h/len(rr):>5.1%}"
                  f"  {(h/len(rr)-ch/len(ctl))*100:>+5.1f}p"
                  f"  要る差{v.mdd*100:>4.1f}p  {v.code}")


def period(groups, rows_all, key, keyname, bands=BANDS):
    print(f"\n  期間で割る（{keyname}・帯ごと）")
    for b in bands:
        base = [c for c in rows_all if band(c["ninki"]) == b]
        if len(base) < MIN_CONTROL:
            continue
        print(f"    {b}")
        for label, rows in groups:
            line = []
            for y in (2025, 2026):
                rr = [c for c in rows
                      if c["date"].startswith(str(y)) and band(c["ninki"]) == b]
                cc = [c for c in base if c["date"].startswith(str(y))]
                if len(rr) < MIN_BAND_N or not cc:
                    line.append(f"{y}: n={len(rr)} 母数不足")
                    continue
                r = sum(1 for x in rr if key(x)) / len(rr)
                bb = sum(1 for x in cc if key(x)) / len(cc)
                line.append(f"{y}: {r:5.1%} ({(r-bb)*100:+5.1f}p, n={len(rr):>4})")
            print(f"      {label:<22} " + " / ".join(line))


def roi(groups, rows_all):
    print("\n■ 単勝回収率（参考）")
    print("  " + power.ROI_HEADER)
    allpay = [tanpuku_pay(c) for c in rows_all]
    for label, rows in groups:
        if len(rows) < MIN_BAND_N:
            continue
        v = power.judge_roi(label, [tanpuku_pay(c) for c in rows], allpay)
        if v:
            print("  " + v.line() + f"  的中{v.hits}本")
    print("  ※ 回収率は同じ優位を見るのに正解率の4〜9倍の母数を要する。"
          "この母数では判定できないのが既定")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="1-12", help="履歴に使う帯")
    ap.add_argument("--target-races", default=DEFAULT_RACES, help="測定対象の帯")
    ap.add_argument("--months", default=None, help="例 2025-01..2026-09")
    a = ap.parse_args()

    months = parse_months(a.months) if a.months else None
    by_horse = load(a.dir, a.races, months)
    rows = build(by_horse, a.target_races)
    print(f"馬 {len(by_horse):,}頭 / 前{RUNS}走の増減が分かる出走 {len(rows):,}")

    up = [c for c in rows if all(d > 0 for d in c["deltas"])]
    down = [c for c in rows if all(d < 0 for d in c["deltas"])]
    mixed = [c for c in rows
             if not (all(d > 0 for d in c["deltas"]) or all(d < 0 for d in c["deltas"]))]
    groups = [(f"{RUNS}走連続で増", up), (f"{RUNS}走連続で減", down), ("まちまち", mixed)]
    print(f"  連続増 {len(up):,} / 連続減 {len(down):,} / まちまち {len(mixed):,}")

    fuku = (lambda c: c["chaku"] <= 3, "複勝率")
    win = (lambda c: c["chaku"] == 1, "勝率")

    report("記事「増え続けは本格化／減り続けは疑問視」", groups, rows, *fuku)
    report("同上", groups, rows, *win)
    period(groups, rows, *fuku)

    # 累計の増減量（符号だけでなく大きさを見る）
    cum = [("累計+20kg以上", [c for c in rows if c["cum"] >= 20]),
           ("累計+10〜19kg", [c for c in rows if 10 <= c["cum"] < 20]),
           ("累計±9kg以内", [c for c in rows if abs(c["cum"]) <= 9]),
           ("累計−10〜19kg", [c for c in rows if -19 < c["cum"] <= -10]),
           ("累計−20kg以下", [c for c in rows if c["cum"] <= -20])]
    report(f"前{RUNS}走の累計増減量", cum, rows, *fuku)
    period(cum, rows, *fuku, bands=["1-3番人気"])

    # 年齢の交絡（3歳以下は成長で増える）
    for lo, hi, name in ((0, 3, "3歳以下"), (4, 99, "4歳以上")):
        sub = [c for c in rows if c["age"] and lo <= c["age"] <= hi]
        g = [(lab, [c for c in rr if c["age"] and lo <= c["age"] <= hi])
             for lab, rr in groups]
        print(f"\n=== 年齢 {name}（対象 {len(sub):,}） ===")
        report(f"増減の推移 × {name}", g, sub, *fuku)

    roi(groups, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
