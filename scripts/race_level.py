#!/usr/bin/env python3
"""レース水準を走破タイムから測り、持ち時計を「水準」と「レース内相対」に分ける。

## なぜこれを測るのか

CLAUDE.mdは2つの宿題を並べて残していた。

1. **前走内容のレース格割引**（`ZENSO_TABLE` は前走着順だけで前走内容を
   決めるので、格上のレースでの大敗が最下位級に評価される）。
   これは「等級データが5,876行中85行しか無い」ため見送られていた
2. **持ち時計指数は絶対値のまま帯に切ってはいけない**（レース水準＝クラスが
   混ざるため。1-3番人気の複勝リフトが2025年 −0.5p → 2026年 +3.4p と
   符号ごと変わった）。だからメンバー相対でしか使えていない

この2つは**同じ穴の裏と表**である。`keiba/mochidokei.py` の留保3が
「距離だけで正規化するので、指数はクラスを部分的に含む」と書いているとおり、
**時計の絶対水準にはクラスの情報が入っている**。ならば等級ラベルを取り直さ
ずに、時計からレース水準を測れる。そして測れれば持ち時計を

    馬の絶対指数 = 走ったレースの水準 ＋ そのレース内での相対（着差）

に**厳密に分解できる**（水準＝出走馬の指数の中央値と定義すれば恒等式）。
絶対値が期間再現しなかったのはこの2成分のどちらが原因なのかを分けて測る。

## 水準の検算は取得経路の違う3つで閉じる

CLAUDE.mdの規則（「検算は取得経路の違う3つ目で閉じる」）に従い、
時計から作った水準を**時計と無関係な3つ**と突き合わせる。

  1. レース名のクラス表記（新馬/未勝利/1勝クラス/2勝クラス）— 文字列なので100%確実
  2. `race_info.csv` の等級列（OP/L/G3/G2/G1）— 結果ページのアイコン由来
  3. メンバー質（出走馬の過去勝率の平均）— 着順由来。時計を一切使わない

    python3 scripts/race_level.py --races 1-12 --target-races 9-12
"""
from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import mochidokei as mk
from keiba import profile
from keiba.power import HEADER, judge
from keiba.racefiles import DEFAULT_RACES, parse_races
from keiba.racelevel import CLASS_ORDER, GRADE_ORDER, build_levels


WINDOW_DAYS = mk.WINDOW_DAYS
RECENT_RUNS = mk.RECENT_RUNS
MIN_RUNS = mk.MIN_RUNS_FOR_SCORE


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="1-12",
                    help="水準・戦績を作る帯（既定1-12）")
    ap.add_argument("--target-races", default=DEFAULT_RACES,
                    help="「今走」として評価する帯（既定9-12）")
    ap.add_argument("--months", default=None)
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--base-times", default="data/profiles/jra/base_times.json")
    return ap.parse_args()


def to_ord(s: str) -> int:
    y, m, d = (int(x) for x in s.split("-"))
    return date(y, m, d).toordinal()


# ---------------------------------------------------------------------------
# 1. レース水準を作る
# ---------------------------------------------------------------------------

def build(args) -> tuple[dict, dict]:
    """水準の計算は `keiba.racelevel.build_levels` に置いてある
    （`scripts/build_race_level.py` と同じ計算を2か所に書かないため）。"""
    races, runs = build_levels(args.dir, args.races, args.months,
                              args.race_info, args.base_times)
    print(f"{args.dir} {args.races}R: レース {len(races):,} / "
          f"延べ出走 {sum(len(v) for v in runs.values()):,} / 頭数 {len(runs):,}\n")
    return races, runs


# ---------------------------------------------------------------------------
# 2. 検算（取得経路の違う3つと突き合わせる）
# ---------------------------------------------------------------------------

