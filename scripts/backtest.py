#!/usr/bin/env python3
"""収集済みレースで買い目戦略を長期シミュレーションする。

「その買い方を全レースで機械的に続けたら、最終的にいくら残るか」を測る。
回収率だけでなく、最大連敗と最大ドローダウン（累積収支の最大下落幅）も出す。
的中率が高くても配当が安ければ資金は減り続けるため、そこを可視化する。

注意: 騎手補正・血統補正は同じレース群から作った ratings.json を使うため、
      既定では補正を切って（--no-ratings 相当の条件で）評価する。補正込みの
      数字は後知恵が入るので参考値として別に表示する。
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.marks import assign_marks
from keiba.models import load_horses
from keiba.scoring import score_race

STAKE = 100
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
    pay = directory / f"{stem}_配当.csv"
    if not (ent.exists() and res.exists() and pay.exists()):
        return None

    rows = [r for r in csv.DictReader(open(res, encoding="utf-8"))
            if (r.get("着順") or "").isdigit()]
    if len(rows) < 5:
        return None
    rows.sort(key=lambda r: int(r["着順"]))
    order = [int(r["馬番"]) for r in rows if (r.get("馬番") or "").isdigit()]
    if len(order) < 3:
        return None

    payouts: dict[str, dict[frozenset, int]] = {}
    for p in csv.DictReader(open(pay, encoding="utf-8")):
        try:
            combo = frozenset(int(x) for x in p["組み合わせ"].split("-"))
            payouts.setdefault(p["券種"], {})[combo] = int(p["配当"])
        except ValueError:
            continue

    horses = load_horses(ent)
    if len(horses) < 5:
        return None
    return {"stem": stem, "horses": horses,
            "top2": frozenset(order[:2]), "top3": frozenset(order[:3]),
            "payouts": payouts}


def settle(kind: str, tickets: list[frozenset], race: dict) -> tuple[int, int]:
    """(投資, 払戻) を返す。"""
    table = race["payouts"].get(kind, {})
    invest = len(tickets) * STAKE
    ret = 0
    for t in tickets:
        if kind == "ワイド":
            hit = t <= race["top3"]
        elif kind == "馬連":
            hit = t == race["top2"]
        else:  # 3連複
            hit = t == race["top3"]
        if hit:
            ret += table.get(t, 0)
    return invest, ret


def strategies(order: list[int], by_ninki: list[int] | None = None
               ) -> dict[str, tuple[str, list[frozenset]]]:
    """印の並び（スコア順）から各戦略の買い目を作る。

    by_ninki を渡すと、比較対象として「人気順で同じ買い方をした場合」も返す。
    スコアが市場評価より優れているかを判定するための対照になる。
    """
    def box(n, size=2):
        return [frozenset(c) for c in combinations(order[:n], size)]

    out = {
        "ワイド 上位3頭BOX(3点)": ("ワイド", box(3)),
        "ワイド 上位4頭BOX(6点)": ("ワイド", box(4)),
        "ワイド 上位5頭BOX(10点)": ("ワイド", box(5)),
        "ワイド ◎軸→3頭流し(3点)": ("ワイド", [frozenset({order[0], x}) for x in order[1:4]]),
        "馬連 上位4頭BOX(6点)": ("馬連", box(4)),
        "馬連 上位5頭BOX(10点)": ("馬連", box(5)),
        "馬連 上位6頭BOX(15点)": ("馬連", box(6)),
        "馬連 ◎軸→5頭流し(5点)": ("馬連", [frozenset({order[0], x}) for x in order[1:6]]),
        "3連複 上位4頭BOX(4点)": ("3連複", box(4, 3)),
        "3連複 上位5頭BOX(10点)": ("3連複", box(5, 3)),
        "3連複 ◎軸→上位4頭(3点)": ("3連複",
            [frozenset({order[0], a, b}) for a, b in combinations(order[1:4], 2)]),
    }
    if by_ninki:
        def nbox(n, size=2):
            return [frozenset(c) for c in combinations(by_ninki[:n], size)]
        out.update({
            "【対照】馬連 人気4頭BOX": ("馬連", nbox(4)),
            "【対照】馬連 人気6頭BOX": ("馬連", nbox(6)),
            "【対照】ワイド 人気4頭BOX": ("ワイド", nbox(4)),
            "【対照】ワイド 人気3頭BOX": ("ワイド", nbox(3)),
            "【対照】3連複 人気4頭BOX": ("3連複", nbox(4, 3)),
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected")
    ap.add_argument("--races", help="対象レース番号で絞る (例: 10-12)")
    ap.add_argument("--ratings",
                    help="使用する補正ファイル。1-9Rだけで作った補正を10-12Rに当てれば"
                         "後知恵の入らない独立検証になる（--with-ratings と併用）")
    ap.add_argument("--with-ratings", action="store_true",
                    help="騎手・血統補正を使う（同一データから作った補正のため後知恵が入る）")
    args = ap.parse_args()

    directory = Path(args.dir)
    stems = sorted({p.name.replace("_結果.csv", "") for p in directory.glob("*_結果.csv")})

    import keiba.scoring as sc
    if not args.with_ratings:
        sc.load_ratings = lambda *a, **k: {}   # 補正を無効化して後知恵を排除
    elif args.ratings:
        import json
        table = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
        sc.load_ratings = lambda *a, **k: table

    results: dict[str, dict] = {}
    used = 0
    wanted = parse_races(args.races) if args.races else None
    for stem in stems:
        if wanted is not None:
            rn = race_number(stem)
            if rn is None or rn not in wanted:
                continue
        race = load_race(directory, stem)
        if race is None:
            continue
        marked = assign_marks(score_race(race["horses"], None), baba="良")
        if len(marked) < 6:
            continue
        used += 1
        order = [m.score.horse.umaban for m in marked]
        ninki = [h.umaban for h in
                 sorted((h for h in race["horses"] if h.ninki), key=lambda h: h.ninki)]

        for label, (kind, tickets) in strategies(order, ninki if len(ninki) >= 6 else None).items():
            inv, ret = settle(kind, tickets, race)
            r = results.setdefault(label, {"inv": 0, "ret": 0, "hit": 0, "n": 0,
                                            "streak": 0, "max_streak": 0,
                                            "cum": 0, "peak": 0, "dd": 0})
            r["inv"] += inv; r["ret"] += ret; r["n"] += 1
            if ret > 0:
                r["hit"] += 1; r["streak"] = 0
            else:
                r["streak"] += 1
                r["max_streak"] = max(r["max_streak"], r["streak"])
            r["cum"] += ret - inv
            r["peak"] = max(r["peak"], r["cum"])
            r["dd"] = min(r["dd"], r["cum"] - r["peak"])

    if not args.with_ratings:
        tag = "騎手・血統補正なし"
    elif args.ratings:
        tag = f"補正={Path(args.ratings).name}（別レース群由来・独立検証）"
    else:
        tag = "騎手・血統補正あり（後知恵注意）"
    band = f"{args.races}R限定・" if args.races else ""
    print("=" * 78)
    print(f" 買い目戦略のシミュレーション（{band}{used}レース・1点100円・{tag}）")
    print("=" * 78)
    print(f"{'戦略':<26}{'的中率':>7}{'回収率':>8}{'収支':>11}{'最大連敗':>8}{'最大DD':>10}")
    for label, r in sorted(results.items(), key=lambda x: -x[1]["ret"] / max(x[1]["inv"], 1)):
        print(f"{label:<26}{r['hit']/r['n']:>7.1%}{r['ret']/r['inv']:>8.0%}"
              f"{r['cum']:>+10,}円{r['max_streak']:>7}連敗{r['dd']:>+9,}円")
    print("\n  最大DD = 累積収支が最も落ち込んだ幅。資金がどれだけ必要かの目安")


if __name__ == "__main__":
    main()
