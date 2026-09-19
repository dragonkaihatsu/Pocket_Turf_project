#!/usr/bin/env python3
"""基礎能力の「味付け」ごとに、買い目の当たり方と配当の出方を並べる。

2026-09-19 の本人の指示「時々高配当が来るような組み合わせと期待値を
追いかけたい」に対応するための測定。**回収率だけでは答えられない**
（高配当が来るかどうかは、的中時払戻の分布の形の話なので）。

味付けは3つの軸の組み合わせ:

    agari_mix   0.0=持ち時計 / 1.0=上がり3F
    use_records 戦績を使うか（持ち時計・コース適性・距離適性・乗り替わり）
    （前走テーブル・脚質・騎手血統はどの味付けでも同じ）

    python3 scripts/ajitsuke.py
    python3 scripts/ajitsuke.py --year 2026
"""
from __future__ import annotations

import argparse
import statistics
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keiba.scoring as sc
from backtest import (load_race, load_race_info, race_date, race_number,
                      race_venue, settle)
from keiba.cli import _load_horse_records
from keiba.marks import assign_marks
from keiba.racefiles import DEFAULT_RACES, result_files
from keiba.racefiles import parse_races

# (表示名, agari_mix, 戦績を使うか)
FLAVORS = (
    ("現行 持ち時計", 0.0, True),
    ("半々", 0.5, True),
    ("上がり3F", 1.0, True),
    ("馬柱のみ(③)", 1.0, False),
)
WIDTHS = (4, 6)


def summarize(name: str, width: int, rows: list) -> dict:
    """rows は (投資, 払戻, 上位n頭の人気リスト, 1着を含んだか)"""
    inv = sum(r[0] for r in rows)
    ret = sum(r[1] for r in rows)
    hits = [r[1] for r in rows if r[1] > 0]
    ninki = [n for r in rows for n in r[2] if n]
    return {
        "味付け": name, "n": len(rows),
        "的中率": len(hits) / len(rows) if rows else 0.0,
        "回収率": ret / inv if inv else 0.0,
        "払戻中央値": statistics.median(hits) if hits else 0,
        "払戻最大": max(hits) if hits else 0,
        # 「高配当が来る組み合わせか」を直接測る。1万円以上の的中が何本出たか
        "万超": sum(1 for h in hits if h >= 10_000),
        "平均人気": statistics.fmean(ninki) if ninki else 0.0,
        "人気薄率": (sum(1 for n in ninki if n >= 6) / len(ninki)) if ninki else 0.0,
        "1着カバー": sum(1 for r in rows if r[3]) / len(rows) if rows else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--records", default="data/profiles/jra/horse_records.csv")
    ap.add_argument("--year", help="この年のレースだけ見る")
    args = ap.parse_args()

    wanted = parse_races(args.races)
    kyori_by = load_race_info(args.race_info)
    records = _load_horse_records(args.records)
    d = Path(args.dir)
    # 騎手・血統補正は切る（味付け以外の要因を混ぜない。accuracy.py と同じ）
    sc.load_ratings = lambda *a, **k: {}

    series: dict[tuple, list] = {}
    used = 0
    for res in result_files(d, args.races):
        stem = res.name.replace("_結果.csv", "")
        if args.year and not stem.startswith(args.year):
            continue
        rn = race_number(stem)
        if rn is None or rn not in wanted:
            continue
        race = load_race(d, stem)
        if race is None or len(race["horses"]) < max(WIDTHS):
            continue
        used += 1
        win = next((h.umaban for h in race["horses"]
                    if h.umaban in race["top2"]), None)
        for name, mix, use_rec in FLAVORS:
            scores = sc.score_race(race["horses"], None,
                                   kyori=kyori_by.get(stem),
                                   records=records if use_rec else None,
                                   as_of=race_date(stem),
                                   venue=race_venue(stem), agari_mix=mix)
            marked = assign_marks(scores, baba="良")
            order = [m.score.horse.umaban for m in marked]
            ninki_of = {h.umaban: h.ninki for h in race["horses"]}
            for w in WIDTHS:
                tickets = [frozenset(c) for c in combinations(order[:w], 2)]
                i, r = settle("馬連", tickets, race)
                series.setdefault((name, w), []).append(
                    (i, r, [ninki_of.get(u) for u in order[:w]],
                     bool(race["top3"] & set(order[:w]))))

    label = f"（{args.year}年のみ）" if args.year else ""
    print(f"{args.dir} {used:,}レース・馬連BOX{label}\n")
    for w in WIDTHS:
        print(f"■ 上位{w}頭BOX（{len(list(combinations(range(w), 2)))}点）")
        print(f"{'味付け':<14}{'的中率':>7}{'回収率':>7}{'払戻中央値':>11}"
              f"{'払戻最大':>10}{'1万超':>7}{'平均人気':>9}{'6人気以下':>10}"
              f"{'3着内カバー':>12}")
        for name, _, _ in FLAVORS:
            s = summarize(name, w, series[(name, w)])
            print(f"{s['味付け']:<14}{s['的中率']:>7.1%}{s['回収率']:>7.0%}"
                  f"{s['払戻中央値']:>11,.0f}{s['払戻最大']:>10,.0f}"
                  f"{s['万超']:>7}{s['平均人気']:>9.2f}{s['人気薄率']:>10.1%}"
                  f"{s['1着カバー']:>12.1%}")
        print()


if __name__ == "__main__":
    main()
