#!/usr/bin/env python3
"""正解率の優位が、なぜ回収率には見えないのかを母数で説明する。

## 問い

CLAUDE.mdは「正解率は期間をまたいで再現する量、回収率は再現しない量」と
記録してきた。だが**再現しない理由を2つに分けていなかった**:

  (A) 正解率の優位が価格に織り込まれていて、回収率の優位が存在しない
  (B) 優位は存在するが、回収率は分散が大きく、同じ優位を見るのに
      正解率の何十倍もの母数が要る

(A)なら追う価値は無いが、(B)なら「まだ見えていない」だけで話が違う。
CLAUDE.mdが仮説ごとにやってきた「必要な母数を先に見積もる」を、
**回収率そのものに当てる**。

## 測り方

同じ区分の同じ馬について、2つの量の検出力を並べる:

  正解率（勝率・複勝率）… 二項なので `keiba/power.py` の required_n が使える
  回収率              … 払戻は確率の逆数なので裾が重い。1頭あたりの
                          払戻の標準偏差から必要な母数を出す

    必要n = (z_α + z_β)^2 × σ² / Δ²

σ は実測の払戻のばらつき（円/1点100円）、Δ は見たい回収率の差。
**同じ式・同じ有意水準・同じ検出力**で並べるので、母数の要求量を直接
比べられる。ブートストラップで回収率の90%区間も出す。

    python3 scripts/roi_power.py --races 1-12 --target-races 9-12 \
        --months 2025-01..2026-05
"""
from __future__ import annotations

import argparse
import csv
import random
import re
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.power import Z_ALPHA, Z_BETA, required_n, wilson
from keiba.racefiles import (DEFAULT_RACES, complete_months, parse_races,
                             race_number, result_paths)
from keiba.scoring import tier1_min_rides

DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})_")
STAKE = 100


def parse_corner(s: str, n: int) -> list[int] | None:
    """通過順の文字列を馬番の並びにする（`scripts/review_hypotheses.py` と同じ）。

    "5,3,1-2,4" のように区切りが混在し、2桁馬番が連結されていることも
    あるため、18を超える数は1桁ずつに割る。重複したり頭数と合わない
    ときは None（読めないものを読めたことにしない）。
    """
    out: list[int] = []
    for t in re.findall(r"\d+", s or ""):
        v = int(t)
        if v <= 18:
            out.append(v)
        else:
            out.extend(int(c) for c in t)
    if len(set(out)) != len(out) or not (n - 2 <= len(out) <= n):
        return None
    return out


def load(directory: str, races: str, months: str | None):
    """前走→今走のペアを作る。払戻は結果CSVと配当CSVから。"""
    by_horse: dict[str, list[dict]] = defaultdict(list)
    rides: dict[str, int] = defaultdict(int)
    for f in result_paths(directory, races, months):
        m = DATE_RE.search(Path(f).name)
        if not m:
            continue
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        pay_t: dict[int, int] = {}
        try:
            for p in csv.DictReader(open(f.replace("_結果.csv", "_配当.csv"),
                                         encoding="utf-8-sig")):
                if p.get("券種") == "単勝":
                    pay_t[int(p["組み合わせ"])] = int(p["配当"])
        except (FileNotFoundError, ValueError, KeyError):
            pass
        ent: dict[str, dict] = {}
        try:
            for e in csv.DictReader(open(f.replace("_結果.csv", "_出走馬.csv"),
                                         encoding="utf-8-sig")):
                nm = (e.get("馬名") or "").strip()
                if nm:
                    iv = (e.get("前走間隔日数") or "").strip()
                    ent[nm] = {"interval": int(iv) if iv.isdigit() else None,
                               "kyaku": (e.get("脚質") or "").strip()}
        except FileNotFoundError:
            pass
        rows = [r for r in csv.DictReader(open(f, encoding="utf-8-sig"))
                if (r.get("着順") or "").isdigit()]
        # 通過順CSVは「コーナー,通過順」の2列で、通過順は馬番を順に並べた
        # 文字列（"5,3,1-2,4"）。最終コーナーの並びから順位を作る
        corner: dict[int, int] = {}
        try:
            cs = list(csv.DictReader(
                open(f.replace("_結果.csv", "_通過順.csv"),
                     encoding="utf-8-sig")))
            order = parse_corner(cs[-1].get("通過順") or "", len(rows)) if cs else None
            if order:
                corner = {ub: i for i, ub in enumerate(order, start=1)}
        except (FileNotFoundError, IndexError):
            pass
        for r in rows:
            nm = (r.get("馬名") or "").strip()
            ch = (r.get("着順") or "").strip()
            ub = (r.get("馬番") or "").strip()
            jk = (r.get("騎手") or "").strip()
            if not nm or not ch.isdigit() or not ub.isdigit():
                continue
            rides[jk] += 1
            e = ent.get(nm, {})
            by_horse[nm].append({
                "date": d, "R": race_number(Path(f).name),
                "chaku": int(ch), "jockey": jk, "umaban": int(ub),
                "interval": e.get("interval"), "kyaku": e.get("kyaku", ""),
                "pos4": corner.get(int(ub)),
                "tan": pay_t.get(int(ub), 0),
            })
    for v in by_horse.values():
        v.sort(key=lambda x: x["date"])
    return by_horse, rides


def make_pairs(by_horse, target):
    pairs = []
    for lst in by_horse.values():
        for i in range(1, len(lst)):
            cur = lst[i]
            if cur["interval"] is None:
                continue
            if target is not None and cur["R"] not in target:
                continue
            t = cur["date"].toordinal() - cur["interval"]
            for cand in lst[:i][::-1]:
                if abs(cand["date"].toordinal() - t) <= 2:
                    pairs.append((cand, cur))
                    break
    return pairs


