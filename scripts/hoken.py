#!/usr/bin/env python3
"""馬連＋ワイドの併買を「保険」として検証する。

狙いは回収率ではない。**0円になるレースを減らすこと**である。
馬連5頭BOXは当たれば大きいが、外れれば全額消える。ワイドを重ねると
的中の下支えになる代わりに、点数ぶん回収率は下がる。その取引が
割に合うかを、0円レース率・連敗・必要資金で測る。

提案されたモデル:
    馬連 上位5頭BOX  100円 × 10点 = 1,000円
    ワイド 上位3頭BOX 500円 ×  3点 = 1,500円   計 2,500円
  さらに「鉄板なら3頭・主役不在なら4頭」と幅を切り替える。
  予算を揃えるため、4頭のときは 250円 × 6点 = 1,500円 とする。

    python3 scripts/hoken.py --profile jra --year 2026
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keiba.scoring as sc
from backtest import (load_race, load_race_info, parse_races, race_date,
                      race_number, race_venue)
from keiba.cli import _load_horse_records
from keiba.marks import assign_marks

# 鉄板と主役不在の境目。既存の thresholds.json と同じ 3.0倍に置く
TEPPAN_MAX = 3.0


def payout(kind, combo, race, stake):
    """stake円 賭けたときの払戻。配当は100円あたりなので比で伸ばす。"""
    hit = (combo <= race["top3"]) if kind == "ワイド" else (combo == race["top2"])
    if not hit:
        return 0
    return race["payouts"].get(kind, {}).get(combo, 0) * stake // 100


def box(kind, order, k, stake, race):
    inv = ret = 0
    for c in combinations(order[:k], 2):
        inv += stake
        ret += payout(kind, frozenset(c), race, stake)
    return inv, ret


# --- 買い方の定義。(名前, 1レースを処理する関数) ------------------------

def only_umaren(race, order):
    return box("馬連", order, 5, 100, race)


def only_wide3(race, order):
    return box("ワイド", order, 3, 500, race)


def combi_fixed3(race, order):
    a = box("馬連", order, 5, 100, race)
    b = box("ワイド", order, 3, 500, race)
    return a[0] + b[0], a[1] + b[1]


def combi_fixed4(race, order):
    a = box("馬連", order, 5, 100, race)
    b = box("ワイド", order, 4, 250, race)
    return a[0] + b[0], a[1] + b[1]


def combi_switch(race, order):
    """鉄板ならワイド3頭に絞り、主役不在なら4頭に広げる。"""
    if race["fav_odds"] is not None and race["fav_odds"] < TEPPAN_MAX:
        return combi_fixed3(race, order)
    return combi_fixed4(race, order)


ARMS = [
    ("馬連5頭のみ(10点)", only_umaren),
    ("ワイド3頭のみ(3点)", only_wide3),
    ("併買・ワイド3頭固定", combi_fixed3),
    ("併買・ワイド4頭固定", combi_fixed4),
    ("併買・鉄板3頭/不在4頭", combi_switch),
]


def bootstrap(pairs, n=10000, seed=0):
    rnd = random.Random(seed)
    N = len(pairs)
    rates = []
    for _ in range(n):
        inv = ret = 0
        for _ in range(N):
            i, r = pairs[rnd.randrange(N)]
            inv += i
            ret += r
        rates.append(ret / inv if inv else 0.0)
    rates.sort()
    return rates[int(.05 * n)], rates[int(.95 * n) - 1], \
        sum(1 for x in rates if x >= 1.0) / n


def summarize(pairs):
    inv = sum(i for i, _ in pairs)
    ret = sum(r for _, r in pairs)
    zero = sum(1 for _, r in pairs if r == 0)
    cum = low = streak = worst = 0
    for i, r in pairs:
        cum += r - i
        low = min(low, cum)
        if r == 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    lo, hi, win = bootstrap(pairs)
    return {"n": len(pairs), "inv": inv, "ret": ret, "pl": ret - inv,
            "roi": ret / inv if inv else 0, "zero": zero / len(pairs),
            "low": low, "streak": worst, "lo": lo, "hi": hi, "win": win}


def show(title, res):
    print(f"\n── {title} " + "─" * max(0, 40 - len(title)))
    print(f"{'買い方':<22}{'1R':>7}{'投資':>10}{'収支':>11}{'回収率':>7}"
          f"{'0円率':>7}{'0円連敗':>8}{'必要資金':>10}{'100%超':>7}")
    for name, _ in ARMS:
        d = res.get(name)
        if not d:
            continue
        per = d["inv"] // d["n"]
        print(f"{name:<22}{per:>7,}{d['inv']:>10,}{d['pl']:>+11,}{d['roi']:>7.0%}"
              f"{d['zero']:>7.0%}{d['streak']:>8}{-d['low']:>10,}{d['win']:>7.0%}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["nar", "jra"], default="jra")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--races", default="9-12")
    ap.add_argument("--year")
    args = ap.parse_args()

    import keiba.profile as profile
    prof = profile.use(args.profile)
    kyori_by = load_race_info(str(prof.path("race_info.csv")))
    records = _load_horse_records(str(prof.path("horse_records.csv")))
    wanted = parse_races(args.races)
    d = Path(args.dir or ("data/collected" if args.profile == "nar"
                          else "data/collected_jra"))

    races = []
    for stem in sorted({p.name[:-len("_結果.csv")] for p in d.glob("*_結果.csv")}):
        rn = race_number(stem)
        if rn is None or rn not in wanted:
            continue
        if args.year and not stem.startswith(args.year):
            continue
        race = load_race(d, stem)
        if race is None:
            continue
        fav = min((h for h in race["horses"] if h.ninki),
                  key=lambda h: h.ninki, default=None)
        race["fav_odds"] = fav.tansho_odds if fav else None
        scores = sc.score_race(race["horses"], None, kyori=kyori_by.get(stem),
                               records=records, as_of=race_date(stem),
                               venue=race_venue(stem))
        marked = assign_marks(scores, baba="良")
        order = [m.score.horse.umaban for m in marked]
        if len(order) < 5:
            continue
        race["order"] = order
        races.append(race)

    label = ("中央" if args.profile == "jra" else "地方") + \
            (f" {args.year}年" if args.year else "")
    print(f"{label} {args.races}R {len(races)}レース")
    print(f"鉄板（1番人気{TEPPAN_MAX}倍未満）"
          f" {sum(1 for r in races if r['fav_odds'] and r['fav_odds'] < TEPPAN_MAX)}"
          f" / 主役不在 "
          f"{sum(1 for r in races if not r['fav_odds'] or r['fav_odds'] >= TEPPAN_MAX)}")

    # 主張の確認
    wide_pays = [v for r in races for v in r["payouts"].get("ワイド", {}).values()]
    umaren_pays = [v for r in races for c, v in r["payouts"].get("馬連", {}).items()
                   if c == r["top2"]]
    print(f"\n実際の配当: ワイド 中央値{statistics.median(wide_pays):,.0f}円 "
          f"最高{max(wide_pays):,}円 / 万馬券"
          f"{sum(1 for v in wide_pays if v >= 10000)}件"
          f"({sum(1 for v in wide_pays if v >= 10000)/len(wide_pays):.2%})")
    print(f"            馬連 平均{statistics.mean(umaren_pays):,.0f}円 "
          f"中央値{statistics.median(umaren_pays):,.0f}円 "
          f"最高{max(umaren_pays):,}円")

    def block(title, subset):
        if not subset:
            return
        res = {}
        for name, fn in ARMS:
            res[name] = summarize([fn(r, r["order"]) for r in subset])
        show(f"{title}（{len(subset)}レース）", res)

    block("全レース", races)
    block("鉄板（1番人気3倍未満）",
          [r for r in races if r["fav_odds"] and r["fav_odds"] < TEPPAN_MAX])
    block("主役不在（1番人気3倍以上）",
          [r for r in races if not r["fav_odds"] or r["fav_odds"] >= TEPPAN_MAX])


if __name__ == "__main__":
    main()
