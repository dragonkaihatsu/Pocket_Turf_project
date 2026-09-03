#!/usr/bin/env python3
"""収集済みコーパスから騎手・種牡馬の成績表を作り、data/ratings.json に保存する。

スコアリングの騎手補正・血統補正は、内蔵の固定リストではなくこの実測値を使う。
中央（JRA）の騎手リストは地方競馬では機能しないため、実際に集めた結果から
その競馬場の騎手・種牡馬を評価する。

    python3 scripts/build_ratings.py [--dir data/collected] [--out data/ratings.json]

--races でレース番号を絞れる。1-9Rだけで補正を作り10-12Rで検証すれば、
騎手は全レースに騎乗するため、後知恵の入らない独立した検証ができる。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path


RACE_NO_RE = re.compile(r"_大井(\d{2})R_")


def race_number(stem: str) -> int | None:
    m = RACE_NO_RE.search(stem + "_")
    return int(m.group(1)) if m else None


def parse_races(spec: str) -> set[int]:
    if "-" in spec:
        lo, hi = spec.split("-")
        return set(range(int(lo), int(hi) + 1))
    return {int(x) for x in spec.split(",")}


def build(directory: Path, wanted: set[int] | None = None) -> dict:
    jockey: dict[str, list[int]] = defaultdict(list)
    sire: dict[str, list[int]] = defaultdict(list)
    races = 0

    for res in sorted(directory.glob("*_結果.csv")):
        if wanted is not None:
            rn = race_number(res.name.replace("_結果.csv", ""))
            if rn is None or rn not in wanted:
                continue
        rows = [r for r in csv.DictReader(open(res, encoding="utf-8"))
                if (r.get("着順") or "").isdigit()]
        if not rows:
            continue
        races += 1

        sires: dict[int, str] = {}
        ent = directory / res.name.replace("_結果.csv", "_出走馬.csv")
        if ent.exists():
            for e in csv.DictReader(open(ent, encoding="utf-8")):
                if (e.get("馬番") or "").isdigit():
                    sires[int(e["馬番"])] = (e.get("血統父") or "").strip()

        for r in rows:
            chaku = int(r["着順"])
            if j := (r.get("騎手") or "").strip():
                jockey[j].append(chaku)
            umaban = int(r["馬番"]) if (r.get("馬番") or "").isdigit() else -1
            if s := sires.get(umaban, ""):
                sire[s].append(chaku)

    def summarize(d: dict[str, list[int]]) -> dict:
        return {
            k: {
                "n": len(v),
                "勝率": round(sum(1 for c in v if c == 1) / len(v), 4),
                "複勝率": round(sum(1 for c in v if c <= 3) / len(v), 4),
            }
            for k, v in sorted(d.items()) if v
        }

    return {"レース数": races, "騎手": summarize(jockey), "種牡馬": summarize(sire)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected")
    ap.add_argument("--out", default="data/ratings.json")
    ap.add_argument("--races", help="対象レース番号で絞る (例: 1-9)")
    args = ap.parse_args()

    wanted = parse_races(args.races) if args.races else None
    ratings = build(Path(args.dir), wanted)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ratings, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{ratings['レース数']}レースから作成: 騎手{len(ratings['騎手'])}人 / "
          f"種牡馬{len(ratings['種牡馬'])}頭 → {out}")


if __name__ == "__main__":
    main()
