#!/usr/bin/env python3
"""単勝・複勝1点買いの実測。scripts/single.py（ワイド/馬連の1点買い）を
単勝・複勝向けにコピーして作った。

単勝・複勝は「馬番が1つだけ」の買い目なので、配当CSVの該当行が
そのままヒット判定になる（的中した馬だけが券種テーブルに載るため、
top2/top3 との突き合わせは不要）。

    python3 scripts/tanpuku.py --dir data/collected_jra --races 9-12 \
        --race-info data/profiles/jra/race_info.csv \
        --out data/profiles/jra/tanpuku_stats.json

**大井（地方）は対象外**。地方の1番人気は複勝率75.9%と中央(62.8%)より
堅く、実測値を取り違えると「もっともらしい間違った予想」になる
（keiba/profile.py 参照）。--dir に data/collected_jra 以外の
大井データが混ざっていないか、レース単位でも念のため確認する。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keiba.scoring as sc
from backtest import (load_race, load_race_info, parse_races, race_date,
                      race_number, race_venue, settle)
from keiba.cli import _load_horse_records
from keiba.marks import assign_marks

STAKE = 100
# スコア順位。(券種, 順位)。単勝は上位が薄くなりやすいので5位まで、
# 複勝は3着以内に絡む可能性がある8位まで見る
CANDIDATES = ([("単勝", r) for r in range(1, 6)] +
              [("複勝", r) for r in range(1, 9)])


def settle_single(kind: str, umaban: int, race: dict) -> tuple[int, int]:
    """(投資, 払戻) を返す。単勝・複勝は馬番1つが払戻テーブルのキーそのもの。"""
    table = race["payouts"].get(kind, {})
    return STAKE, table.get(frozenset({umaban}), 0)


def bootstrap(pairs, b=10000):
    if not pairs:
        return (0.0, 0.0, 0.0)
    rng = random.Random(20260909)
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
    return (rates[int(0.05 * len(rates))], rates[int(0.95 * len(rates))],
            sum(1 for r in rates if r >= 1.0) / len(rates))


def streak_and_dd(pairs):
    cum = peak = dd = run = worst = 0
    for inv, ret in pairs:
        cum += ret - inv
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
        run = 0 if ret > 0 else run + 1
        worst = max(worst, run)
    return worst, dd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra",
                     help="既定は中央のみ（data/collected_jra）。大井を含む "
                          "data/collected は対象外")
    ap.add_argument("--races", default="9-12")
    ap.add_argument("--ratings")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--by-tier", action="store_true")
    ap.add_argument("--out", help="結果をJSONで書き出す")
    args = ap.parse_args()

    if args.ratings:
        table = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
        sc.load_ratings = lambda *a, **k: table

    wanted = parse_races(args.races)
    kyori_by = load_race_info(args.race_info)
    records = _load_horse_records()
    d = Path(args.dir)

    series: dict[tuple, list] = {}
    used = skipped_oi = 0
    for stem in sorted({p.name.replace("_結果.csv", "") for p in d.glob("*_結果.csv")}):
        if "大井" in stem:
            # --dir を誤って大井データに向けても地方の数値が中央のプロファイルに
            # 混ざらないよう、レース単位でも弾く（keiba/profile.py の注意点）
            skipped_oi += 1
            continue
        rn = race_number(stem)
        if rn is None or rn not in wanted:
            continue
        race = load_race(d, stem)
        if race is None:
            continue
        fav = min((h for h in race["horses"] if h.ninki), key=lambda h: h.ninki, default=None)
        if fav is None or not fav.tansho_odds:
            continue
        scores = sc.score_race(race["horses"], None, kyori=kyori_by.get(stem),
                               records=records, as_of=race_date(stem),
                               venue=race_venue(stem))
        marked = assign_marks(scores, baba="良")
        if len(marked) < 5:
            continue
        used += 1
        order = [m.score.horse.umaban for m in marked]
        tier = ("1倍台" if fav.tansho_odds < 2.0
                else "2倍台" if fav.tansho_odds < 3.0 else "3倍以上")
        for kind, r in CANDIDATES:
            if r > len(order):
                continue
            pair = settle_single(kind, order[r - 1], race)
            for scope in ("全体", tier):
                series.setdefault((kind, r, scope), []).append(pair)

    if skipped_oi:
        print(f"注意: 大井のレースを{skipped_oi}件スキップした（このスクリプトの対象外）\n")

    scopes = ["全体"] + (["1倍台", "2倍台", "3倍以上"] if args.by_tier else [])
    print(f"{args.dir} {args.races}R {used}レース・1点{STAKE}円・ブートストラップ1万回\n")
    payload = {"レース数": used, "対象": args.dir, "単複": {}}
    for scope in scopes:
        rows = []
        for kind, r in CANDIDATES:
            pairs = series.get((kind, r, scope))
            if not pairs:
                continue
            inv = sum(a for a, _ in pairs)
            ret = sum(b for _, b in pairs)
            hit = sum(1 for _, b in pairs if b > 0)
            lo, hi, win = bootstrap(pairs)
            run, dd = streak_and_dd(pairs)
            rows.append((f"{kind} {r}位", len(pairs), hit / len(pairs),
                         ret / inv, lo, hi, win, run, dd))
            payload["単複"].setdefault(scope, {})[f"{kind}{r}"] = {
                "n": len(pairs), "的中率": round(hit / len(pairs), 4),
                "回収率": round(ret / inv, 4), "区間下": round(lo, 4),
                "区間上": round(hi, 4), "黒字確率": round(win, 4),
                "最大連敗": run, "最大DD": dd,
            }
        rows.sort(key=lambda r: -r[3])
        print(f"── {scope} " + "─" * 58)
        print(f"{'買い目':<12}{'R数':>5}{'的中率':>7}{'回収率':>7}{'90%区間':>17}"
              f"{'黒字確率':>9}{'最大連敗':>8}{'最大DD':>10}")
        for r in rows:
            span = f"{r[4]:.0%} 〜 {r[5]:.0%}"
            print(f"{r[0]:<12}{r[1]:>5}{r[2]:>7.0%}{r[3]:>7.0%}{span:>17}"
                  f"{r[6]:>9.0%}{r[7]:>7}連{r[8]:>+9,}円")
        print()
    if args.out:
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"書き出し: {args.out}")


if __name__ == "__main__":
    main()
