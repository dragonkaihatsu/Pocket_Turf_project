#!/usr/bin/env python3
"""持ち時計指数が、同一人気帯の中で着順を判別できるかを測る。

    python3 scripts/mochidokei_test.py --races 1-12 --target-races 9-12

## 何と比べるか

**対照は「素の上がり3F偏差値」**。CLAUDE.mdが横断偏差値で失敗した1度目が
これで、全体の勝率は8.7%→5.3%と単調なのに、同じ人気帯で切ると判別力が
消えて逆転した（4-5番人気帯で偏差値55以上7.8% < 45未満12.6%、14,759出走）。

まったく同じ行・同じ窓・同じ分位の切り方で、上がり3Fと時計指数を並べる。
**上がり3Fが逆転する帯で時計指数が逆転しなければ、尺度を直した効果**と言える。
逆転すれば「時計も織り込み済み」の3度目の確認になる。

## 情報漏れを出さない

各出走の指標は**その日より前・365日以内の走り**だけから作る。レース当日の
タイムは絶対に使わない。基準タイム表は全期間から作るので、そこは in-sample
（トラックの物理定数に近い量だが、独立性が要るなら `--train-months` で
期間を切って作り直せる）。
"""
from __future__ import annotations

import argparse
import collections
import csv
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.models import parse_agari_3f
from keiba import mochidokei as mk
from keiba import power
from keiba.racefiles import (DEFAULT_RACES, race_number, race_venue,
                             result_files)
from scripts.build_mochidokei import load_race_info, stem_date, _expand

MIN_RUNS = 3          # 指標を作るのに要求する窓内の走り
WINDOW = 365


def band(ninki: int | None) -> str | None:
    if ninki is None:
        return None
    if ninki <= 3:
        return "1-3番人気"
    if ninki <= 5:
        return "4-5番人気"
    if ninki <= 9:
        return "6-9番人気"
    return "10番人気以下"


BANDS = ["1-3番人気", "4-5番人気", "6-9番人気", "10番人気以下"]


def load(paths, info, base) -> tuple[list[dict], dict]:
    """出走を読み、レース内で上がり3Fを偏差値化しつつ時計指数も付ける。"""
    runs = []
    for p in paths:
        stem = p.name.replace("_結果.csv", "")
        ri = info.get(stem)
        d, ba, rno = stem_date(p.name), race_venue(p.name), race_number(p.name)
        if not ri or not d or not ba:
            continue
        rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
        agaris = [a for r in rows
                  if (a := parse_agari_3f(r.get("上がり3F"))) is not None]
        # 上がり3Fは小さいほど速い→符号を反転して偏差値化する
        devs = mk_deviations([-a for a in agaris])
        it = iter(devs)
        for r in rows:
            name = (r.get("馬名") or "").strip()
            if not name:
                continue
            a = parse_agari_3f(r.get("上がり3F"))
            ad = next(it) if a is not None else None
            idx = base.index(mk.parse_time(r.get("タイム")), ba,
                             ri["馬場種別"], ri["距離"], ri["馬場"])
            runs.append({"馬名": name, "日付": d, "R": rno, "stem": stem,
                         "指数": idx, "上がり偏差": ad,
                         "着順": _i(r.get("着順")), "人気": _i(r.get("人気")),
                         "馬番": _i(r.get("馬番"))})
    return runs, info


def mk_deviations(values):
    from keiba.hensachi import deviations
    return deviations(values)


def _f(s):
    try:
        return float((s or "").strip())
    except ValueError:
        return None


def _i(s):
    s = (s or "").strip()
    return int(s) if s.isdigit() else None


def build_metrics(runs, target_races: str) -> list[dict]:
    """対象レースの各出走に、窓内の走りから作った指標を付ける。"""
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
        past = [q for q in hist[r["馬名"]] if lo <= q["日付"] < r["日付"]]
        past.sort(key=lambda q: q["日付"], reverse=True)   # 新しい順
        idxs = [q["指数"] for q in past if q["指数"] is not None]
        ags = [q["上がり偏差"] for q in past if q["上がり偏差"] is not None]
        if len(idxs) < MIN_RUNS or len(ags) < MIN_RUNS:
            continue
        m = mk.summarize(idxs)
        out.append({**r,
                    "窓内": len(idxs),
                    "時計_近走": m.recent, "時計_最高": m.best,
                    "上がり偏差_平均": statistics.fmean(ags[:mk.RECENT_RUNS])})
    # メンバー内の相対差（重要度上位2つの形）
    by_race = collections.defaultdict(list)
    for r in out:
        by_race[r["stem"]].append(r)
    for rows in by_race.values():
        vals = {r["馬番"]: r["時計_近走"] for r in rows if r["馬番"] is not None}
        dl = mk.member_deltas(vals)
        for r in rows:
            t, a = dl.get(r["馬番"], (None, None))
            r["トップ差"], r["平均差"] = t, a
        r0 = rows[0]
        r0["_メンバー数"] = len(rows)
    return out


