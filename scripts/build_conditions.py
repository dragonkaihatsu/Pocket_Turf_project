#!/usr/bin/env python3
"""キャッシュ済みHTMLから、レースの条件（ハンデ/定量/別定）とクラスを取り出す。

RaceData02 に「1回 札幌 1日目 サラ系３歳以上 １勝クラス [指] 定量 13頭」の形で
入っている。斤量の決め方（ハンデか否か）と格（重賞かどうか）は、予想の
読みやすさに直結するのに race_info.csv に無かったので足す。

    python3 scripts/build_conditions.py --cache-dir data/raw_jra \
        --race-info data/profiles/jra/race_info.csv
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

KINRYO = ("ハンデ", "別定", "馬齢", "定量")
GRADE_RE = re.compile(r"\((G[123]|Jpn[123]|L)\)")
CLASSES = ("新馬", "未勝利", "１勝クラス", "2勝クラス", "２勝クラス", "3勝クラス",
           "３勝クラス", "オープン", "1勝クラス")


def parse(html: str) -> dict:
    out = {"斤量条件": "", "クラス": "", "格": ""}
    m = re.search(r'<div class="RaceData02"[^>]*>(.*?)</div>', html, re.S)
    if m:
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
        for k in KINRYO:
            if k in text:
                out["斤量条件"] = k
                break
        for c in CLASSES:
            if c in text:
                out["クラス"] = c.replace("１", "1").replace("２", "2").replace("３", "3")
                break
    if t := re.search(r"<title>([^<|]+)", html):
        if g := GRADE_RE.search(t.group(1)):
            out["格"] = g.group(1)
    if not out["格"] and re.search(r'class="[^"]*Icon_GradeType(1|2|3)\b', html):
        out["格"] = "重賞"
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", default="data/raw_jra")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    args = ap.parse_args()

    info_path = Path(args.race_info)
    rows = list(csv.DictReader(open(info_path, encoding="utf-8-sig")))
    cache = Path(args.cache_dir)

    filled = 0
    for r in rows:
        rid = (r.get("race_id") or "").strip()
        p = cache / f"{rid}.html"
        if not (rid and p.exists()):
            r.update({"斤量条件": "", "クラス": "", "格": ""})
            continue
        r.update(parse(p.read_text(encoding="utf-8", errors="ignore")))
        if r["斤量条件"]:
            filled += 1

    cols = list(rows[0].keys())
    # BOM付きUTF-8。WindowsのExcelが文字コードを取り違えないようにする
    with open(info_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    print(f"{len(rows)}レース中 {filled}レースに斤量条件を付与 → {info_path}")
    for key in ("斤量条件", "クラス", "格"):
        c = Counter(r[key] for r in rows if r[key])
        print(f"  {key}: " + " / ".join(f"{k} {v}" for k, v in c.most_common(6)))


if __name__ == "__main__":
    main()
