#!/usr/bin/env python3
"""1点買いの実測。「これだけ押さえればよい」1点を数字で決めるための集計。

点数を増やすほど的中率は上がるが回収率は下がる、という関係は既に確認済み
（scripts/boxstats.py）。その延長線上の端が1点買いになる。ここでは
**スコア順のどの組を1点だけ買うのが最も回収率が高いか**を測る。

測るもの:
  * 回収率と、ブートストラップ90%信頼区間
  * 100%を超えた割合（黒字確率）
  * 最大連敗と最大ドローダウン … 1点買いは外れが続くので資金面の目安が要る

    python3 scripts/single.py --dir data/collected --races 9-12 --ratings <path>
"""
from __future__ import annotations

import argparse
import datetime as dt
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
DOW = ["月曜", "火曜", "水曜", "木曜", "金曜", "土曜", "日曜"]
# スコア順の組み合わせ。(券種, i位, j位)
CANDIDATES = [
    ("ワイド", 1, 2), ("ワイド", 1, 3), ("ワイド", 2, 3),
    ("ワイド", 1, 4), ("ワイド", 1, 5), ("ワイド", 2, 4), ("ワイド", 3, 4),
    ("馬連", 1, 2), ("馬連", 1, 3), ("馬連", 2, 3),
]


def bootstrap(pairs, b=10000):
    if not pairs:
        return (0.0, 0.0, 0.0)
    rng = random.Random(20260905)
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
    ap.add_argument("--dir", default="data/collected")
    ap.add_argument("--races", default="9-12")
    ap.add_argument("--ratings")
    ap.add_argument("--race-info", default="data/profiles/nar/race_info.csv")
    ap.add_argument("--by-tier", action="store_true")
    ap.add_argument("--by-dow", action="store_true",
                    help="土曜・日曜に分けても集計する（曜日で中身が違わないかの確認）")
    ap.add_argument("--sort", choices=("的中率", "回収率"), default="回収率",
                    help="表の並び順。正解率を主指標にするときは 的中率")
    ap.add_argument("--out", help="結果をJSONで書き出す")
    ap.add_argument("--dump", help="レース×買い目の明細をCSVで書き出す。"
                    "スコア計算をやり直さずに年別・場別など任意の切り方で"
                    "measり直せるようにするため（再集計が数分→一瞬になる）")
    args = ap.parse_args()

    if args.ratings:
        table = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
        sc.load_ratings = lambda *a, **k: table

    wanted = parse_races(args.races)
    kyori_by = load_race_info(args.race_info)
    records = _load_horse_records()
    d = Path(args.dir)

    series: dict[tuple, list] = {}
    dump: list[dict] = []
    used = 0
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
        scope_list = ["全体", tier]
        if args.by_dow:
            date = race_date(stem)
            dow = DOW[dt.date.fromisoformat(date).weekday()] if date else None
            if dow:
                scope_list += [dow, f"{tier}/{dow}"]
        for kind, i, j in CANDIDATES:
            t = [frozenset({order[i - 1], order[j - 1]})]
            inv, ret = settle(kind, t, race)
            for scope in scope_list:
                series.setdefault((kind, i, j, scope), []).append((inv, ret))
            if args.dump:
                dump.append({"日付": race_date(stem), "stem": stem,
                             "場": race_venue(stem), "R": rn, "帯": tier,
                             "1番人気オッズ": fav.tansho_odds,
                             "券種": kind, "i": i, "j": j,
                             "投資": inv, "払戻": ret})

    scopes = ["全体"] + (["1倍台", "2倍台", "3倍以上"] if args.by_tier else [])
    if args.by_dow:
        scopes += ["土曜", "日曜"]
        if args.by_tier:
            scopes += [f"{t}/{d}" for t in ("1倍台", "2倍台", "3倍以上")
                       for d in ("土曜", "日曜")]
    print(f"{args.dir} {args.races}R {used}レース・1点{STAKE}円・ブートストラップ1万回\n")
    payload = {"レース数": used, "対象": args.dir, "1点買い": {}}
    for scope in scopes:
        rows = []
        for kind, i, j in CANDIDATES:
            pairs = series.get((kind, i, j, scope))
            if not pairs:
                continue
            inv = sum(a for a, _ in pairs)
            ret = sum(b for _, b in pairs)
            hit = sum(1 for _, b in pairs if b > 0)
            lo, hi, win = bootstrap(pairs)
            run, dd = streak_and_dd(pairs)
            rows.append((f"{kind} {i}位-{j}位", len(pairs), hit / len(pairs),
                         ret / inv, lo, hi, win, run, dd, hit))
            payload["1点買い"].setdefault(scope, {})[f"{kind}{i}-{j}"] = {
                "n": len(pairs), "的中率": round(hit / len(pairs), 4),
                "回収率": round(ret / inv, 4), "区間下": round(lo, 4),
                "区間上": round(hi, 4), "黒字確率": round(win, 4),
                "的中本数": hit, "最大連敗": run, "最大DD": dd,
            }
        rows.sort(key=lambda r: -(r[2] if args.sort == "的中率" else r[3]))
        print(f"── {scope} " + "─" * 58)
        print(f"{'買い目':<16}{'R数':>5}{'的中':>5}{'的中率':>7}{'回収率':>7}{'90%区間':>17}"
              f"{'黒字確率':>9}{'最大連敗':>8}{'最大DD':>10}")
        for r in rows:
            span = f"{r[4]:.0%} 〜 {r[5]:.0%}"
            print(f"{r[0]:<16}{r[1]:>5}{r[9]:>5}{r[2]:>7.0%}{r[3]:>7.0%}{span:>17}"
                  f"{r[6]:>9.0%}{r[7]:>7}連{r[8]:>+9,}円")
        print()
    if args.dump:
        import csv as _csv
        with open(args.dump, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.DictWriter(f, fieldnames=list(dump[0].keys()))
            w.writeheader()
            w.writerows(dump)
        print(f"書き出し: {args.dump}（{len(dump)}行）")

    if args.out:
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"書き出し: {args.out}")


if __name__ == "__main__":
    main()
