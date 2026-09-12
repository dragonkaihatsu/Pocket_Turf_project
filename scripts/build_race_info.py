#!/usr/bin/env python3
"""キャッシュ済みの結果HTMLから、レースごとの距離・馬場・等級を復元する。

収集済みCSVには距離が入っていないが、距離適性の判定には必要になる。
通信は一切せず data/raw のキャッシュだけを読む。

## 既存の行を消さない（2026-09-12・重要）

**キャッシュは縮む。** `data/raw` は運用の途中で整理されるため、いま置き換えで
書き出すと既存の行が消える。実際に `data/profiles/jra/race_info.csv` は
1,899行あるのに、キャッシュに残っている結果HTMLは223件しかない。
そのまま実行すれば**1,676行が静かに失われる**。

そこで既定は**マージ**にした。キャッシュから読めた行で上書きし、読めない行は
そのまま残す。置き換えたいときだけ `--replace` を明示する。

## 等級（重賞かどうか）

`parse_result` は `info.grade`（G1/G2/G3/OP/L）を解析しているのに、
これまで書き出していなかった。**等級が無いと「平場で頑張っている騎手 vs
重賞では勝てない騎手」を比べられない**（レース名からは1,899レース中1,374が
固有名で、特別・OP・重賞を分けられない）。`等級` 列を追加した。

    python3 scripts/build_race_info.py --out data/profiles/jra/race_info.csv
    python3 scripts/build_race_info.py --replace   # 既存を捨てて作り直す
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.collect import parse_result

FIELDS = ["stem", "race_id", "距離", "馬場種別", "馬場", "天候", "頭数",
          "レース名", "等級"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", default="data/raw")
    ap.add_argument("--out", default="data/race_info.csv")
    ap.add_argument("--replace", action="store_true",
                    help="既存の行を捨てて作り直す。既定はマージ（キャッシュは縮むため）")
    args = ap.parse_args()

    rows = []
    skipped = 0
    for p in sorted(Path(args.cache_dir).glob("*.html")):
        race_id = p.stem
        if not race_id.isdigit():
            continue
        data = parse_result(p.read_text(encoding="utf-8", errors="replace"), race_id)
        if data is None or not data.info.date:
            skipped += 1
            continue
        i = data.info
        safe = re.sub(r'[\\/:*?"<>|\s]+', "", i.name) or f"{i.race_no:02d}R"
        rows.append({
            "stem": f"{i.date}_{i.venue}{i.race_no:02d}R_{safe}",
            "race_id": race_id,
            "距離": i.kyori or "",
            "馬場種別": i.surface[:1] if i.surface else "",
            "馬場": i.baba, "天候": i.weather,
            "頭数": i.head_count or "", "レース名": i.name,
            "等級": i.grade,
        })

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    merged: dict[str, dict] = {}
    kept = 0
    if out.exists() and not args.replace:
        # **既存を残す**。キャッシュから消えたレースの行を失わないため
        with open(out, encoding="utf-8-sig", newline="") as f:
            for old in csv.DictReader(f):
                merged[old.get("race_id") or old.get("stem", "")] = {
                    k: old.get(k, "") for k in FIELDS}
        kept = len(merged)
    for r in rows:
        merged[r["race_id"]] = r

    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(merged.values())
    have = sum(1 for r in merged.values() if r["距離"])
    grade = sum(1 for r in merged.values() if r["等級"])
    mode = "置き換え" if args.replace else f"マージ（既存{kept:,}行を保持）"
    print(f"キャッシュから{len(rows)}レース読めた（解析不可{skipped}）")
    print(f"{mode} → 合計{len(merged):,}行（距離あり{have:,}／等級あり{grade:,}）→ {out}")
    if not args.replace and kept and len(rows) < kept * 0.5:
        print(f"※ キャッシュ({len(rows)})が既存({kept:,})より大幅に少ない。"
              "--replace を付けると既存が消えるので注意")


if __name__ == "__main__":
    main()
