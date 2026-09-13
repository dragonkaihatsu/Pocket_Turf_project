#!/usr/bin/env python3
"""レース内偏差値がレースの読みやすさを予測するかを検証する。

`keiba/hensachi.py` は1位の偏差値で「抜けている／やや優位／混戦」と言い換えて
表示しているが、**その言い換えが当たるかは一度も測っていない**。CLAUDE.mdは
さらに「レース内偏差値の混戦表示がそのまま見送り判定に使える」と書いており、
これも未検証のまま運用に載りかけている。

測ること:
  1. 帯（抜けている/やや優位/混戦）ごとに ◎ の勝率・複勝率が違うか
  2. 箱買いの的中率・回収率が帯で違うか（＝見送り判定に使えるか）
  3. **1番人気オッズで統制しても残るか**。「抜けている」レースは単に
     人気馬が強いレースかもしれない。それなら偏差値は市場の言い換えであって
     新しい情報ではない（CLAUDE.md「載っているものは織り込み済み」）

判定は keiba/power.py に合わせる。母数が足りない区分は「判定不能」と出し、
数字を作らない。
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest import load_race, load_race_info, race_date, race_venue, settle
from keiba.hensachi import CLEAR, SLIGHT, by_umaban
from keiba.marks import assign_marks
from keiba.power import HEADER, ROI_HEADER, judge, judge_roi
from keiba.racefiles import DEFAULT_RACES, parse_months, result_files
from keiba.scoring import score_race

STAKE = 100
BANDS = ["抜けている", "やや優位", "混戦"]


def band_of(top: float) -> str:
    if top >= CLEAR:
        return "抜けている"
    if top >= SLIGHT:
        return "やや優位"
    return "混戦"


def odds_band(o: float | None) -> str:
    if o is None:
        return "不明"
    if o < 2.0:
        return "1倍台"
    if o < 3.0:
        return "2倍台"
    return "3倍以上"


def first_place(path: Path) -> int | None:
    """結果CSVから1着の馬番。同着があれば最初の1頭を返す。"""
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if (r.get("着順") or "").strip() == "1" and (r.get("馬番") or "").isdigit():
                return int(r["馬番"])
    return None


def boxes(order: list[int]) -> dict[str, tuple[str, list[frozenset]]]:
    """検証する箱。CLAUDE.mdが実際に出している幅に合わせる。"""
    return {
        "ワイド 上位3頭BOX": ("ワイド", [frozenset(c) for c in combinations(order[:3], 2)]),
        "ワイド 上位6頭BOX": ("ワイド", [frozenset(c) for c in combinations(order[:6], 2)]),
        "馬連 上位4頭BOX": ("馬連", [frozenset(c) for c in combinations(order[:4], 2)]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--months", help="期間で絞る (例 2025-01..2026-05)")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--records", default="data/profiles/jra/horse_records_corpus.csv")
    args = ap.parse_args()

    directory = Path(args.dir)
    months = parse_months(args.months) if args.months else None
    stems = [Path(f).name.replace("_結果.csv", "")
             for f in result_files(directory, args.races, months)]

    import keiba.scoring as sc
    sc.load_ratings = lambda *a, **k: {}       # 後知恵を排除（backtest.py と同じ）

    from keiba.horsedb import load_records
    kyori_by_stem = load_race_info(args.race_info)
    records = load_records(args.records) if Path(args.records).exists() else None
    if records:
        by_name: dict[str, list[dict]] = {}
        for rows in records.values():
            if rows and rows[0]["馬名"]:
                by_name.setdefault(rows[0]["馬名"], []).extend(rows)
        for rows in by_name.values():
            rows.sort(key=lambda r: r["日付"])
        records = by_name

    # 集計器
    acc: dict[tuple, list[int]] = defaultdict(list)        # (帯, 指標) -> 0/1 の並び
    box: dict[tuple, list[float]] = defaultdict(list)      # (帯, 箱) -> 1点あたり払戻
    box_hit: dict[tuple, list[int]] = defaultdict(list)
    cross: dict[tuple, list[int]] = defaultdict(list)      # (オッズ帯, 偏差帯) -> ◎複勝
    tops: list[float] = []
    tops_by_n: list[tuple[int, float]] = []   # (頭数, 1位の偏差値)
    gaps: list[tuple[float, int, int, dict[str, int]]] = []   # (差, ◎勝, ◎複, 箱的中)
    used = 0

    for stem in stems:
        race = load_race(directory, stem)
        if race is None:
            continue
        scores = score_race(race["horses"], None, kyori=kyori_by_stem.get(stem),
                            records=records, as_of=race_date(stem),
                            venue=race_venue(stem))
        marked = assign_marks(scores, baba="良")
        if len(marked) < 6:
            continue
        devs = by_umaban(scores, baba="良")          # 印が付かない馬も含めた全頭
        if not devs:
            continue
        top = max(devs.values())
        b = band_of(top)
        tops.append(top)
        tops_by_n.append((len(devs), top))
        used += 1

        order = [m.score.horse.umaban for m in marked]
        honmei = order[0]
        # load_race は top2/top3 しか持たないので、1着馬は結果CSVから直接読む
        first = first_place(directory / f"{stem}_結果.csv")
        acc[(b, "◎の勝率")].append(1 if first is not None and honmei == first else 0)
        acc[(b, "◎の複勝率")].append(1 if honmei in race["top3"] else 0)

        fav = next((h for h in race["horses"] if h.ninki == 1), None)
        if fav is not None:
            acc[(b, "1番人気の複勝率")].append(1 if fav.umaban in race["top3"] else 0)
            cross[(odds_band(fav.tansho_odds), b)].append(1 if honmei in race["top3"] else 0)

        box_this: dict[str, int] = {}
        for label, (kind, tickets) in boxes(order).items():
            inv, ret = settle(kind, tickets, race)
            if inv <= 0:
                continue
            box[(b, label)].append(ret / (inv / STAKE) / STAKE)   # 1点あたりの回収倍率
            box_hit[(b, label)].append(1 if ret > 0 else 0)
            box_this[label] = 1 if ret > 0 else 0

        # 「混戦」を1位の偏差値ではなく **1位と2位の差** で測り直す。
        # 1位の偏差値は頭数で決まってしまう（N頭の最大値は自然に約1.7σ）ため、
        # 接戦かどうかを表していない。差なら頭数に依らずメンバー内の離れ具合を表す
        ranked_dev = sorted(devs.values(), reverse=True)
        if len(ranked_dev) >= 2:
            gaps.append((ranked_dev[0] - ranked_dev[1],
                         acc[(b, "◎の勝率")][-1], acc[(b, "◎の複勝率")][-1], box_this))

    print(f"対象 {used}レース（{args.dir} / {args.races}"
          + (f" / {args.months}" if args.months else "") + "）")
    if tops:
        tops_sorted = sorted(tops)
        print(f"1位の偏差値: 中央値 {tops_sorted[len(tops_sorted)//2]:.1f}"
              f"  最小 {tops_sorted[0]:.1f}  最大 {tops_sorted[-1]:.1f}")
    counts = {b: len(acc[(b, "◎の複勝率")]) for b in BANDS}
    print("帯ごとのレース数: " + "  ".join(f"{b} {counts[b]}" for b in BANDS))
    report_fieldsize(tops_by_n)

    for metric in ["◎の勝率", "◎の複勝率", "1番人気の複勝率"]:
        print(f"\n■ {metric}（対照＝全レース）")
        print(HEADER)
        allrows = [v for b in BANDS for v in acc[(b, metric)]]
        if not allrows:
            continue
        ck, cn = sum(allrows), len(allrows)
        print(judge("全レース", ck, cn, ck, cn).line())
        for b in BANDS:
            rows = acc[(b, metric)]
            if rows:
                print(judge(b, sum(rows), len(rows), ck, cn).line())

    print("\n■ 箱買いの的中率（対照＝全レース）")
    print(HEADER)
    for label in ["ワイド 上位3頭BOX", "ワイド 上位6頭BOX", "馬連 上位4頭BOX"]:
        allrows = [v for b in BANDS for v in box_hit[(b, label)]]
        if not allrows:
            continue
        ck, cn = sum(allrows), len(allrows)
        print(judge(f"{label} 全体", ck, cn, ck, cn).line())
        for b in BANDS:
            rows = box_hit[(b, label)]
            if rows:
                print(judge(f"  {b}", sum(rows), len(rows), ck, cn).line())

    print("\n■ 箱買いの回収率（対照＝同じ箱の全レース）")
    print(ROI_HEADER)
    for label in ["ワイド 上位3頭BOX", "ワイド 上位6頭BOX", "馬連 上位4頭BOX"]:
        allpay = [v * STAKE for b in BANDS for v in box[(b, label)]]
        if not allpay:
            continue
        for b in BANDS:
            pay = [v * STAKE for v in box[(b, label)]]
            if len(pay) >= 30:
                print(judge_roi(f"{label} {b}", pay, allpay, stake=STAKE).line())

    print("\n■ 1番人気オッズで統制した ◎の複勝率")
    print("  「抜けている」が単に人気馬が強いレースなら、偏差値は市場の言い換えにすぎない")
    print(HEADER)
    for ob in ["1倍台", "2倍台", "3倍以上"]:
        rows_all = [v for b in BANDS for v in cross[(ob, b)]]
        if len(rows_all) < 30:
            continue
        ck, cn = sum(rows_all), len(rows_all)
        print(judge(f"{ob} 全体", ck, cn, ck, cn).line())
        for b in BANDS:
            rows = cross[(ob, b)]
            if rows:
                print(judge(f"  {b}", sum(rows), len(rows), ck, cn).line())

    report_gap(gaps)


def report_fieldsize(tops_by_n: list[tuple[int, float]]) -> None:
    """1位の偏差値が頭数で決まっていないかを見る。

    N頭の標準正規の最大値の期待値は N とともに上がる（14頭で約1.71σ＝偏差値67）。
    もし観測値がこれに沿うなら、1位の偏差値は「抜けているか」ではなく
    「何頭立てか」を測っていることになる。
    """
    if len(tops_by_n) < 100:
        return
    import statistics
    ns = [n for n, _ in tops_by_n]
    ts = [t for _, t in tops_by_n]
    r = statistics.correlation(ns, ts) if len(set(ns)) > 1 else 0.0
    print(f"\n■ 1位の偏差値は頭数で決まっていないか（相関 r={r:+.2f}）")
    by_n: dict[int, list[float]] = defaultdict(list)
    for n, t in tops_by_n:
        by_n[n].append(t)
    print(f"  {'頭数':>4}{'R数':>7}{'1位の偏差値(中央値)':>22}")
    for n in sorted(by_n):
        v = sorted(by_n[n])
        if len(v) >= 20:
            print(f"  {n:>4}{len(v):>7}{v[len(v)//2]:>22.1f}")


def report_gap(gaps) -> None:
    """1位と2位の偏差値差で四分位に割り、同じ指標を測る。"""
    if len(gaps) < 100:
        return
    gaps = sorted(gaps, key=lambda g: g[0])
    q = len(gaps) // 4
    buckets = [("差が小さい(接戦)", gaps[:q]), ("やや接戦", gaps[q:2 * q]),
               ("やや離れる", gaps[2 * q:3 * q]), ("差が大きい(抜けている)", gaps[3 * q:])]
    print("\n■ 1位と2位の偏差値差で割り直す（頭数に依らない接戦の指標）")
    lo, hi = gaps[0][0], gaps[-1][0]
    print(f"  差の範囲 {lo:.1f}〜{hi:.1f}  四分位の境目 "
          f"{gaps[q][0]:.1f} / {gaps[2 * q][0]:.1f} / {gaps[3 * q][0]:.1f}")
    for metric, idx in [("◎の勝率", 1), ("◎の複勝率", 2)]:
        print(f"\n  {metric}")
        print(HEADER)
        ck = sum(g[idx] for g in gaps); cn = len(gaps)
        print(judge("全レース", ck, cn, ck, cn).line())
        for name, rows in buckets:
            print(judge(name, sum(r[idx] for r in rows), len(rows), ck, cn).line())
    for label in ["ワイド 上位3頭BOX", "ワイド 上位6頭BOX", "馬連 上位4頭BOX"]:
        print(f"\n  {label} の的中率")
        print(HEADER)
        allr = [g[3][label] for g in gaps if label in g[3]]
        ck, cn = sum(allr), len(allr)
        if not cn:
            continue
        print(judge("全レース", ck, cn, ck, cn).line())
        for name, rows in buckets:
            r = [g[3][label] for g in rows if label in g[3]]
            if r:
                print(judge(name, sum(r), len(r), ck, cn).line())


if __name__ == "__main__":
    main()
