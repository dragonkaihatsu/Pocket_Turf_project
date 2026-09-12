#!/usr/bin/env python3
"""収集済みの結果CSVから、馬別戦績CSVを組み直す（通信ゼロ）。

## なぜ必要か

`horse_records.csv` は netkeiba の馬ページを1頭ずつ取る作りなので
（`keiba.cli horses`、1.5秒間隔）、全頭ぶんは現実的に集まらない。実際
220頭しか入っておらず、そのため:

  * `コース適性15点`・距離適性が、ほぼ全馬で中立値に倒れる
  * `correction_norikae`（前走の騎手が要る）がバックテストで一度も発火しない

一方で**手元の結果CSVそのものが延べ26,000件の戦績**である。1レースぶんの
結果には全出走馬の 着順・騎手・人気・オッズ が入っており、race_info から
距離・馬場種別も引ける。組み直せば通信ゼロで全頭ぶんが作れる。

## 限界を明示しておく

- **カバー範囲は収集した帯（既定9-12R）に限られる**。1-8Rや他年の戦績は
  入らないので、netkeiba から取った全キャリアより短い
- 馬IDが結果CSVに無いため、**馬名をキーにする**。同名馬は区別できない
- したがってこれは全キャリアの代用であって、上位互換ではない。当日の予想は
  `keiba.cli horses` で取った全キャリアを使うほうが厚い

    python3 scripts/build_horse_records.py \
        --dir data/collected_jra --races 9-12 \
        --race-info data/profiles/jra/race_info.csv \
        --out data/profiles/jra/horse_records_corpus.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.racefiles import DEFAULT_RACES, race_number, result_files

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")
VENUE_RE = re.compile(r"_(\D+?)\d{2}R_")

# horse_records.csv と同じ列（keiba/horsedb.py の load_records が読む形）
COLUMNS = ["馬ID", "馬名", "日付", "場", "R", "レース名", "頭数", "枠番",
           "馬番", "オッズ", "人気", "着順", "騎手", "斤量",
           "馬場種別", "距離", "馬場"]


def load_race_info(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            out[row["stem"]] = row
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--out", default="data/profiles/jra/horse_records_corpus.csv")
    args = ap.parse_args()

    info = load_race_info(Path(args.race_info))
    rows_out: list[dict] = []
    races = 0

    for res in result_files(args.dir, args.races):
        stem = res.name[: -len("_結果.csv")]
        d = DATE_RE.match(stem)
        v = VENUE_RE.search(stem + "_")
        if not d or not v:
            continue
        ri = info.get(stem, {})
        rows = [r for r in csv.DictReader(open(res, encoding="utf-8-sig"))
                if (r.get("着順") or "").isdigit()]
        if not rows:
            continue
        races += 1
        for r in rows:
            name = (r.get("馬名") or "").strip()
            if not name:
                continue
            rows_out.append({
                # 馬IDが結果CSVに無いため馬名で代用する（同名馬は区別できない）
                "馬ID": name,
                "馬名": name,
                "日付": d.group(1),
                "場": v.group(1),
                "R": str(race_number(stem) or ""),
                "レース名": ri.get("レース名", ""),
                "頭数": str(len(rows)),
                "枠番": (r.get("枠番") or "").strip(),
                "馬番": (r.get("馬番") or "").strip(),
                "オッズ": (r.get("単勝オッズ") or "").strip(),
                "人気": (r.get("人気") or "").strip(),
                "着順": r["着順"].strip(),
                "騎手": (r.get("騎手") or "").strip(),
                "斤量": (r.get("斤量") or "").strip(),
                "馬場種別": ri.get("馬場種別", ""),
                "距離": ri.get("距離", ""),
                "馬場": ri.get("馬場", ""),
            })

    rows_out.sort(key=lambda r: (r["馬名"], r["日付"]))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # BOM付きUTF-8（CLAUDE.mdの文字コード方針）
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows_out)

    horses = {r["馬名"] for r in rows_out}
    counts = sorted(sum(1 for r in rows_out if r["馬名"] == h) for h in horses)
    print(f"{races:,}レース → {len(rows_out):,}行・{len(horses):,}頭 を {out}")
    if counts:
        print(f"1頭あたりの戦績数: 中央値{counts[len(counts) // 2]}走 / "
              f"最大{counts[-1]}走")


if __name__ == "__main__":
    main()
