#!/usr/bin/env python3
"""走破タイムを「同開催（その日のその馬場）どれくらい速かったか」で測り直す。

    python3 scripts/kaisai_time.py --races 1-12 --target-races 9-12

記事の主張は「走破タイムは短距離では重要／**同開催でどれくらい速かったかも
重要**」。現行の持ち時計指数は

    指数 = (基準タイム − 自分のタイム) / 基準のばらつき     基準は(場×芝ダ×距離)の全期間
    馬場補正 = 同じ(場×芝ダ×馬場)における指数の平均を引く   馬場は申告値を全期間プール

で作っている。**申告された馬場（良/稍重/重/不良）は4段階しかなく、同じ
「良」でも開催によって時計の出方が違う**（芝の生育・柵の位置・気温）。
そこを直接測るのが「同開催内の相対」である。

    当日補正 = その日・その競馬場・その芝ダで走った全出走の生指数の平均を引く

**これは馬場補正の置き換えであって、追加ではない。** 同じ量（トラックの
速さ）を、申告値の4段階で測るか、その日の実測時計で測るかの違い。

## A/B の形にする
CLAUDE.mdの指標尺度更新と同じやり方で、**同じ行・同じ窓・同じ3分位**に対して
補正だけを入れ替えて並べる。判定は同一人気帯内の複勝リフト＋期間再現。

## 情報漏れ
当日補正はその日の全レースを使うが、**適用先は過去走**（対象レースより前の
日付）なので、対象レース当日の情報は入らない。対象レース自身の日付の補正は
一度も使わない（テストで固定した）。
"""
from __future__ import annotations

import argparse
import collections
import csv
import statistics
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import mochidokei as mk
from keiba import power
from keiba.racefiles import (DEFAULT_RACES, parse_months, race_number,
                             race_venue, result_files)
from scripts.build_mochidokei import load_race_info, stem_date, _expand
from scripts.mochidokei_test import BANDS, MIN_RUNS, WINDOW, band, _f, _i

MIN_DAY_ROWS = 20      # 当日補正を作るのに要求する延べ出走
MIN_DAY_RACES = 3      # 同じ(日×場×芝ダ)のレース数


def load(paths, info, base, months=None):
    runs = []
    for p in paths:
        stem = p.name.replace("_結果.csv", "")
        ri = info.get(stem)
        d, ba, rno = stem_date(p.name), race_venue(p.name), race_number(p.name)
        if not ri or not d or not ba:
            continue
        if months and f"{d.year:04d}-{d.month:02d}" not in months:
            continue
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            name = (r.get("馬名") or "").strip()
            if not name:
                continue
            sec = mk.parse_time(r.get("タイム"))
            runs.append({
                "馬名": name, "日付": d, "R": rno, "stem": stem, "場": ba,
                "馬場種別": ri["馬場種別"], "距離": ri["距離"], "馬場": ri["馬場"],
                # 生指数（補正なし）と、現行の馬場補正ぶみ
                "生指数": base.index(sec, ba, ri["馬場種別"], ri["距離"]),
                "馬場補正指数": base.index(sec, ba, ri["馬場種別"], ri["距離"],
                                     ri["馬場"]),
                "着順": _i(r.get("着順")), "人気": _i(r.get("人気")),
                "馬番": _i(r.get("馬番"))})
    return runs


def day_offsets(runs):
    """(日付, 場, 芝ダ) ごとの生指数の平均。トラックのその日の速さ。"""
    acc = collections.defaultdict(list)
    races = collections.defaultdict(set)
    for r in runs:
        if r["生指数"] is None:
            continue
        k = (r["日付"], r["場"], r["馬場種別"])
        acc[k].append(r["生指数"])
        races[k].add(r["stem"])
    out = {}
    for k, v in acc.items():
        if len(v) >= MIN_DAY_ROWS and len(races[k]) >= MIN_DAY_RACES:
            out[k] = statistics.fmean(v)
    return out


def apply_day(runs, off):
    made = 0
    for r in runs:
        o = off.get((r["日付"], r["場"], r["馬場種別"]))
        if r["生指数"] is not None and o is not None:
            r["当日補正指数"] = r["生指数"] - o
            made += 1
        else:
            r["当日補正指数"] = None
    return made


