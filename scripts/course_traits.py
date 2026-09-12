#!/usr/bin/env python3
"""コース適性を「場」ではなく「特性」で測ると母数と判別力がどう変わるか。

コース適性15点は全馬中立値のまま死んでいた（CLAUDE.md）。原因は適性を
「その馬が中山を走ったことがあるか」で測ろうとしていたことにある。
9-12Rだけを集めた手元のデータでは、特定1場での実績を持つ馬がほとんどいない。

そこで `keiba/courses.py` の特性表で束ねる。「中山の実績」は中山だけだが
「小回りの実績」は中山・福島・小倉・札幌・函館の5場ぶんが入る。

測るもの:
  1. 母数がどれだけ増えるか（場一致 vs 特性一致で、実績を持つ馬の割合）
  2. **同一人気帯の中で着順を判別できるか**（CLAUDE.mdの主指標）。
     人気帯で統制すれば価格を固定して精度だけを比べられる
  3. 2025年（材料）/2026年（独立検証）で同じ向きに出るか

情報漏れ対策: ある馬のある出走を評価するとき、**その出走より前の日付の
走りだけ**を使う。同じ日の他レースも使わない。

    python3 scripts/course_traits.py --dir data/collected_jra \
        --race-info data/profiles/jra/race_info.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.courses import COURSES, traits
from keiba.racefiles import DEFAULT_RACES, parse_races, race_number as rno

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")
VENUE_RE = re.compile(r"_(\D+?)(\d{2})R_")
AXES = ("小回り", "坂", "芝種", "直線", "回り")


def parse_stem(stem: str) -> tuple[str, str, int] | None:
    d = DATE_RE.match(stem)
    v = VENUE_RE.search(stem + "_")
    if not d or not v or v.group(1) not in COURSES:
        return None
    return d.group(1), v.group(1), int(v.group(2))


def load_race_info(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            out[row["stem"]] = row
    return out


def load_runs(d: Path, info: dict[str, dict], races: range | None) -> list[dict]:
    """全出走を1行ずつ返す（馬名・日付・場・馬場種別・着順・人気）。"""
    runs = []
    for res in sorted(d.glob("*_結果.csv")):
        stem = res.name[: -len("_結果.csv")]
        parsed = parse_stem(stem)
        if parsed is None:
            continue
        date, venue, rn = parsed
        if races is not None and rn not in races:
            continue
        surface = (info.get(stem, {}) or {}).get("馬場種別") or None
        with open(res, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                chaku, ninki = row.get("着順"), row.get("人気")
                name = (row.get("馬名") or "").strip()
                if not name or not chaku or not chaku.isdigit():
                    continue
                runs.append({
                    "馬名": name, "日付": date, "場": venue, "R": rn,
                    "馬場種別": surface, "着順": int(chaku),
                    "人気": int(ninki) if (ninki or "").isdigit() else None,
                    "stem": stem,
                })
    return runs


def ninki_band(n: int | None) -> str | None:
    if n is None:
        return None
    if n <= 3:
        return "1-3番人気"
    if n <= 5:
        return "4-5番人気"
    if n <= 9:
        return "6-9番人気"
    return "10番人気以下"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--races", default=DEFAULT_RACES,
                    help="対象レース番号（既定9-12）。1-8Rの収集が完了したら"
                         "1-12 を渡して1頭あたりの母数を増やして再検証する")
    ap.add_argument("--min-n", type=int, default=2,
                    help="適性を判定するのに必要な、特性一致の過去走数")
    args = ap.parse_args()

    info = load_race_info(Path(args.race_info))
    runs = load_runs(Path(args.dir), info, parse_races(args.races))
    print(f"{args.dir}: {len(runs):,}出走・"
          f"{len({r['馬名'] for r in runs}):,}頭\n")

    by_horse: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        by_horse[r["馬名"]].append(r)
    for lst in by_horse.values():
        lst.sort(key=lambda r: r["日付"])

    # ── 1. 母数の比較 ──
    have_venue = have_axis = {a: 0 for a in AXES}
    have_axis = {a: 0 for a in AXES}
    have_venue = 0
    total = 0
    prior_counts = []
    for name, lst in by_horse.items():
        for i, cur in enumerate(lst):
            prior = lst[:i]
            if not prior:
                continue
            total += 1
            prior_counts.append(len(prior))
            if sum(1 for p in prior if p["場"] == cur["場"]) >= args.min_n:
                have_venue += 1
            cur_t = traits(cur["場"], cur["馬場種別"])
            for axis, val in cur_t.items():
                if axis not in AXES:
                    continue
                m = sum(1 for p in prior
                        if traits(p["場"], p["馬場種別"]).get(axis) == val)
                if m >= args.min_n:
                    have_axis[axis] += 1

    print(f"── 1. 母数: 過去走を持つ{total:,}出走のうち、"
          f"「{args.min_n}走以上の実績」を持つ割合 ──")
    print(f"{'判定の仕方':<22}{'該当':>9}{'割合':>8}")
    print(f"{'同じ競馬場での実績':<22}{have_venue:>9,}{have_venue/total:>8.1%}")
    for axis in AXES:
        print(f"{('同じ「'+axis+'」の実績'):<22}"
              f"{have_axis[axis]:>9,}{have_axis[axis]/total:>8.1%}")
    print(f"\n（過去走数の中央値 {sorted(prior_counts)[len(prior_counts)//2]}走）\n")

    # ── 2. 同一人気帯内のリフト ──
    # **その馬の中での対比**にする: 特性が一致する場での複勝率と、
    # 一致しない場での複勝率を比べ、両側に min_n 走以上ある馬だけを見る。
    #
    # 最初は「特性一致の複勝率 > その馬の全体複勝率」で判定したが、これは
    # 壊れていた。過去走が全部同じ特性の馬（小回りしか走っていない馬など）は
    # 一致側＝全体になるので必ず「同じ」に落ち、比較から外れてしまう。
    # 本来いちばん適性がはっきりしている馬が抜け落ちる形だった。
    #
    # 水準（強い馬か弱い馬か）ではなく対比を測るのは意図的。水準は人気が
    # 既に織り込んでいるため、測れば必ず市場に負ける（CLAUDE.md 偏差値化の失敗）
    for axis in AXES:
        cells: dict[tuple, list[int]] = defaultdict(list)
        band_all: dict[tuple, list[int]] = defaultdict(list)
        for name, lst in by_horse.items():
            for i, cur in enumerate(lst):
                prior = lst[:i]
                band = ninki_band(cur["人気"])
                if not prior or band is None:
                    continue
                year = cur["日付"][:4]
                val = traits(cur["場"], cur["馬場種別"]).get(axis)
                if val is None:
                    continue
                match, other = [], []
                for pr in prior:
                    pv = traits(pr["場"], pr["馬場種別"]).get(axis)
                    if pv is None:
                        continue
                    (match if pv == val else other).append(pr)
                # 両側に実績が無いと「この馬の中で得意か」は判定できない
                if len(match) < args.min_n or len(other) < args.min_n:
                    continue
                band_all[(band, year)].append(cur["着順"])
                mrate = sum(1 for p in match if p["着順"] <= 3) / len(match)
                orate = sum(1 for p in other if p["着順"] <= 3) / len(other)
                tag = "得意" if mrate > orate else "苦手" if mrate < orate else "同じ"
                cells[(band, year, tag)].append(cur["着順"])

        print(f"── 2. 「{axis}」: 一致する場 vs しない場（その馬の中での対比）──")
        print(f"{'人気帯':<12}{'判定':<6}"
              f"{'2025 n':>8}{'複勝率':>8}{'リフト':>8}"
              f"{'2026 n':>8}{'複勝率':>8}{'リフト':>8}")
        for band in ("1-3番人気", "4-5番人気", "6-9番人気", "10番人気以下"):
            for tag in ("得意", "苦手"):
                line = f"{band:<12}{tag:<6}"
                for year in ("2025", "2026"):
                    sel = cells.get((band, year, tag), [])
                    base = band_all.get((band, year), [])
                    if len(sel) < 30 or not base:
                        line += f"{len(sel):>8}{'—':>8}{'—':>8}"
                        continue
                    rate = sum(1 for c in sel if c <= 3) / len(sel)
                    brate = sum(1 for c in base if c <= 3) / len(base)
                    line += (f"{len(sel):>8}{rate:>8.1%}"
                             f"{(rate-brate)*100:>+7.1f}p")
                print(line)
        print()


if __name__ == "__main__":
    main()
