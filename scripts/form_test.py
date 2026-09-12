#!/usr/bin/env python3
"""騎手の「調子」「波」「ツキ」は次のレースに効くか（連続性の検定）。

「騎手の調子、行けるかもという波や、ツキのようなものは母数が少ない分、単なる
偶然に終わることもあるかもしれない」（本人の言葉・2026-09-12）。

これは測れる。ただし素朴に「直近が good な騎手」と「bad な騎手」を比べると
**調子ではなく騎手の実力を測ってしまう**（上手い騎手はいつでも直近成績が良い）。
そこで2通り出す:

  素朴版   … 全騎手をまとめて好調群 vs 不調群。騎手の実力が混ざる
  騎手内版 … 各騎手を「その騎手自身の平常時」と比べる。実力が打ち消える

騎手内版が本当の検定である。調子の指標は **そのレースより前の騎乗だけ** から
作る（同日を含めない）ので情報漏れは無い。

さらに `--permute N` で並べ替え検定を行う。**「好調のあと」を条件に次の成績を
見ると、連続がまったく無いデータでも差がマイナスに出る**（Miller-Sanjurjo 型の
バイアス。ある騎乗の結果はそれ以降の窓に入るため、好調群は構造的に「直前に
好走した騎乗」に偏る）。各騎手×人気帯の中で結果の順番だけを壊した帰無分布と
比べて初めて、調子が実在するかを言える。

    python3 scripts/form_test.py
    python3 scripts/form_test.py --window 50         # 直近50騎乗で調子を測る
    python3 scripts/form_test.py --permute 3000      # 並べ替え検定（数百回では足りない）
"""
from __future__ import annotations

import argparse
import collections
import csv
import itertools
import random
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.power import min_detectable_diff, wilson
from keiba.racefiles import DEFAULT_RACES, result_paths

BANDS = (("1-3番人気", 1, 3), ("4-5番人気", 4, 5), ("6-9番人気", 6, 9),
         ("10番人気以下", 10, 99), ("（全体）", 1, 99))


