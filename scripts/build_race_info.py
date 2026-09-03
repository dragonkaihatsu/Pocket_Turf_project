#!/usr/bin/env python3
"""キャッシュ済みの結果HTMLから、レースごとの距離・馬場を復元する。

収集済みCSVには距離が入っていないが、距離適性の判定には必要になる。
通信は一切せず data/raw のキャッシュだけを読む。

    python3 scripts/build_race_info.py [--cache-dir data/raw] [--out data/race_info.csv]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.collect import parse_result

FIELDS = ["stem", "race_id", "距離", "馬場種別", "馬場", "天候", "頭数", "レース名"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", default="data/raw")
    ap.add_argument("--out", default="data/race_info.csv")
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
        })

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    have = sum(1 for r in rows if r["距離"])
    print(f"{len(rows)}レース（距離あり{have}／解析不可{skipped}）→ {out}")


if __name__ == "__main__":
    main()