def build(runs, target_races):
    hist = collections.defaultdict(list)
    for r in runs:
        hist[r["馬名"]].append(r)
    for v in hist.values():
        v.sort(key=lambda r: r["日付"])

    tgt = {int(x) for x in _expand(target_races)}
    out = []
    for r in runs:
        if r["R"] not in tgt or r["着順"] is None or r["人気"] is None:
            continue
        lo = r["日付"] - timedelta(days=WINDOW)
        past = sorted((q for q in hist[r["馬名"]] if lo <= q["日付"] < r["日付"]),
                      key=lambda q: q["日付"], reverse=True)
        a = [q["馬場補正指数"] for q in past if q["馬場補正指数"] is not None]
        b = [q["当日補正指数"] for q in past if q["当日補正指数"] is not None]
        if len(a) < MIN_RUNS or len(b) < MIN_RUNS:
            continue
        out.append({**r, "窓内": len(a),
                    "馬場_近走": mk.summarize(a).recent,
                    "当日_近走": mk.summarize(b).recent})

    by_race = collections.defaultdict(list)
    for r in out:
        by_race[r["stem"]].append(r)
    for rows in by_race.values():
        for src, dst in (("馬場_近走", "馬場_平均差"), ("当日_近走", "当日_平均差")):
            vals = {r["馬番"]: r[src] for r in rows if r["馬番"] is not None}
            dl = mk.member_deltas(vals)
            for r in rows:
                r[dst] = dl.get(r["馬番"], (None, None))[1]
    return out


