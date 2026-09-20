#!/usr/bin/env python3
"""乗り替わり補正を騎手別（特にルメール）に割り、単勝で見る（2026-09-20）。

## 背景
「ルメールに変わるといい感じ」という感触について、本人から
「確かに効果はあるかもしれないけど、市場はもうマークしている」という
仮説が出た。CLAUDE.mdの既存の乗り替わり検証（`review_hypotheses.py`
`norikae_test.py`）は**一軍騎手をまとめて**扱っており、個別の騎手
（ルメールなど）を抜き出した単勝の検証はまだやっていない。

## 一軍の定義では、ルメールは一軍から漏れている（重要な前提）
`correction_norikae` の一軍判定は「延べ騎乗数の上位16人」（`keiba/scoring.py`
`tier1_min_rides`）。ルメールは1-12R・2024〜2026の延べ騎乗が1,477（22位、
閾値1,078には届く母数ながら上位16人には入らない）:

    → 実際に測ると is_tier1_jockey("ルメー") は **False**
      （現行の ratings.json では n=887・閾値1,078なのでさらに漏れる）

つまり**「ルメールへの乗り替わり」は、現行実装の`correction_norikae`では
そもそも発火しない**。乗り替わり補正が「効いている」としても、それは
ルメールへの乗り替わりの話ではあり得ない（発火条件を満たさないため）。
この前提を先に確認してから、単勝の実測に進む。

**注**: ルメール・Mデムーロは永住の長期免許騎手であり、モレイラのような
短期免許・選抜騎乗の外国人騎手とは立場が違う（本人の指摘・2026-09-20）。
延べ騎乗数が上位16人に届かない理由は未確認（有力馬中心の依頼を受けやすい
立場だからという可能性はあるが検証していない）。

## 測り方
`norikae_test.py` と同じペア作り（前走→今走、馬柱の前走間隔日数で照合）を
1-12R・2024〜2026の全コーパスに広げ、**乗り替わり先の騎手名で個別に**
単勝の勝率・回収率を見る。ルメールを単独グループとして抜き出し、
残りの騎手（延べ騎乗上位・乗り替わり先として登場する頻度が高い騎手）と
並べる。

    python3 scripts/norikae_jockey.py
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.racefiles import result_paths
from keiba import power

STAKE = 100
MIN_HITS = 10  # 的中本数の基準（CLAUDE.md一貫の方針）


def to_ordinal(s: str) -> int:
    y, m, d = (int(x) for x in s.split("-"))
    return date(y, m, d).toordinal()


def build_pairs():
    by_horse: dict[str, list[dict]] = defaultdict(list)
    for f in result_paths("data/collected_jra", races="1-12"):
        stem = Path(f).name
        date_str = stem[:10]
        pay_tan: dict[int, int] = {}
        try:
            for p in csv.DictReader(open(f.replace("_結果.csv", "_配当.csv"),
                                          encoding="utf-8-sig")):
                if p.get("券種") == "単勝":
                    try:
                        pay_tan[int(p["組み合わせ"])] = int(p["配当"])
                    except (ValueError, KeyError):
                        pass
        except FileNotFoundError:
            pass
        interval: dict[str, int | None] = {}
        try:
            for e in csv.DictReader(open(f.replace("_結果.csv", "_出走馬.csv"),
                                          encoding="utf-8-sig")):
                nm = (e.get("馬名") or "").strip()
                iv = e.get("前走間隔日数") or ""
                if nm:
                    interval[nm] = int(iv) if iv.isdigit() else None
        except FileNotFoundError:
            pass
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            nm = (r.get("馬名") or "").strip()
            j = (r.get("騎手") or "").strip()
            ub, nk, ch = r.get("馬番") or "", r.get("人気") or "", r.get("着順") or ""
            if not (nm and j and ub.isdigit() and ch.isdigit()):
                continue
            by_horse[nm].append({
                "date": date_str, "jockey": j, "chaku": int(ch),
                "ninki": int(nk) if nk.isdigit() else None,
                "tan": pay_tan.get(int(ub), 0),
                "interval": interval.get(nm),
            })
    for v in by_horse.values():
        v.sort(key=lambda x: x["date"])

    pairs = []
    for nm, lst in by_horse.items():
        for i in range(1, len(lst)):
            cur = lst[i]
            if cur["interval"] is None:
                continue
            t = to_ordinal(cur["date"]) - cur["interval"]
            for cand in lst[:i][::-1]:
                if abs(to_ordinal(cand["date"]) - t) <= 2:
                    pairs.append((cand, cur))
                    break
    return pairs


def agg(rows: list[dict]) -> dict | None:
    n = len(rows)
    if not n:
        return None
    w = sum(1 for r in rows if r["chaku"] == 1)
    tan_sum = sum(r["tan"] for r in rows)
    return {"n": n, "wins": w, "win": w / n, "tan_roi": tan_sum / (n * STAKE)}


def main() -> int:
    from keiba.scoring import is_tier1_jockey, tier1_min_rides
    print(f"■ 一軍の定義確認（現行 ratings.json ベース）")
    print(f"  tier1_min_rides() = {tier1_min_rides():,}騎乗")
    print(f"  is_tier1_jockey('ルメー') = {is_tier1_jockey('ルメー')}")
    print(f"  → ルメールは現行の一軍判定から漏れており、"
          f"correction_norikaeは乗り替わり先がルメールのケースで発火しない\n")

    pairs = build_pairs()
    print(f"対象: 前走→今走ペア {len(pairs):,}組（1-12R・2024〜2026）\n")

    # 前走二桁 × 乗り替わり（騎手が変わった）だけに絞る
    switched = [(p, c) for p, c in pairs
               if p["chaku"] >= 10 and p["jockey"] != c["jockey"]]
    print(f"前走二桁 × 騎手が変わった: {len(switched):,}組\n")

    # 乗り替わり先の騎手ごとに集計。ルメールを単独グループとして先頭に出す
    by_new_jockey: dict[str, list[dict]] = defaultdict(list)
    for p, c in switched:
        by_new_jockey[c["jockey"]].append(c)

    # 対照: 前走二桁 × 継続騎乗（乗り替わらなかった）
    kept = [c for p, c in pairs if p["chaku"] >= 10 and p["jockey"] == c["jockey"]]
    ctl = agg(kept)
    print(f"対照（前走二桁×継続騎乗）: n={ctl['n']:,} 勝率{ctl['win']:.1%} "
          f"単勝回収{ctl['tan_roi']:.0%}\n")

    print(f"■ 乗り替わり先の騎手別（前走二桁×乗り替わり・全期間）")
    print(f"{'騎手':<10}{'n':>6}{'勝利':>6}{'勝率':>8}{'単勝回収':>10}{'判定':>8}")

    rows = []
    for j, rs in by_new_jockey.items():
        a = agg(rs)
        if a["n"] < 20:
            continue
        rows.append((j, a))
    rows.sort(key=lambda x: -x[1]["n"])

    lemaire_row = None
    for j, a in rows:
        v = power.judge("", a["wins"], a["n"], ctl["wins"], ctl["n"])
        mark = j == "ルメー"
        tag = f"{v.code}" + ("  ※的中10本未満" if a["wins"] < MIN_HITS else "")
        line = (f"{j + ('★' if mark else ''):<10}{a['n']:>6,}{a['wins']:>6}"
                f"{a['win']:>8.1%}{a['tan_roi']:>10.0%}  {tag}")
        print(line)
        if mark:
            lemaire_row = (a, v)

    if lemaire_row is None:
        print("\nルメールへの乗り替わり（前走二桁）はn<20で個別集計に出ていません")
        return 0

    a, v = lemaire_row
    print(f"\n■ ルメールへの乗り替わり（前走二桁）だけを詳しく見る")
    print(f"  n={a['n']:,}（うち的中{a['wins']}本） 勝率{a['win']:.1%} "
          f"単勝回収率{a['tan_roi']:.0%}")
    print(f"  対照（前走二桁×継続騎乗全体）: 勝率{ctl['win']:.1%} "
          f"単勝回収{ctl['tan_roi']:.0%}")
    print(f"  判定: {v.code}（差{v.diff*100:+.1f}pt・要る差{v.mdd*100:.1f}pt・"
          f"必要母数{v.need_n:,}）")

    # 期間で割って再現するか（2024/2025/2026）
    print(f"\n■ 期間で割る（ルメールへの乗り替わり・前走二桁）")
    for y in ("2024", "2025", "2026"):
        yr = [c for c in by_new_jockey.get("ルメー", []) if c["date"].startswith(y)]
        ay = agg(yr)
        if not ay:
            print(f"  {y}: 該当なし")
            continue
        print(f"  {y}: n={ay['n']:>4} 勝利{ay['wins']:>3} "
              f"勝率{ay['win']:>6.1%} 単勝回収{ay['tan_roi']:>5.0%}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