def roi_stats(rows: list[dict]) -> dict:
    """1頭あたりの払戻から回収率・ばらつき・必要母数を出す。"""
    pay = [r["tan"] for r in rows]
    n = len(pay)
    if n < 2:
        return {}
    mean = statistics.mean(pay)
    sd = statistics.stdev(pay)
    rng = random.Random(20260912)
    boot = sorted(statistics.mean(rng.choices(pay, k=n)) / STAKE
                  for _ in range(2000))
    return {"n": n, "roi": mean / STAKE, "sd": sd / STAKE,
            "lo": boot[100], "hi": boot[1900],
            "hits": sum(1 for p in pay if p > 0)}


def need_for_roi(sd: float, diff: float) -> int:
    """回収率の差 diff（例 0.30 = 30pt）を見分けるのに要る母数。"""
    if diff <= 0 or sd <= 0:
        return 0
    return int(((Z_ALPHA + Z_BETA) ** 2 * 2 * sd ** 2) / diff ** 2) + 1


# 1-8Rを含めて収集できている月数。必要母数に何年ぶんで届くかを出すため。
# `keiba.racefiles.complete_months` で数えた値を渡す
def project(n_now: int, need: int, months_now: int) -> str:
    """いまの母数と必要母数から、あと何ヶ月ぶんの収集が要るかを見積もる。

    前走ペアの数は収集した月数にほぼ比例する（1頭が何走するかは
    期間に比例するため）。厳密ではないが桁は合う。
    """
    if n_now <= 0 or need <= n_now or months_now <= 0:
        return "届いている"
    months = months_now * need / n_now
    return (f"あと{months - months_now:.0f}ヶ月ぶん"
            f"（通算{months / 12:.1f}年ぶんの1-12R収集）")


def report(label: str, test: list[dict], ctrl: list[dict],
           months_now: int = 0) -> None:
    t, c = roi_stats(test), roi_stats(ctrl)
    if not t or not c:
        print(f"  {label}: 母数不足")
        return
    # 正解率（勝率）側
    wt = sum(1 for r in test if r["chaku"] == 1) / t["n"]
    wc = sum(1 for r in ctrl if r["chaku"] == 1) / c["n"]
    lo, hi = wilson(sum(1 for r in test if r["chaku"] == 1), t["n"])
    need_rate = required_n(wc, abs(wt - wc)) if wt != wc else 0
    # 回収率側
    need_roi = need_for_roi(max(t["sd"], c["sd"]), abs(t["roi"] - c["roi"]))
    print(f"\n■ {label}")
    print(f"  母数 検証{t['n']:,} / 対照{c['n']:,}")
    print(f"  勝率     {wt:>7.1%} 対 {wc:>7.1%}  差{(wt-wc)*100:+5.1f}pt"
          f"  95%CI[{lo:.1%}-{hi:.1%}]")
    print(f"  単勝回収 {t['roi']:>7.0%} 対 {c['roi']:>7.0%}  "
          f"差{(t['roi']-c['roi'])*100:+5.0f}pt"
          f"  90%区間[{t['lo']:.0%}-{t['hi']:.0%}]")
    print(f"  1頭あたり払戻のばらつき σ={t['sd']:.2f}（回収率の単位）")
    print(f"  この差を主張するのに要る母数:")
    print(f"    勝率で見る   {need_rate:>10,}頭"
          f"{'  ← 足りている' if need_rate and t['n'] >= need_rate else ''}")
    print(f"    回収率で見る {need_roi:>10,}頭"
          f"{'  ← 足りている' if need_roi and t['n'] >= need_roi else ''}")
    if need_rate and need_roi:
        print(f"    → 回収率は勝率の **{need_roi/need_rate:.0f}倍** の母数が要る")
    if months_now and need_roi:
        print(f"  回収率の優位を主張できるまで: "
              f"{project(t['n'], need_roi, months_now)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--target-races", default=None)
    ap.add_argument("--months", default=None)
    args = ap.parse_args()

    by_horse, rides = load(args.dir, args.races, args.months)
    pairs = make_pairs(by_horse, parse_races(args.target_races or args.races))
    cut = tier1_min_rides({"騎手": {j: {"n": n} for j, n in rides.items()}})
    tier1 = {j for j, n in rides.items() if n >= cut}
    months_now = len(complete_months(args.dir, "1-8"))
    print(f"前走ペア {len(pairs):,}組 / 一軍{len(tier1)}人（{cut:,}騎乗以上）"
          f" / 1-8Rが揃った月 {months_now}")
    print("※ 単勝1点100円。対照は「前走二桁着順のその他」")

    dd = [(p, c) for p, c in pairs if p["chaku"] >= 10]
    ctrl_n = [c for p, c in dd
              if not (p["jockey"] not in tier1 and c["jockey"] in tier1)]
    report("前走二桁 × 一軍騎手へ乗り替わり",
           [c for p, c in dd
            if p["jockey"] not in tier1 and c["jockey"] in tier1], ctrl_n,
           months_now)

    FRONT = ("逃げ", "先行")
    furi = [c for p, c in dd
            if p["kyaku"] in FRONT and p["pos4"] is not None and p["pos4"] >= 6]
    ctrl_f = [c for p, c in dd
              if not (p["kyaku"] in FRONT and p["pos4"] is not None
                      and p["pos4"] >= 6)]
    report("前走二桁 × 前に行って沈んだ（不利痕跡・代理B）", furi, ctrl_f,
           months_now)


if __name__ == "__main__":
    main()
