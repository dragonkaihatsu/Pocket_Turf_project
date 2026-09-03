#!/usr/bin/env python3
"""スコア順位 → 実際の勝率・複勝率 の対応表を収集済みレースから作る。

CLAUDE.md が求める「1着期待度%」「着内期待度%」の裏付けデータ。
スコアは順序尺度でしかないので、確率に変換するには
「スコア1位の馬が実際に何%勝ったか」を数えるしかない。

注意（必ず読むこと）:
  * これは in-sample の対応表。同じレース群でスコアを付け、同じレース群で
    的中率を数えている。将来のレースで同じ率が出る保証はない。
  * 騎手・血統補正は既定で切る。data/ratings.json は同じレース群から
    作られており、有効にすると後知恵が二重に入る。
  * 複勝率は頭数に強く依存する（少頭数ほど上がる）。頭数別の内訳も出す。

使い方:
    python3 scripts/calibrate.py                    # 全レース
    python3 scripts/calibrate.py --races 10-12      # 10-12Rのみ
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.expectation import MAX_RANK, rank_key, wilson
from keiba.models import load_horses
from keiba.scoring import score_race

FIELD_BUCKETS = [("〜9頭", 0, 9), ("10-12頭", 10, 12), ("13頭〜", 13, 99)]
RACE_NO_RE = re.compile(r"_大井(\d{2})R_")


def race_number(stem: str) -> int | None:
    m = RACE_NO_RE.search(stem + "_")
    return int(m.group(1)) if m else None


def parse_races(spec: str) -> set[int]:
    if "-" in spec:
        lo, hi = spec.split("-")
        return set(range(int(lo), int(hi) + 1))
    return {int(x) for x in spec.split(",")}


def load_race(directory: Path, stem: str):
    ent = directory / f"{stem}_出走馬.csv"
    res = directory / f"{stem}_結果.csv"
    if not (ent.exists() and res.exists()):
        return None
    rows = [r for r in csv.DictReader(open(res, encoding="utf-8"))
            if (r.get("着順") or "").isdigit() and (r.get("馬番") or "").isdigit()]
    if len(rows) < 5:
        return None
    rows.sort(key=lambda r: int(r["着順"]))
    order = [int(r["馬番"]) for r in rows]
    horses = load_horses(ent)
    if len(horses) < 5:
        return None
    return {"horses": horses, "winner": order[0], "top3": set(order[:3]),
            "field": len(horses)}


def field_bucket(n: int) -> str:
    for label, lo, hi in FIELD_BUCKETS:
        if lo <= n <= hi:
            return label
    return FIELD_BUCKETS[-1][0]


def tally(counter: dict, key: str, won: bool, placed: bool) -> None:
    c = counter.setdefault(key, {"n": 0, "勝": 0, "複": 0})
    c["n"] += 1
    c["勝"] += int(won)
    c["複"] += int(placed)


def finalize(counter: dict) -> dict:
    out = {}
    for key, c in counter.items():
        n, w, p = c["n"], c["勝"], c["複"]
        out[key] = {
            "n": n, "勝": w, "複": p,
            "勝率": w / n if n else 0.0,
            "複勝率": p / n if n else 0.0,
            "勝率CI": list(wilson(w, n)),
            "複勝率CI": list(wilson(p, n)),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected")
    ap.add_argument("--races", help="対象レース番号 (例: 10-12)")
    ap.add_argument("--out", default="data/calibration.json")
    ap.add_argument("--with-ratings", action="store_true",
                    help="騎手・血統補正を使う（同一データ由来のため後知恵が入る）")
    args = ap.parse_args()

    if not args.with_ratings:
        import keiba.scoring as sc
        sc.load_ratings = lambda *a, **k: {}

    wanted = parse_races(args.races) if args.races else None
    directory = Path(args.dir)
    stems = sorted({p.name.replace("_結果.csv", "") for p in directory.glob("*_結果.csv")})

    by_rank: dict = {}
    by_field: dict = {}
    by_ninki: dict = {}
    used = 0
    for stem in stems:
        if wanted is not None:
            rn = race_number(stem)
            if rn is None or rn not in wanted:
                continue
        race = load_race(directory, stem)
        if race is None:
            continue
        scores = score_race(race["horses"], None)
        ranked = sorted(scores, key=lambda s: s.total_yoi, reverse=True)
        used += 1
        fb = field_bucket(race["field"])
        for i, s in enumerate(ranked, start=1):
            uma = s.horse.umaban
            won = uma == race["winner"]
            placed = uma in race["top3"]
            tally(by_rank, rank_key(i), won, placed)
            if i <= MAX_RANK:
                tally(by_field, f"{fb}/{i}位", won, placed)

        # 対照: 市場評価（人気順）が同じ順位で何%来ているか
        ninki = sorted((h for h in race["horses"] if h.ninki), key=lambda h: h.ninki)
        for i, h in enumerate(ninki, start=1):
            tally(by_ninki, rank_key(i),
                  h.umaban == race["winner"], h.umaban in race["top3"])

    if not used:
        print("対象レースが見つかりませんでした")
        return

    target = f"大井{args.races}R" if args.races else "大井全レース"
    payload = {
        "生成日": date.today().isoformat(),
        "対象": target,
        "レース数": used,
        "補正": "騎手・血統補正あり（後知恵注意）" if args.with_ratings else "騎手・血統補正なし",
        "注意": "同一レース群で作った in-sample の対応表。将来の率を保証しない",
        "順位別": finalize(by_rank),
        "頭数別": finalize(by_field),
        "対照_人気順": finalize(by_ninki),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    print(f" スコア順位別の実測成績（{target} {used}レース・{payload['補正']}）")
    print("=" * 72)
    print(f"{'スコア順位':<10}{'頭数':>7}{'1着':>6}{'勝率':>8}{'95%CI':>16}"
          f"{'着内':>6}{'着内率':>8}{'95%CI':>16}")
    for key in [str(i) for i in range(1, MAX_RANK + 1)] + [f"{MAX_RANK + 1}位以下"]:
        r = payload["順位別"].get(key)
        if not r:
            continue
        label = f"{key}位" if key.isdigit() else key
        wci = f"{r['勝率CI'][0]:.0%}-{r['勝率CI'][1]:.0%}"
        pci = f"{r['複勝率CI'][0]:.0%}-{r['複勝率CI'][1]:.0%}"
        print(f"{label:<10}{r['n']:>7}{r['勝']:>6}{r['勝率']:>8.1%}{wci:>16}"
              f"{r['複']:>6}{r['複勝率']:>8.1%}{pci:>16}")
    print("\n--- 対照: 市場評価（人気順）の同じ集計 ---")
    print(f"{'人気':<10}{'頭数':>7}{'1着':>6}{'勝率':>8}{'着内':>6}{'着内率':>8}")
    for key in [str(i) for i in range(1, MAX_RANK + 1)] + [f"{MAX_RANK + 1}位以下"]:
        r = payload["対照_人気順"].get(key)
        if not r:
            continue
        label = f"{key}番人気" if key.isdigit() else key
        print(f"{label:<10}{r['n']:>7}{r['勝']:>6}{r['勝率']:>8.1%}"
              f"{r['複']:>6}{r['複勝率']:>8.1%}")

    top = payload["順位別"].get("1", {})
    ctl = payload["対照_人気順"].get("1", {})
    if top and ctl:
        print(f"\nスコア1位 勝率{top['勝率']:.1%} / 1番人気 勝率{ctl['勝率']:.1%}"
              f"  → スコアの順位付けは市場に{'勝って' if top['勝率'] > ctl['勝率'] else '負けて'}いる")

    print(f"\n書き出し: {out}")
    print("  ※ in-sample。母数が少ない区分はCIの幅で判断すること")


if __name__ == "__main__":
    main()