def verify(races: dict, runs: dict) -> None:
    print("== 検算1: レース名のクラス表記（文字列なので100%確実）==")
    print(f"  {'クラス':<8}{'n':>7}{'水準(中央値)':>14}{'勝ち馬指数':>12}{'sd':>7}")
    meds = []
    for c in CLASS_ORDER:
        vs = [r["水準"] for r in races.values() if r["クラス"] == c]
        ws = [r["勝ち馬指数"] for r in races.values() if r["クラス"] == c]
        if not vs:
            continue
        meds.append((c, statistics.median(vs)))
        print(f"  {c:<8}{len(vs):>7,}{statistics.median(vs):>+14.3f}"
              f"{statistics.median(ws):>+12.3f}{statistics.pstdev(vs):>7.3f}")
    ok = all(a[1] < b[1] for a, b in zip(meds, meds[1:]))
    print(f"  → クラスの順序と{'一致（単調）' if ok else '一致しない'}\n")

    print("== 検算2: race_info.csv の等級列（結果ページのアイコン由来）==")
    print(f"  {'等級':<8}{'n':>7}{'水準(中央値)':>14}{'勝ち馬指数':>12}")
    gm = []
    for g in GRADE_ORDER:
        vs = [r["水準"] for r in races.values() if r["等級"] == g]
        ws = [r["勝ち馬指数"] for r in races.values() if r["等級"] == g]
        if not vs:
            continue
        gm.append((g, statistics.median(vs)))
        print(f"  {g:<8}{len(vs):>7,}{statistics.median(vs):>+14.3f}"
              f"{statistics.median(ws):>+12.3f}")
    ok = all(a[1] < b[1] for a, b in zip(gm, gm[1:]))
    print(f"  → 等級の順序と{'一致（単調）' if ok else '一致しない'}"
          f"{'' if ok else '。オープン以上は時計で格を測れない'}\n")

    print("== 検算3: メンバー質（出走馬の過去勝率の平均・時計を使わない）==")
    # 各馬の「そのレースより前の勝率」を累積で作る（後知恵なし）
    prior: dict[tuple[str, str], float] = {}
    for nm, lst in runs.items():
        w = 0
        for i, r in enumerate(lst):
            if i >= 2:                      # 1走だと0%か100%しか取らない
                prior[(nm, r["stem"])] = w / i
            w += 1 if r["着順"] == 1 else 0
    qual: dict[str, float] = {}
    by_stem: dict[str, list[str]] = defaultdict(list)
    for nm, lst in runs.items():
        for r in lst:
            by_stem[r["stem"]].append(nm)
    for stem, names in by_stem.items():
        vs = [prior[(n, stem)] for n in names if (n, stem) in prior]
        if len(vs) >= 3:
            qual[stem] = statistics.fmean(vs)
    pairs = [(races[s]["水準"], q) for s, q in qual.items() if s in races]
    if len(pairs) > 2:
        r = statistics.correlation([a for a, _ in pairs], [b for _, b in pairs])
        print(f"  n={len(pairs):,}  相関 r={r:+.3f}")
        qs = sorted(pairs, key=lambda x: x[1])
        k = len(qs) // 4
        for lab, part in (("メンバー質 下位1/4", qs[:k]),
                          ("中位", qs[k:3 * k]), ("メンバー質 上位1/4", qs[3 * k:])):
            print(f"  {lab:<20}n={len(part):>6,} "
                  f"水準の中央値 {statistics.median([a for a, _ in part]):+.3f}")
    print()


# ---------------------------------------------------------------------------
# 3. 前走水準 × 前走着順（前走内容のレース格割引）
# ---------------------------------------------------------------------------

def band(nk: int | None) -> str | None:
    if nk is None:
        return None
    if nk <= 3:
        return "1-3番人気"
    if nk <= 5:
        return "4-5番人気"
    if nk <= 9:
        return "6-9番人気"
    return "10番人気以下"


BANDS = ["1-3番人気", "4-5番人気", "6-9番人気", "10番人気以下"]
CHAKU_BANDS = (("前走1-2着", lambda c: c <= 2), ("前走3-5着", lambda c: 3 <= c <= 5),
               ("前走6-9着", lambda c: 6 <= c <= 9), ("前走二桁", lambda c: c >= 10))
PERIODS = ("2024", "2025", "2026")


def reproduced(test: list[dict], ctrl: list[dict], key) -> str:
    """期間ごとに符号が揃うか。各期間で的中10本を要求する（review_hypotheses と同じ）。"""
    signs = []
    for per in PERIODS:
        t = [r for r in test if r["日付"].startswith(per)]
        c = [r for r in ctrl if r["日付"].startswith(per)]
        if not t or not c or sum(key(r) for r in t) < 10:
            continue
        signs.append(1 if (sum(key(r) for r in t) / len(t)
                           >= sum(key(r) for r in c) / len(c)) else -1)
    if len(signs) < 2:
        return "期間不足"
    return "再現" if len(set(signs)) == 1 else "反転"