def load_rides(directory: str, races: str) -> list[dict]:
    rides: list[dict] = []
    for path in result_paths(directory, races):
        text = str(path)
        m = re.search(r"(\d{4}-\d{2}-\d{2})_", text)
        if not m:
            continue
        with open(text, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                try:
                    chaku = int(row.get("着順"))
                    ninki = int(row.get("人気"))
                except (TypeError, ValueError):
                    continue
                try:
                    odds = float(row.get("単勝オッズ"))
                except (TypeError, ValueError):
                    odds = None
                rides.append({
                    "date": m.group(1),
                    "jockey": (row.get("騎手") or "").strip(),
                    "chaku": chaku,
                    "ninki": ninki,
                    "odds": odds,
                    "place": chaku <= 3,
                    "win": chaku == 1,
                })
    rides.sort(key=lambda r: r["date"])
    return rides


def attach_form(rides: list[dict], window: int) -> None:
    """各騎乗に、その日より前の直近 window 騎乗での複勝率を付ける。

    同じ日のレースは「まだ結果が出ていない」扱いにする（朝の時点で分かる情報に
    そろえる）。これを怠ると同日の好走がそのまま調子に入り、循環する。
    """
    hist: dict[str, list[tuple[str, bool]]] = collections.defaultdict(list)
    for ride in rides:
        past = [p for d, p in hist[ride["jockey"]] if d < ride["date"]]
        ride["form"] = sum(past[-window:]) / window if len(past) >= window else None
        hist[ride["jockey"]].append((ride["date"], ride["place"]))


def cell(rows: list[dict], key: str = "place") -> tuple[int, int, float]:
    hits = sum(1 for r in rows if r[key])
    return len(rows), hits, (hits / len(rows) if rows else 0.0)


def verdict(test: list[dict], base: list[dict], key: str = "place") -> str:
    n_t, k_t, p_t = cell(test, key)
    _, _, p_b = cell(base, key)
    if not n_t:
        return "—"
    lo, hi = wilson(k_t, n_t)
    if not lo <= p_b <= hi:
        return "差あり"
    return "差なし" if min_detectable_diff(n_t, p_b) <= 0.05 else "判定不能"


def report(hot: list[dict], cold: list[dict], title: str, key: str = "place") -> None:
    print(f"  {title}")
    print(f"    {'人気帯':<14}{'好調 n':>8}{'率':>8}{'不調 n':>8}{'率':>8}{'差':>9}{'判定':>10}")
    for label, lo, hi in BANDS:
        h = [r for r in hot if lo <= r["ninki"] <= hi]
        c = [r for r in cold if lo <= r["ninki"] <= hi]
        if not h or not c:
            continue
        n_h, _, p_h = cell(h, key)
        n_c, _, p_c = cell(c, key)
        print(f"    {label:<14}{n_h:>8,}{p_h * 100:>7.1f}%{n_c:>8,}{p_c * 100:>7.1f}%"
              f"{(p_h - p_c) * 100:>8.1f}pt{verdict(h, c, key):>10}")


def permutation_test(rides: list[dict], window: int, min_rides: int,
                     n_perm: int, seed: int = 20260912) -> None:
    """騎手×人気帯の中で結果の順番だけを壊した帰無分布と実測を比べる。

    その騎手のその帯での複勝率は保たれ、時間的な連続性だけが消える。調子が
    実在しないなら実測値は帰無分布の中に収まる。帰無分布の平均がゼロから
    離れている分が、連続を条件にすることで生じる見かけの差そのもの。
    """
    n = len(rides)
    band_of = [next(i for i, (_, lo, hi) in enumerate(BANDS[:-1]) if lo <= r["ninki"] <= hi)
               for r in rides]

    # 騎手ごとに日付でまとめたインデックス列（同日は調子に入れない）
    order = sorted(range(n), key=lambda i: (rides[i]["jockey"], rides[i]["date"]))
    groups: dict[str, list[list[int]]] = {}
    for jockey, idxs in itertools.groupby(order, key=lambda i: rides[i]["jockey"]):
        days = [list(g) for _, g in itertools.groupby(idxs, key=lambda i: rides[i]["date"])]
        if sum(len(d) for d in days) >= min_rides:
            groups[jockey] = days

    def gaps(place: list[int]) -> tuple[list[float | None], list[list[int]], list[list[int]]]:
        hot = [[0, 0] for _ in BANDS[:-1]]
        cold = [[0, 0] for _ in BANDS[:-1]]
        for days in groups.values():
            hist: list[int] = []
            seen: list[tuple[float, int]] = []
            for day in days:
                form = sum(hist[-window:]) / window if len(hist) >= window else None
                for i in day:
                    if form is not None:
                        seen.append((form, i))
                    hist.append(place[i])
            if len(seen) < min_rides:
                continue
            vals = sorted(f for f, _ in seen)
            med = vals[len(vals) // 2]
            for form, i in seen:
                target = hot if form > med else (cold if form < med else None)
                if target is None:
                    continue
                target[band_of[i]][0] += 1
                target[band_of[i]][1] += place[i]
        out = [(h[1] / h[0] - c[1] / c[0]) * 100 if h[0] and c[0] else None
               for h, c in zip(hot, cold)]
        return out, hot, cold

    place = [1 if r["place"] else 0 for r in rides]
    observed, hot, cold = gaps(place)

    strata: dict[tuple[str, int], list[int]] = collections.defaultdict(list)
    for i in range(n):
        strata[(rides[i]["jockey"], band_of[i])].append(i)

    rng = random.Random(seed)
    null: list[list[float]] = [[] for _ in BANDS[:-1]]
    shuffled = place[:]
    for _ in range(n_perm):
        for idxs in strata.values():
            vals = [place[i] for i in idxs]
            rng.shuffle(vals)
            for i, v in zip(idxs, vals):
                shuffled[i] = v
        g, _, _ = gaps(shuffled)
        for b, val in enumerate(g):
            if val is not None:
                null[b].append(val)

    print(f"■ 並べ替え検定（{n_perm}回）: 騎手×人気帯の中で結果の順番だけを壊す")
    print("  調子が実在しないなら、実測値は帰無分布の中に収まる")
    print(f"  {'人気帯':<14}{'好調n':>7}{'不調n':>7}{'実測':>9}{'帰無の平均':>12}"
          f"{'帰無90%区間':>17}{'p':>8}{'判定':>18}")
    for b, (label, _, _) in enumerate(BANDS[:-1]):
        dist = sorted(null[b])
        if not dist or observed[b] is None:
            continue
        mu = statistics.fmean(dist)
        lo, hi = dist[int(0.05 * len(dist))], dist[int(0.95 * len(dist))]
        obs = observed[b]
        p = sum(1 for x in dist if x <= obs) / len(dist)
        tag = "バイアスの範囲内" if lo <= obs <= hi else "外れている"
        print(f"  {label:<14}{hot[b][0]:>7,}{cold[b][0]:>7,}{obs:>8.1f}pt{mu:>11.1f}pt"
              f"  [{lo:>5.1f},{hi:>5.1f}]{p:>8.3f}{tag:>18}")
    print()
    print("  帰無の平均がゼロから離れている分が、連続を条件にすることで生じる")
    print("  見かけの差。実測がそこに収まるなら『調子』は観測できていない")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--window", type=int, default=30, help="調子を測る直近騎乗数")
    ap.add_argument("--min-rides", type=int, default=60,
                    help="騎手内比較に入れる最低騎乗数（好調・不調の両側を作るため）")
    ap.add_argument("--permute", type=int, default=0,
                    help="並べ替え検定の回数。数百回では帰無分布が狭く出るので3000程度")
    args = ap.parse_args()

    rides = load_rides(args.dir, args.races)
    attach_form(rides, args.window)
    usable = [r for r in rides if r["form"] is not None]
    print(f"延べ {len(rides):,}騎乗 / 調子を算出できた {len(usable):,}騎乗"
          f"（直近{args.window}騎乗ぶんの履歴が必要）\n")

    # --- 素朴版: 全騎手をまとめて三分割
    forms = sorted(r["form"] for r in usable)
    lo_q, hi_q = forms[len(forms) // 3], forms[len(forms) * 2 // 3]
    print("■ 素朴版: 全騎手まとめて好調群(上位1/3) vs 不調群(下位1/3)")
    print(f"  しきい値 複勝率 {lo_q * 100:.1f}% / {hi_q * 100:.1f}%")
    report([r for r in usable if r["form"] >= hi_q],
           [r for r in usable if r["form"] <= lo_q],
           "→ この差には「上手い騎手はいつも直近成績が良い」が混ざっている")
    print()

    # --- 騎手内版: 各騎手を自分自身の平常時と比べる
    by_j: dict[str, list[dict]] = collections.defaultdict(list)
    for r in usable:
        by_j[r["jockey"]].append(r)
    hot: list[dict] = []
    cold: list[dict] = []
    n_jockeys = 0
    for jockey, rows in by_j.items():
        if len(rows) < args.min_rides:
            continue
        vals = sorted(r["form"] for r in rows)
        med = vals[len(vals) // 2]
        h = [r for r in rows if r["form"] > med]
        c = [r for r in rows if r["form"] < med]
        if not h or not c:
            continue
        n_jockeys += 1
        hot.extend(h)
        cold.extend(c)
    print(f"■ 騎手内版: 各騎手の「自分の調子の中央値より上／下」で分ける"
          f"（{n_jockeys}人・騎乗{args.min_rides}以上）")
    print("  同じ騎手が好調側にも不調側にも入るので、騎手の実力は打ち消える")
    report(hot, cold, "【複勝率】")
    report(hot, cold, "【勝率】", key="win")
    print()

    print("■ 期間で割って再現するか（騎手内版・複勝率）")
    for year in ("2025", "2026"):
        report([r for r in hot if r["date"].startswith(year)],
               [r for r in cold if r["date"].startswith(year)],
               f"【{year}年】")
    print()

    if args.permute:
        permutation_test(rides, args.window, args.min_rides, args.permute)
        print()

    print("■ 単勝回収率（騎手内版）")
    print(f"  {'人気帯':<14}{'好調':>10}{'不調':>10}")
    for label, lo, hi in BANDS:
        out = []
        for group in (hot, cold):
            v = [r for r in group if lo <= r["ninki"] <= hi and r["odds"]]
            out.append(sum(r["odds"] for r in v if r["win"]) / len(v) * 100 if v else 0.0)
        print(f"  {label:<14}{out[0]:>9.0f}%{out[1]:>9.0f}%")


if __name__ == "__main__":
    main()
