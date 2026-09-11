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


# ファイル名は「日付_場名+レース番号R_レース名_種別.csv」。競馬場名は
# 大井にも東京にも東京競馬場以外にもなるので、場名を決め打ちしない
RACE_NO_RE = re.compile(r"_\D+?(\d{2})R_")


def race_number(stem: str) -> int | None:
    m = RACE_NO_RE.search(stem + "_")
    return int(m.group(1)) if m else None


def parse_races(spec: str) -> set[int]:
    if "-" in spec:
        lo, hi = spec.split("-")
        return set(range(int(lo), int(hi) + 1))
    return {int(x) for x in spec.split(",")}


STAKE = 100


def load_tansho_payouts(path: Path) -> dict[int, int]:
    """単勝配当を 馬番 → 配当円 で返す（勝ち馬以外は0扱いなのでキーに無い）。"""
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("券種") == "単勝":
                try:
                    out[int(row["組み合わせ"])] = int(row["配当"])
                except ValueError:
                    continue
    return out


def build(directory: Path, wanted: set[int] | None = None) -> dict:
    # 値は (着順, 単勝払戻円) のタプル。払戻は勝ち馬以外は0
    jockey: dict[str, list[tuple[int, int]]] = defaultdict(list)
    sire: dict[str, list[tuple[int, int]]] = defaultdict(list)
    kyakushitsu: dict[str, list[tuple[int, int]]] = defaultdict(list)
    races = 0

    for res in sorted(directory.glob("*_結果.csv")):
        if wanted is not None:
            rn = race_number(res.name.replace("_結果.csv", ""))
            if rn is None or rn not in wanted:
                continue
        rows = [r for r in csv.DictReader(open(res, encoding="utf-8-sig"))
                if (r.get("着順") or "").isdigit()]
        if not rows:
            continue
        races += 1

        sires: dict[int, str] = {}
        kyaku: dict[int, str] = {}
        ent = directory / res.name.replace("_結果.csv", "_出走馬.csv")
        if ent.exists():
            for e in csv.DictReader(open(ent, encoding="utf-8-sig")):
                if (e.get("馬番") or "").isdigit():
                    sires[int(e["馬番"])] = (e.get("血統父") or "").strip()
                    kyaku[int(e["馬番"])] = (e.get("脚質") or "").strip()
        payouts = load_tansho_payouts(directory / res.name.replace("_結果.csv", "_配当.csv"))

        for r in rows:
            chaku = int(r["着順"])
            umaban = int(r["馬番"]) if (r.get("馬番") or "").isdigit() else -1
            ret = payouts.get(umaban, 0)
            if j := (r.get("騎手") or "").strip():
                jockey[j].append((chaku, ret))
            if s := sires.get(umaban, ""):
                sire[s].append((chaku, ret))
            if k := kyaku.get(umaban, ""):
                kyakushitsu[k].append((chaku, ret))

    def summarize(d: dict[str, list[tuple[int, int]]]) -> dict:
        return {
            k: {
                "n": len(v),
                "勝率": round(sum(1 for c, _ in v if c == 1) / len(v), 4),
                "複勝率": round(sum(1 for c, _ in v if c <= 3) / len(v), 4),
                "単勝回収率": round(sum(ret for _, ret in v) / (len(v) * STAKE), 4),
            }
            for k, v in sorted(d.items()) if v
        }

    return {"レース数": races, "騎手": summarize(jockey), "種牡馬": summarize(sire),
            "脚質": summarize(kyakushitsu)}


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
          f"種牡馬{len(ratings['種牡馬'])}頭 / 脚質{len(ratings['脚質'])}種 → {out}")
    for k, v in sorted(ratings["脚質"].items(), key=lambda x: -x[1]["複勝率"]):
        print(f"    {k:<6} n={v['n']:>5}  勝率{v['勝率']:.1%}  複勝率{v['複勝率']:.1%}"
              f"  単勝回収率{v['単勝回収率']:.0%}")


if __name__ == "__main__":
    main()
