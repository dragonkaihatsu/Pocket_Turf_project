#!/usr/bin/env python3
"""持ち時計指数の基準タイム表を作り、カバー率を測る。

    python3 scripts/build_mochidokei.py --races 1-12 --target-races 9-12

CLAUDE.mdの手順どおり、**作る前にカバー率と母数を出す**。基準が無い区分は
「基準なし」として数え、推定値を作らない。

`--train-months` を渡すと、その期間だけで基準を作って残りに当てられる
（in-sample の基準で測った数字を、独立検証と混同しないため）。
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import mochidokei as mk
from keiba.racefiles import (DEFAULT_RACES, parse_months, race_month,
                             race_number, race_venue, result_files)

STEM_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_")


def load_race_info(path: Path) -> dict[str, dict]:
    """stem → レース条件。距離・芝ダ・馬場が揃っている行だけ返す。"""
    out = {}
    if not path.exists():
        return out
    for row in csv.DictReader(open(path, encoding="utf-8-sig")):
        if row.get("距離") and row.get("馬場種別") and row.get("馬場"):
            out[row["stem"]] = row
    return out


def stem_date(name: str) -> date | None:
    m = STEM_DATE_RE.match(name)
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def collect_rows(paths: list[Path], info: dict[str, dict]) -> tuple[list[dict], dict]:
    """結果CSVを {場, 馬場種別, 距離, 馬場, 秒, 馬名, 日付, R} の並びにする。"""
    rows: list[dict] = []
    miss = collections.Counter()
    for p in paths:
        stem = p.name.replace("_結果.csv", "")
        ri = info.get(stem)
        if not ri:
            miss["レース条件なし"] += 1
            continue
        ba, d, rno = race_venue(p.name), stem_date(p.name), race_number(p.name)
        if not ba or not d:
            miss["ファイル名が読めない"] += 1
            continue
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            sec = mk.parse_time(r.get("タイム"))
            name = (r.get("馬名") or "").strip()
            if not name:
                continue
            if sec is None:
                miss["タイムなし"] += 1
                continue
            rows.append({"場": ba, "馬場種別": ri["馬場種別"], "距離": ri["距離"],
                         "馬場": ri["馬場"], "秒": sec, "馬名": name,
                         "日付": d, "R": rno, "stem": stem,
                         "人気": r.get("人気", ""), "着順": r.get("着順", "")})
    return rows, miss


def report_coverage(base: mk.BaseTimes, rows: list[dict], target_races: str | None) -> None:
    have = collections.Counter()
    for r in rows:
        key = mk.cell_key(r["場"], r["馬場種別"], r["距離"])
        have["基準あり" if key in base.cells else "基準なし"] += 1
    tot = sum(have.values())
    print(f"\n■ 基準タイム表")
    print(f"  距離区分 {len(base.cells)}（{mk.MIN_CELL_ROWS}行以上）"
          f" / 馬場区分 {len(base.baba)}")
    print(f"  指数が出せる出走 {have['基準あり']:,}/{tot:,} ({have['基準あり']/tot:.1%})")

    # 馬場補正の向き（乾いているほど速いはず）を確認する
    print("\n■ 馬場補正（正=その馬場は時計が速く出る）")
    by_bs = collections.defaultdict(dict)
    for k, v in base.baba.items():
        ba, shu, baba = k.split(mk.SEP)
        by_bs[(ba, shu)][baba] = (v["delta"], v["n"])
    order = mk.BABA_ORDER
    shown = 0
    for (ba, shu), d in sorted(by_bs.items()):
        if len(d) < 3:
            continue
        cells = "  ".join(f"{b} {d[b][0]:+.2f}(n={d[b][1]:,})" for b in order if b in d)
        print(f"  {ba}{shu}: {cells}")
        shown += 1
        if shown >= 8:
            print("  …（以下略）")
            break


def report_window(rows: list[dict], base: mk.BaseTimes, target_races: str) -> None:
    """直近365日で何走ぶんの指数が作れるか（母数の事前見積もり）。"""
    idx_by_horse: dict[str, list[tuple[date, float]]] = collections.defaultdict(list)
    for r in rows:
        v = base.index(r["秒"], r["場"], r["馬場種別"], r["距離"], r["馬場"])
        if v is not None:
            idx_by_horse[r["馬名"]].append((r["日付"], v))
    for v in idx_by_horse.values():
        v.sort()

    tgt = set(int(x) for x in _expand(target_races))
    counts = []
    for r in rows:
        if r["R"] not in tgt:
            continue
        d = r["日付"]
        try:
            lo = date(d.year - 1, d.month, d.day)
        except ValueError:
            lo = date(d.year - 1, d.month, 28)
        counts.append(sum(1 for (dd, _) in idx_by_horse[r["馬名"]] if lo <= dd < d))

    if not counts:
        print("\n■ 直近365日: 対象レースが0件")
        return
    c = collections.Counter(counts)
    n = len(counts)
    print(f"\n■ 直近365日に指数が作れる過去走（対象{target_races}R・{n:,}出走）")
    print("  ※コーパスの最初の1年は前年が無いので、年で分けて読む（下段）")
    for k in range(6):
        print(f"  {k}走: {c[k]:>6,} ({c[k]/n:>5.1%})")
    print(f"  6走以上: {sum(v for k, v in c.items() if k >= 6):>6,} "
          f"({sum(v for k, v in c.items() if k >= 6)/n:.1%})")
    print(f"  中央値 {statistics.median(counts):.0f}走 / "
          f"1走以上 {sum(1 for k in counts if k >= 1)/n:.1%} / "
          f"3走以上 {sum(1 for k in counts if k >= 3)/n:.1%}")

    by_year: dict[int, list[int]] = collections.defaultdict(list)
    for r, k in zip([r for r in rows if r["R"] in tgt], counts):
        by_year[r["日付"].year].append(k)
    print("  年別（前年がコーパスに入っているかで大きく変わる）")
    for y in sorted(by_year):
        v = by_year[y]
        print(f"    {y}年 {len(v):>6,}出走  中央値{statistics.median(v):>3.0f}走"
              f"  1走以上{sum(1 for k in v if k >= 1)/len(v):>6.1%}"
              f"  3走以上{sum(1 for k in v if k >= 3):>6,}=" 
              f"{sum(1 for k in v if k >= 3)/len(v):.1%}")


def _expand(spec: str) -> list[str]:
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += [str(i) for i in range(int(a), int(b) + 1)]
        else:
            out.append(part)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="1-12", help="基準を作る材料のレース帯")
    ap.add_argument("--target-races", default=DEFAULT_RACES, help="カバー率を測る対象")
    ap.add_argument("--months", default=None)
    ap.add_argument("--train-months", default=None,
                    help="基準をこの期間だけで作る（独立検証用）")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--out", default="data/profiles/jra/base_times.json")
    a = ap.parse_args()

    info = load_race_info(Path(a.race_info))
    paths = result_files(a.dir, races=a.races, months=a.months)
    print(f"結果CSV {len(paths):,}本 / レース条件 {len(info):,}本")

    rows, miss = collect_rows(paths, info)
    print(f"延べ出走（タイムあり） {len(rows):,}")
    for k, v in miss.most_common():
        print(f"  除外 {k}: {v:,}")

    train = rows
    if a.train_months:
        keep = parse_months(a.train_months)
        train = [r for r in rows if race_month(r["stem"] + "_結果.csv") in keep]
        print(f"\n基準を作る期間 {a.train_months} → {len(train):,}行")

    base = mk.BaseTimes.build(train)
    report_coverage(base, rows, a.target_races)
    report_window(rows, base, a.target_races)

    base.save(a.out)
    print(f"\n書き出し {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