def tercile(rows, key, title):
    print(f"\n■ {title}（{key}）")
    print(f"{'人気帯':<14}{'位置':<6}{'n':>6}{'勝率':>8}{'複勝率':>8}"
          f"{'勝リフト':>9}{'複リフト':>9}  判定(複勝)")
    for b in BANDS:
        sub = [r for r in rows if band(r["人気"]) == b and r.get(key) is not None]
        if len(sub) < 60:
            print(f"{b:<14}母数不足 n={len(sub)}")
            continue
        vals = sorted(r[key] for r in sub)
        q1, q2 = vals[len(vals) // 3], vals[2 * len(vals) // 3]
        g = {"上位": [], "中位": [], "下位": []}
        for r in sub:
            v = r[key]
            g["上位" if v >= q2 else ("中位" if v >= q1 else "下位")].append(r)
        bw = sum(1 for r in sub if r["着順"] == 1)
        bp = sum(1 for r in sub if r["着順"] <= 3)
        n0 = len(sub)
        print(f"{b:<14}{'帯全体':<6}{n0:>6}{bw/n0:>8.1%}{bp/n0:>8.1%}{'—':>9}{'—':>9}")
        for name in ("上位", "中位", "下位"):
            gr = g[name]
            if not gr:
                continue
            w = sum(1 for r in gr if r["着順"] == 1)
            pl = sum(1 for r in gr if r["着順"] <= 3)
            n = len(gr)
            v = power.judge(name, pl, n, bp, n0)
            print(f"{'':<14}{name:<6}{n:>6}{w/n:>8.1%}{pl/n:>8.1%}"
                  f"{(w/n-bw/n0)*100:>+8.1f}p{(pl/n-bp/n0)*100:>+8.1f}p  {v.code}")


def ab(rows, bands=("1-3番人気", "4-5番人気", "6-9番人気")):
    """同じ行の上で補正だけ入れ替え、期間でも割る。"""
    print("\n" + "=" * 78)
    print("■ A/B: 馬場補正（申告値・全期間プール） 対 当日補正（その日の実測時計）")
    print("=" * 78)
    for b in bands:
        sub = [r for r in rows if band(r["人気"]) == b]
        if len(sub) < 120:
            print(f"  {b} 母数不足 n={len(sub)}")
            continue
        bp = sum(1 for r in sub if r["着順"] <= 3) / len(sub)
        print(f"\n  {b}  n={len(sub):,}  帯の複勝率{bp:.1%}")
        for key, label in (("馬場_平均差", "現行: 馬場補正 → メンバー平均差"),
                           ("当日_平均差", "新: 当日補正 → メンバー平均差")):
            ok = [r for r in sub if r.get(key) is not None]
            if len(ok) < 120:
                print(f"    {label:<34} 母数不足 n={len(ok)}")
                continue
            vals = sorted(r[key] for r in ok)
            q2 = vals[2 * len(vals) // 3]
            q1 = vals[len(vals) // 3]
            hi = [r for r in ok if r[key] >= q2]
            lo = [r for r in ok if r[key] < q1]
            parts = []
            for nm, gr in (("上位", hi), ("下位", lo)):
                h = sum(1 for r in gr if r["着順"] <= 3)
                v = power.judge(nm, h, len(gr), int(bp * len(ok)), len(ok))
                parts.append(f"{nm} {h/len(gr):5.1%} ({(h/len(gr)-bp)*100:+5.1f}p"
                             f"・要る差{v.mdd*100:4.1f}p・{v.code})")
            print(f"    {label:<34} " + " / ".join(parts))
            per = []
            for y in (2025, 2026):
                yy = [r for r in ok if r["日付"].year == y]
                if len(yy) < 100:
                    per.append(f"{y}: n={len(yy)} 母数不足")
                    continue
                ybp = sum(1 for r in yy if r["着順"] <= 3) / len(yy)
                yv = sorted(r[key] for r in yy)
                yq = yv[2 * len(yv) // 3]
                yh = [r for r in yy if r[key] >= yq]
                hh = sum(1 for r in yh if r["着順"] <= 3) / len(yh)
                per.append(f"{y}: 上位{hh:5.1%} ({(hh-ybp)*100:+5.1f}p, n={len(yh):>4})")
            print(f"    {'':<34} " + " / ".join(per))


def disagree(rows, band_name="1-3番人気"):
    """**2つの補正が答えを変えた出走だけ**で比べる。

    全体で差が出ないのは「補正が効いていない」のか「補正が同じ答えを出す」
    のか区別がつかない。答えが変わった行に絞れば、どちらが正しいかを直接
    測れる（CLAUDE.md「◎が入れ替わったのは178レース中33レース」と同じ読み）。
    """
    print("\n" + "=" * 78)
    print(f"■ 2つの補正が答えを変えた出走だけで比べる（{band_name}）")
    print("=" * 78)
    sub = [r for r in rows
           if band(r["人気"]) == band_name
           and r.get("馬場_平均差") is not None and r.get("当日_平均差") is not None]
    if len(sub) < 200:
        print(f"  母数不足 n={len(sub)}")
        return
    # 帯の中で3分位を切り、上位に入るかどうかが食い違った行を拾う
    top = {}
    for key in ("馬場_平均差", "当日_平均差"):
        vals = sorted(r[key] for r in sub)
        q2 = vals[2 * len(vals) // 3]
        top[key] = {id(r) for r in sub if r[key] >= q2}
    flip = [r for r in sub
            if (id(r) in top["馬場_平均差"]) != (id(r) in top["当日_平均差"])]
    bp = sum(1 for r in sub if r["着順"] <= 3) / len(sub)
    print(f"  対象 n={len(sub):,}  帯の複勝率{bp:.1%}")
    print(f"  上位3分位の判定が食い違った出走 {len(flip):,} "
          f"({len(flip)/len(sub):.1%})")
    if len(flip) < 60:
        print("  → 食い違いが母数不足。2つの補正はほぼ同じ答えを出している")
        return
    for key, other in (("馬場_平均差", "当日_平均差"), ("当日_平均差", "馬場_平均差")):
        only = [r for r in flip if id(r) in top[key]]
        if len(only) < 30:
            print(f"    {key} だけが上位に置いた n={len(only)} 母数不足")
            continue
        h = sum(1 for r in only if r["着順"] <= 3)
        v = power.judge(key, h, len(only), int(bp * len(sub)), len(sub))
        print(f"    {key} だけが上位に置いた  n={len(only):>4}  {h/len(only):5.1%}"
              f"  {(h/len(only)-bp)*100:+5.1f}p  要る差{v.mdd*100:4.1f}p  {v.code}")
    print("  ※ 両方が同じ側に置いた行は差が出ようがないので、優劣はこの食い違い"
          "だけで決まる")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="1-12")
    ap.add_argument("--target-races", default=DEFAULT_RACES)
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--base", default="data/profiles/jra/base_times.json")
    ap.add_argument("--months", default=None)
    a = ap.parse_args()

    base = mk.BaseTimes.load(a.base)
    info = load_race_info(Path(a.race_info))
    months = parse_months(a.months) if a.months else None
    runs = load(result_files(a.dir, a.races), info, base, months)
    off = day_offsets(runs)
    made = apply_day(runs, off)
    print(f"出走 {len(runs):,} / 当日補正が作れた {made:,} ({made/max(1,len(runs)):.1%})"
          f" / (日×場×芝ダ)区分 {len(off):,}")
    sp = sorted(off.values())
    print(f"  当日補正の広がり: 中央値{sp[len(sp)//2]:+.2f}σ "
          f"10%点{sp[len(sp)//10]:+.2f}σ 90%点{sp[9*len(sp)//10]:+.2f}σ")

    rows = build(runs, a.target_races)
    print(f"対象の出走（両方の指標が作れたもの） {len(rows):,}")

    tercile(rows, "馬場_平均差", "現行（馬場補正）")
    tercile(rows, "当日_平均差", "新（当日補正＝同開催内の相対）")
    ab(rows)
    disagree(rows)
    disagree(rows, "6-9番人気")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
