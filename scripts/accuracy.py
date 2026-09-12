#!/usr/bin/env python3
"""正解率を「市場より正確か」で測る（このシステムの主指標）。

本人の方針（2026-09-11）:
  回収率が100を超えることよりも、正解率を高めることが大事。

ただし正解率だけを最大化すると「1番人気を買う」に収束し、確実に負ける
（中央の1番人気の複勝率62.8%）。正しい目標は**同じ人気帯の中で正解率を
上げる**こと＝市場より正確に当てること。

そこで、人気帯 × スコア順位帯 のクロス集計で「同一価格帯における
スコアのリフト」を測る。人気帯の全体率をベースラインにして、スコアが
上位に置いた馬がそれを上回るかを見る。上回るなら市場に無い情報がある。

    python3 scripts/accuracy.py --dir data/collected_jra \
        --race-info data/profiles/jra/race_info.csv \
        --records data/profiles/jra/horse_records.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keiba.scoring as sc
from keiba.racefiles import DEFAULT_RACES, result_files
from backtest import load_race_info, race_date, race_venue
from keiba.horsedb import load_records
from keiba.models import load_horses

RESULT_RE = re.compile(r"_結果\.csv$")


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


def score_tier(rank: int) -> str:
    if rank <= 3:
        return "スコア上位(1-3位)"
    if rank <= 6:
        return "スコア中位(4-6位)"
    return "スコア下位(7位以下)"


BANDS = ["1-3番人気", "4-5番人気", "6-9番人気", "10番人気以下"]
TIERS = ["スコア上位(1-3位)", "スコア中位(4-6位)", "スコア下位(7位以下)"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--races", default=DEFAULT_RACES,
                    help="対象レース番号（既定9-12）。1-8Rを混ぜると"
                         "収集の進み具合で期間が偏るため既定で絞る")
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--records", default="data/profiles/jra/horse_records.csv")
    ap.add_argument("--year", help="この年のレースだけ見る（独立検証用）")
    ap.add_argument("--ratings", default="data/profiles/jra/ratings.json",
                    help="騎乗数を引く実測ファイル。**明示しないと既定プロファイル"
                         "（地方）を読んでしまい、中央のレースに大井の騎手データを"
                         "当てる事故になる**")
    ap.add_argument("--with-norikae", action="store_true",
                    help="乗り替わり補正を効かせる。騎手の騎乗数だけを渡し、"
                         "複勝率は中立値に潰すので騎手補正・血統補正は働かない。"
                         "騎乗数は結果（着順）ではないため後知恵にならない")
    args = ap.parse_args()

    if args.with_norikae:
        # 一軍判定に必要な騎乗数だけを残す。複勝率は correction_kishu が
        # 0点を返す帯（0.18〜0.28）の値に固定し、騎手補正が混ざらないようにする。
        # こうしないと「乗り替わり補正の効果」と「騎手補正の効果」を
        # 分離できない
        _real = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
        _tier_only = {"騎手": {k: {"n": v.get("n", 0), "複勝率": 0.22,
                                   "勝率": 0.0, "単勝回収率": 0.0}
                              for k, v in _real.get("騎手", {}).items()}}
        sc.load_ratings = lambda *a, **k: _tier_only
    else:
        sc.load_ratings = lambda *a, **k: {}   # 騎手・血統補正は切る（後知恵排除）

    kyori_by = load_race_info(args.race_info)
    recs = load_records(args.records)
    by_name: dict[str, list[dict]] = {}
    for rows in recs.values():
        if rows and rows[0]["馬名"]:
            by_name.setdefault(rows[0]["馬名"], []).extend(rows)
    for rows in by_name.values():
        rows.sort(key=lambda r: r["日付"])

    d = Path(args.dir)
    cells: dict[tuple, dict] = defaultdict(lambda: {"n": 0, "win": 0, "plc": 0})
    band_tot: dict[str, dict] = defaultdict(lambda: {"n": 0, "win": 0, "plc": 0})
    used = 0

    for res in result_files(d, args.races):
        stem = RESULT_RE.sub("", res.name)
        if args.year and not stem.startswith(args.year):
            continue
        ent = res.with_name(f"{stem}_出走馬.csv")
        if not ent.exists():
            continue
        chaku = {}
        for r in csv.DictReader(open(res, encoding="utf-8-sig")):
            if (r.get("着順") or "").isdigit() and (r.get("馬番") or "").isdigit():
                chaku[int(r["馬番"])] = int(r["着順"])
        if len(chaku) < 5:
            continue
        horses = load_horses(ent)
        if len(horses) < 5:
            continue
        scores = sc.score_race(horses, None, kyori=kyori_by.get(stem),
                               records=by_name, as_of=race_date(stem),
                               venue=race_venue(stem))
        ranked = sorted(scores, key=lambda s: s.total_yoi, reverse=True)
        used += 1
        for rank, s in enumerate(ranked, start=1):
            h = s.horse
            c = chaku.get(h.umaban)
            b = band(h.ninki)
            if c is None or b is None:
                continue
            for key in ((b, score_tier(rank)),):
                cells[key]["n"] += 1
                cells[key]["win"] += 1 if c == 1 else 0
                cells[key]["plc"] += 1 if c <= 3 else 0
            band_tot[b]["n"] += 1
            band_tot[b]["win"] += 1 if c == 1 else 0
            band_tot[b]["plc"] += 1 if c <= 3 else 0

    label = f"（{args.year}年のみ）" if args.year else ""
    print(f"{args.dir} {used:,}レースを採点{label}\n")
    print(f"{'人気帯':<14}{'スコア':<20}{'n':>7}{'勝率':>8}{'複勝率':>8}"
          f"{'勝率リフト':>11}{'複勝リフト':>11}")
    for b in BANDS:
        bt = band_tot[b]
        if not bt["n"]:
            continue
        base_w, base_p = bt["win"] / bt["n"], bt["plc"] / bt["n"]
        print(f"{b:<14}{'帯の全体（市場基準）':<20}{bt['n']:>7,}"
              f"{base_w:>8.1%}{base_p:>8.1%}{'—':>11}{'—':>11}")
        for t in TIERS:
            c = cells.get((b, t))
            if not c or c["n"] < 30:
                continue
            w, p = c["win"] / c["n"], c["plc"] / c["n"]
            print(f"{'':<14}{t:<20}{c['n']:>7,}{w:>8.1%}{p:>8.1%}"
                  f"{w - base_w:>+11.1%}{p - base_p:>+11.1%}")
        print()


if __name__ == "__main__":
    main()