def make_pairs(runs: dict, target) -> list[tuple[dict, dict]]:
    out = []
    for lst in runs.values():
        for i in range(1, len(lst)):
            cur = lst[i]
            if cur["interval"] is None:
                continue
            if target is not None and cur["R"] not in target:
                continue
            t = to_ord(cur["日付"]) - cur["interval"]
            for cand in lst[:i][::-1]:
                if abs(to_ord(cand["日付"]) - t) <= 2:
                    out.append((cand, cur))
                    break
    return out


def tertiles(vals: list[float]) -> tuple[float, float]:
    s = sorted(vals)
    return s[len(s) // 3], s[2 * len(s) // 3]


def zenso_level(pairs: list[tuple[dict, dict]]) -> None:
    print(f"== 前走の水準 × 前走着順（{len(pairs):,}組）==")
    print("前走の水準は**発走前に分かる**（前走の結果だから）。"
          "同一人気帯の中で測る\n")

    lo, hi = tertiles([p["水準"] for p, _ in pairs])
    print(f"前走水準の3分位の境目: {lo:+.3f} / {hi:+.3f}\n")

    # まず母数を数える（CLAUDE.mdの手順: 測る前に帯ごとの母数を数える）
    print("-- 帯ごとの母数（測る前に数える）--")
    print(f"  {'':<14}{'前走1-2着':>12}{'前走3-5着':>12}{'前走6-9着':>12}{'前走二桁':>12}")
    for b in BANDS:
        cells = []
        for _, f in CHAKU_BANDS:
            n = sum(1 for p, c in pairs
                    if band(c["人気"]) == b and c["着順"] is not None
                    and p["着順"] is not None and f(p["着順"]) and p["水準"] >= hi)
            cells.append(n)
        print(f"  {b:<14}" + "".join(f"{n:>12,}" for n in cells))
    print("  （水準が上位1/3の組だけを数えた。検証群になる側）\n")

    for metric, mlab, key in (("複勝率", "複勝率", lambda r: 1 if r["着順"] <= 3 else 0),
                              ("勝率", "勝率", lambda r: 1 if r["着順"] == 1 else 0)):
        print(f"-- {mlab}: 同じ前走着順の中で、前走が高水準だった馬 --")
        print("  " + HEADER)
        for b in BANDS:
            for clab, f in CHAKU_BANDS:
                sel = [(p, c) for p, c in pairs
                       if band(c["人気"]) == b and c["着順"] is not None
                       and p["着順"] is not None and f(p["着順"])]
                if len(sel) < 60:
                    continue
                test = [c for p, c in sel if p["水準"] >= hi]
                ctrl = [c for p, c in sel if p["水準"] < lo]
                if len(test) < 30 or len(ctrl) < 30:
                    continue
                v = judge(f"{b} {clab}×高水準", sum(key(r) for r in test), len(test),
                          sum(key(r) for r in ctrl), len(ctrl))
                rep = reproduced(test, ctrl, key)
                print(f"  {v.line()}[{rep}]")
        print()


# ---------------------------------------------------------------------------
# 4. 持ち時計の分解（水準 ＋ レース内相対）
# ---------------------------------------------------------------------------

def decompose(runs: dict, races: dict, target) -> None:
    """馬の持ち時計を3つの量にし、メンバー相対にして同一人気帯内で測る。

        絶対 = 水準 + 相対      （恒等式。水準をレース内中央値と定義したため）

    production は「絶対をメンバー内で正規化した値」を使っている。
    どの成分が情報を持っているかを分けて測る。
    """
    print("== 持ち時計の分解（絶対 = 走ったレースの水準 ＋ レース内相対）==")
    print(f"窓{WINDOW_DAYS}日・近{RECENT_RUNS}走平均・{MIN_RUNS}走未満は作らない"
          "（keiba/mochidokei.py と同じ条件）\n")

    # レースごとに出走馬をまとめ、各馬の窓内平均を3つ作る
    field: dict[str, list[dict]] = defaultdict(list)
    for lst in runs.values():
        for r in lst:
            field[r["stem"]].append(r)

    rows = []
    for stem, members in field.items():
        ri = races.get(stem)
        if not ri or (target is not None and ri["R"] not in target):
            continue
        cur = to_ord(ri["日付"])
        vals: dict[str, tuple[float, float, float]] = {}
        for m in members:
            past = [r for r in runs[m["馬名"]]
                    if 0 < cur - to_ord(r["日付"]) <= WINDOW_DAYS]
            past.sort(key=lambda r: r["日付"], reverse=True)
            if len(past) < MIN_RUNS:
                continue
            w = past[:RECENT_RUNS]
            vals[m["馬名"]] = (statistics.fmean(r["指数"] for r in w),
                              statistics.fmean(r["水準"] for r in w),
                              statistics.fmean(r["相対"] for r in w))
        if len(vals) < 4:
            continue
        avg = [statistics.fmean(v[i] for v in vals.values()) for i in range(3)]
        for m in members:
            v = vals.get(m["馬名"])
            if v is None or m["人気"] is None or m["着順"] is None:
                continue
            rows.append({"日付": ri["日付"], "人気": m["人気"], "着順": m["着順"],
                         "絶対": v[0], "水準": v[1], "相対": v[2],
                         "絶対差": v[0] - avg[0], "水準差": v[1] - avg[1],
                         "相対差": v[2] - avg[2]})

    print(f"測れた出走 {len(rows):,}\n")
    for kind, keys in (("絶対値のまま（CLAUDE.mdが「帯に切ってはいけない」と書いた形）",
                        ("絶対", "水準", "相対")),
                       ("メンバー平均との差（実測で再現した形）",
                        ("絶対差", "水準差", "相対差"))):
        print(f"-- {kind} --")
        print("  " + HEADER)
        for k in keys:
            lo, hi = tertiles([r[k] for r in rows])
            for b in BANDS:
                sel = [r for r in rows if band(r["人気"]) == b]
                test = [r for r in sel if r[k] >= hi]
                ctrl = [r for r in sel if r[k] < lo]
                if len(test) < 60 or len(ctrl) < 60:
                    continue
                key = lambda r: 1 if r["着順"] <= 3 else 0
                v = judge(f"{b} {k}が上位1/3", sum(key(r) for r in test), len(test),
                          sum(key(r) for r in ctrl), len(ctrl))
                rep = reproduced(test, ctrl, key)
                print(f"  {v.line()}[{rep}]")
            print()
    return rows


def cross(rows: list[dict]) -> None:
    """水準差 × 相対差 の2×2。2つの成分が帯ごとに役割を分けるかを直接見る。

    帯ごとに別々のセルで「差あり」が出ただけでは、24区分を同時に見た中の
    2つという読みもできる。**同じ帯の中で向きが逆になる**ことを1つの表で
    確かめる（対照群が動かないことを確かめた `nokori.py` の②と同じ形）。
    """
    print("== 交差: 水準差 × 相対差（同じ帯の中で向きが逆か）==")
    print("  水準差＝どの水準のレースで走ってきたか（メンバー平均との差）")
    print("  相対差＝そのレースで相手をどれだけ離したか（同）\n")
    slo, shi = tertiles([r["水準差"] for r in rows])
    rlo, rhi = tertiles([r["相対差"] for r in rows])
    key = lambda r: 1 if r["着順"] <= 3 else 0
    print("  " + HEADER)
    for b in BANDS:
        sel = [r for r in rows if band(r["人気"]) == b]
        if not sel:
            continue
        base = [r for r in sel if slo <= r["水準差"] < shi and rlo <= r["相対差"] < rhi]
        for lab, f in (("水準↑×相対↓", lambda r: r["水準差"] >= shi and r["相対差"] < rlo),
                       ("水準↓×相対↑", lambda r: r["水準差"] < slo and r["相対差"] >= rhi),
                       ("両方↑", lambda r: r["水準差"] >= shi and r["相対差"] >= rhi),
                       ("両方↓", lambda r: r["水準差"] < slo and r["相対差"] < rlo)):
            t = [r for r in sel if f(r)]
            if len(t) < 40 or len(base) < 40:
                continue
            v = judge(f"{b} {lab}", sum(key(r) for r in t), len(t),
                      sum(key(r) for r in base), len(base))
            print(f"  {v.line()}[{reproduced(t, base, key)}]")
        print(f"  {'（対照＝どちらも中位）':<32}{len(base):>6,}"
              f"{sum(key(r) for r in base) / len(base):>7.1%}\n")


def main() -> None:
    args = parse_args()
    profile.assert_same_profile(args.dir, args.race_info)
    races, runs = build(args)
    verify(races, runs)
    target = parse_races(args.target_races)
    pairs = make_pairs(runs, target)
    zenso_level(pairs)
    rows = decompose(runs, races, target)
    cross(rows)

if __name__ == "__main__":
    main()
