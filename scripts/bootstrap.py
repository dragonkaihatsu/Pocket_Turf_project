#!/usr/bin/env python3
"""買い方ごとの回収率を、ブートストラップ信頼区間つきで評価する。

競馬の払戻は確率の逆数なので、回収は少数の高配当に集中する。これは
外れ値ではなく賭けている対象そのものであり、大きい払戻を除いて評価すると
体系的に下振れした数字になる。**除かずに、ばらつきの大きさを測る**のが正しい。

出すもの:
  * 回収率（実測）
  * ブートストラップ90%信頼区間 … レースを復元抽出し直したときの回収率の幅
  * 100%以上になった割合 … 「勝てる側に転ぶ確率」の目安
  * 最大連敗・最大ドローダウン … その配当を待つ間に必要な資金

    python3 scripts/bootstrap.py --races 9-12 --ratings <path>
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keiba.scoring as sc
from backtest import load_race, load_race_info, parse_races, race_date, race_number, settle
from keiba.betting import make_betting_plan
from keiba.cli import _load_horse_records
from keiba.marks import assign_marks

STAKE = 100
B = 10000


def bootstrap(pairs: list[tuple[int, int]], b: int = B) -> tuple[float, float, float]:
    """(投資, 回収) の列からブートストラップで回収率の分布を作る。

    戻り値は (5パーセンタイル, 95パーセンタイル, 100%以上になった割合)。
    """
    if not pairs:
        return (0.0, 0.0, 0.0)
    rng = random.Random(20260904)
    n = len(pairs)
    rates = []
    for _ in range(b):
        inv = ret = 0
        for _ in range(n):
            i, r = pairs[rng.randrange(n)]
            inv += i
            ret += r
        rates.append(ret / inv if inv else 0.0)
    rates.sort()
    win = sum(1 for r in rates if r >= 1.0) / len(rates)
    return (rates[int(0.05 * len(rates))], rates[int(0.95 * len(rates))], win)


def drawdown(pairs: list[tuple[int, int]]) -> tuple[int, int]:
    """(最大連敗, 最大ドローダウン)。その配当を待つ間に必要な資金の目安。"""
    cum = peak = dd = streak = worst = 0
    for inv, ret in pairs:
        cum += ret - inv
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
        streak = 0 if ret > 0 else streak + 1
        worst = max(worst, streak)
    return worst, dd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected")
    ap.add_argument("--races", default="9-12")
    ap.add_argument("--ratings")
    ap.add_argument("--race-info", default="data/race_info.csv")
    ap.add_argument("--bootstrap", type=int, default=B)
    args = ap.parse_args()

    if args.ratings:
        table = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
        sc.load_ratings = lambda *a, **k: table

    wanted = parse_races(args.races)
    kyori_by = load_race_info(args.race_info)
    records = _load_horse_records()
    d = Path(args.dir)

    series: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for stem in sorted({p.name.replace("_結果.csv", "") for p in d.glob("*_結果.csv")}):
        rn = race_number(stem)
        if rn is None or rn not in wanted:
            continue
        race = load_race(d, stem)
        if race is None:
            continue
        fav = min((h for h in race["horses"] if h.ninki), key=lambda h: h.ninki, default=None)
        if fav is None or not fav.tansho_odds:
            continue
        tier = ("1倍台" if fav.tansho_odds < 2.0
                else "2倍台" if fav.tansho_odds < 3.0 else "3倍以上")
        scores = sc.score_race(race["horses"], None, kyori=kyori_by.get(stem),
                               records=records, as_of=race_date(stem))
        marked = assign_marks(scores, baba="良")
        if len(marked) < 6:
            continue
        order = [m.score.horse.umaban for m in marked]
        plan = make_betting_plan(marked, baba="良", favorite_odds=fav.tansho_odds)

        entries: dict[str, tuple[str, list]] = {}
        if plan.wide:
            entries[f"{plan.strategy}型(システム)"] = (
                "ワイド", [frozenset(m.score.horse.umaban for m in t.horses) for t in plan.wide])
        elif plan.umaren:
            entries[f"{plan.strategy}型(システム)"] = (
                "馬連", [frozenset(m.score.horse.umaban for m in t.horses) for t in plan.umaren])
        entries["馬連 上位4頭BOX(6点)"] = ("馬連", [frozenset(c) for c in combinations(order[:4], 2)])
        entries["馬連 上位5頭BOX(10点)"] = ("馬連", [frozenset(c) for c in combinations(order[:5], 2)])
        entries["ワイド 上位3頭BOX(3点)"] = ("ワイド", [frozenset(c) for c in combinations(order[:3], 2)])
        entries["ワイド 上位4頭BOX(6点)"] = ("ワイド", [frozenset(c) for c in combinations(order[:4], 2)])
        for label, (kind, tickets) in entries.items():
            series.setdefault((tier, label), []).append(settle(kind, tickets, race))

    print(f"大井{args.races}R・1点{STAKE}円・ブートストラップ{args.bootstrap:,}回")
    print("大きい払戻も除かずに評価し、ばらつきを信頼区間で示す\n")
    hdr = (f"{'オッズ帯':<8}{'買い方':<22}{'R数':>5}{'的中率':>7}{'回収率':>7}"
           f"{'90%信頼区間':>18}{'100%超':>7}{'最大連敗':>7}{'最大DD':>10}")
    print(hdr)
    for tier in ("1倍台", "2倍台", "3倍以上"):
        rows = [(k[1], v) for k, v in series.items() if k[0] == tier]
        for label, pairs in sorted(rows, key=lambda x: -sum(r for _, r in x[1]) / max(sum(i for i, _ in x[1]), 1)):
            inv = sum(i for i, _ in pairs)
            ret = sum(r for _, r in pairs)
            hit = sum(1 for _, r in pairs if r > 0)
            lo, hi, win = bootstrap(pairs, args.bootstrap)
            streak, dd = drawdown(pairs)
            print(f"{tier:<8}{label:<22}{len(pairs):>5}{hit/len(pairs):>7.0%}"
                  f"{ret/inv:>7.0%}{f'{lo:.0%} 〜 {hi:.0%}':>18}{win:>7.0%}"
                  f"{streak:>6}連{dd:>+9,}円")
        print()
    print("  90%信頼区間 = 同じ買い方を別の期間で続けたときに入りうる回収率の幅")
    print("  100%超 = ブートストラップで回収率が100%以上になった割合")
    print("  最大DD = 累積収支の最大下落幅。高配当を待つ間に必要な資金の目安")


if __name__ == "__main__":
    main()
