#!/usr/bin/env python3
"""レース区分（障害／新馬／未勝利／条件／固有名）ごとに買い目の実測を並べる。

「レース数を絞る重要性が今日わかりました。一応障害と、新馬戦は除外する
ことでお願いします」（本人の指示・2026-09-22）に対して、**除外の根拠を
数字で残す**ためのスクリプト。CLAUDE.mdの規則「数字を載せるなら、その
数字を再現する行をスクリプトに残す」に従う。

障害と新馬はスコアの入力そのものが欠ける:

    障害 … `index_of_record` が芝ダ以外を除くので持ち時計が作れず、
            上がり3Fも `parse_agari_3f` の 30.0〜48.0秒の外に出る
    新馬 … 過去走が無いので前走内容が全馬同点・持ち時計も作れない

だから「当たらない」以前に**採点できていない**。それを点差と発火率で
確認し、買い目の実測も添える。

    python3 scripts/taisho.py --races 1-12
    python3 scripts/taisho.py --races 1-12 --sample 300   # 抜き取りで速く見る
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keiba.scoring as sc
from backtest import (load_race, load_race_info, parse_races, race_date,
                      race_number, race_venue, settle)
from keiba.cli import _load_horse_records
from keiba.marks import assign_marks
from keiba.target import race_class


def load_surface(path: str) -> dict[str, str]:
    """stem → 馬場種別。**障害の判定は名前ではなくここで行う**
    （コーパスの障害330本のうち45本は名前に「障害」が入らない）。"""
    import csv
    f = Path(path)
    if not f.exists():
        return {}
    return {r["stem"]: (r.get("馬場種別") or "").strip()
            for r in csv.DictReader(open(f, encoding="utf-8-sig"))}

WIDTH = 4
ORDER = ("障害", "新馬", "未勝利", "条件(1-3勝)", "固有名(特別〜G1)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="1-12")
    ap.add_argument("--ratings", default="data/profiles/jra/ratings.json")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--records", default="data/profiles/jra/horse_records.csv")
    ap.add_argument("--sample", type=int, default=0,
                    help="区分ごとにこの本数だけ抜き取る（0=全件）")
    args = ap.parse_args()

    if Path(args.ratings).exists():
        table = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
        sc.load_ratings = lambda *a, **k: table

    wanted = parse_races(args.races)
    kyori_by = load_race_info(args.race_info)
    surface_by = load_surface(args.race_info)
    records = _load_horse_records(args.records)
    d = Path(args.dir)

    stems = defaultdict(list)
    for stem in sorted({p.name.replace("_結果.csv", "") for p in d.glob("*_結果.csv")}):
        rn = race_number(stem)
        if rn is None or rn not in wanted:
            continue
        stems[race_class(stem, surface_by.get(stem))].append(stem)

    if args.sample:
        rng = random.Random(20260922)
        for k, v in stems.items():
            if len(v) > args.sample:
                stems[k] = rng.sample(v, args.sample)

    rows = []
    for cls in ORDER:
        pairs = {k: [] for k in ("ワイド", "馬連")}
        spread, mochi_rate, used = [], [], 0
        for stem in stems.get(cls, []):
            race = load_race(d, stem)
            if race is None:
                continue
            scores = sc.score_race(race["horses"], None, kyori=kyori_by.get(stem),
                                   records=records, as_of=race_date(stem),
                                   venue=race_venue(stem))
            marked = assign_marks(scores, baba="良")
            if len(marked) < WIDTH:
                continue
            used += 1
            vals = [m.score.total_yoi for m in marked]
            spread.append(max(vals) - min(vals))
            n = len(scores)
            mochi_rate.append(sum(1 for s in scores if s.mochi_delta is not None) / n)
            order = [m.score.horse.umaban for m in marked]
            tickets = [frozenset(c) for c in combinations(order[:WIDTH], 2)]
            for kind in pairs:
                pairs[kind].append(settle(kind, tickets, race))
        if not used:
            continue
        row = {"区分": cls, "n": used,
               "点差": statistics.median(spread),
               "持ち時計": statistics.mean(mochi_rate)}
        for kind, ps in pairs.items():
            inv = sum(i for i, _ in ps) or 1
            row[kind] = (sum(1 for _, r in ps if r > 0) / len(ps),
                         sum(r for _, r in ps) / inv)
        rows.append(row)

    print(f"対象 {args.races}R"
          + (f"・区分ごと最大{args.sample}本の抜き取り" if args.sample else "・全件"))
    print(f"\n{'区分':<18}{'n':>6}{'レース内点差':>13}{'持ち時計':>9}"
          f"{'ワイド4頭BOX':>22}{'馬連4頭BOX':>20}")
    for r in rows:
        w, u = r["ワイド"], r["馬連"]
        print(f"{r['区分']:<19}{r['n']:>6}{r['点差']:>12.1f}点{r['持ち時計']:>8.0%}"
              f"{'的中'+format(w[0],'.0%')+' 回収'+format(w[1],'.0%'):>22}"
              f"{'的中'+format(u[0],'.0%')+' 回収'+format(u[1],'.0%'):>20}")


if __name__ == "__main__":
    main()