def tercile_report(rows: list[dict], key: str, title: str) -> None:
    print(f"\n■ {title}（{key}・窓内{MIN_RUNS}走以上）")
    print(f"{'人気帯':<14}{'位置':<6}{'n':>6}{'勝率':>8}{'複勝率':>8}"
          f"{'勝リフト':>9}{'複リフト':>9}  判定(複勝)")
    for b in BANDS:
        sub = [r for r in rows if band(r["人気"]) == b and r.get(key) is not None]
        if len(sub) < 60:
            print(f"{b:<14}母数不足 n={len(sub)}")
            continue
        vals = sorted(r[key] for r in sub)
        q1, q2 = vals[len(vals) // 3], vals[2 * len(vals) // 3]
        groups = {"下位": [], "中位": [], "上位": []}
        for r in sub:
            v = r[key]
            groups["上位" if v >= q2 else ("中位" if v >= q1 else "下位")].append(r)
        bw = sum(1 for r in sub if r["着順"] == 1)
        bp = sum(1 for r in sub if r["着順"] <= 3)
        n0 = len(sub)
        print(f"{b:<14}{'帯全体':<6}{n0:>6}{bw/n0:>8.1%}{bp/n0:>8.1%}"
              f"{'—':>9}{'—':>9}")
        for g in ("上位", "中位", "下位"):
            gr = groups[g]
            if not gr:
                continue
            w = sum(1 for r in gr if r["着順"] == 1)
            pl = sum(1 for r in gr if r["着順"] <= 3)
            n = len(gr)
            v = power.judge(g, pl, n, bp, n0)
            print(f"{'':<14}{g:<6}{n:>6}{w/n:>8.1%}{pl/n:>8.1%}"
                  f"{(w/n-bw/n0)*100:>+8.1f}p{(pl/n-bp/n0)*100:>+8.1f}p  {v.code}")


def headline(rows: list[dict]) -> None:
    """4-5番人気帯で、上がり3Fの逆転が時計指数で消えるか。"""
    print("\n" + "=" * 74)
    print("■ 本命の比較: 4-5番人気帯（上がり3F偏差値が逆転した帯）")
    print("=" * 74)
    sub = [r for r in rows if band(r["人気"]) == "4-5番人気"]
    if len(sub) < 60:
        print(f"  母数不足 n={len(sub)}")
        return
    for key, label in [("上がり偏差_平均", "対照: 上がり3F偏差値"),
                       ("時計_近走", "時計指数（近走平均）"),
                       ("時計_最高", "時計指数（近3走最高）"),
                       ("平均差", "時計指数 メンバー平均との差"),
                       ("トップ差", "時計指数 メンバートップとの差")]:
        ok = [r for r in sub if r.get(key) is not None]
        if len(ok) < 60:
            print(f"  {label:<30} 母数不足 n={len(ok)}")
            continue
        vals = sorted(r[key] for r in ok)
        q1, q2 = vals[len(vals) // 3], vals[2 * len(vals) // 3]
        hi = [r for r in ok if r[key] >= q2]
        lo = [r for r in ok if r[key] < q1]
        hw, lw = _rate(hi, 1), _rate(lo, 1)
        hp, lp = _rate(hi, 3), _rate(lo, 3)
        mark = "逆転" if hw < lw else "順方向"
        print(f"  {label:<30} n={len(ok):>5}  "
              f"上位 勝{hw:>5.1%}/複{hp:>5.1%}  下位 勝{lw:>5.1%}/複{lp:>5.1%}  "
              f"→ 勝率は{mark}")


def _rate(rows, within):
    return sum(1 for r in rows if r["着順"] <= within) / len(rows) if rows else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="1-12")
    ap.add_argument("--target-races", default=DEFAULT_RACES)
    ap.add_argument("--months", default=None)
    ap.add_argument("--year", type=int, default=None, help="対象をこの年に限る")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--base", default="data/profiles/jra/base_times.json")
    a = ap.parse_args()

    base = mk.BaseTimes.load(a.base)
    info = load_race_info(Path(a.race_info))
    paths = result_files(a.dir, races=a.races, months=a.months)
    print(f"結果CSV {len(paths):,}本 / 基準 距離{len(base.cells)}区分・馬場{len(base.baba)}区分")

    runs, _ = load(paths, info, base)
    print(f"延べ出走 {len(runs):,}")

    rows = build_metrics(runs, a.target_races)
    if a.year:
        rows = [r for r in rows if r["日付"].year == a.year]
        print(f"対象を{a.year}年に限定")
    print(f"指標が作れた対象出走 {len(rows):,}"
          f"（{a.target_races}R・窓内{MIN_RUNS}走以上）")
    if not rows:
        return 1
    print(f"  窓内の走り 中央値 {statistics.median(r['窓内'] for r in rows):.0f}走")

    headline(rows)
    for key, title in [("上がり偏差_平均", "対照: 素の上がり3F偏差値"),
                       ("時計_近走", "時計指数（近走平均・絶対値）"),
                       ("平均差", "時計指数 メンバー平均との差"),
                       ("トップ差", "時計指数 メンバートップとの差")]:
        tercile_report(rows, key, title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
