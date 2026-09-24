#!/usr/bin/env python3
"""「このコースはこの騎手/血統が得意」を、主観を入れずに機械的に判定する。

    python3 scripts/course_jockey_check.py --venue 中山 --venue 阪神

## 書いた理由

過去に「洋芝はGalileo系が浮上する」のような、根拠のない思い込みを
CLAUDE.mdに書いてしまい、あとで独立検証すると支持されず節ごと削除した
（2026-09-21）。同じ失敗を「コースごとの騎手・血統」でも繰り返さないため、
**`keiba/sanko.py` の `jockey_note` が1頭ごとに使っている判定式を、
全騎手×場単位にそのまま機械的に流す**だけのスクリプトにした。
新しい統計手法は作らない。人が「このコースはこの騎手」と選ぶ余地を
挟まないのが目的なので、選ぶ側の判断を増やさない。

## 判定式（`jockey_note` と同一）

    差 = その条件での複勝率 − その騎手の全体複勝率（ratings.json）
    採用 = |差| >= power.min_detectable_diff(n, 全体複勝率)

「得意」と呼べるのは、差がその母数で見える大きさを超えたときだけ。
表示するのは複勝率と母数（単勝回収率は期間をまたいで再現しないので
看板にしない、という既存方針をそのまま踏襲）。

## 血統×コースはここでは測らない

`scripts/ketto_course.py` が既に独立検証まで通した結果「差なし」
（2026-09-18・40セル・母数十分で棄却）。ここで再度測ると、母数を
変えるたびに違う「有力候補」が出てくる多重比較の罠に戻るだけなので、
このスクリプトはその結論を出力するだけに留める。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import power, profile


def load(venue: str):
    prof = profile.for_venue(venue)
    js = json.loads(prof.path("jockey_stats.json").read_text(encoding="utf-8"))
    ratings = json.loads(prof.path("ratings.json").read_text(encoding="utf-8"))
    return js["組み合わせ"], ratings["騎手"]


def check_venue(venue: str) -> None:
    combos, kishu_base = load(venue)
    at_venue = [c for c in combos if c["条件"] == venue or c["条件"].startswith(venue + "/")]
    reliable = [c for c in at_venue if c.get("信頼できる母数")]

    print(f"\n===== {venue} =====")
    print(f"場を含む条件（全粒度）: {len(at_venue)}件")
    print(f"うち信頼できる母数(n≧10かつ勝利10本以上): {len(reliable)}件")

    hits = []
    checked = []
    for c in reliable:
        base_rec = kishu_base.get(c["騎手"])
        if not base_rec:
            continue
        base = base_rec["複勝率"]
        diff = c["複勝率"] - base
        need = power.min_detectable_diff(c["n"], base)
        checked.append((diff, need, c, base))
        if abs(diff) >= need:
            hits.append((diff, need, c, base))

    print(f"差が見える大きさを超えた（＝客観的に「得意/苦手」と言える）: {len(hits)}件")
    if hits:
        hits.sort(key=lambda x: -abs(x[0]))
        for diff, need, c, base in hits:
            tag = "得意" if diff > 0 else "苦手"
            print(f"  {c['騎手']:6s} {c['条件']:24s} {tag} "
                  f"複勝{c['複勝率']:.1%}(全体{base:.1%}・差{diff:+.1%}pt・"
                  f"要る差±{need:.1%}pt) n={c['n']} 勝利{c['勝利数']}")
    else:
        print("  該当なし。" +
              ("参考として、信頼できる母数を持つ騎手の生の値（有意ではない）:" if checked else ""))
        checked.sort(key=lambda x: -abs(x[0]))
        for diff, need, c, base in checked:
            print(f"    {c['騎手']:6s} n={c['n']:4d} 複勝{c['複勝率']:.1%} "
                  f"全体{base:.1%} 差{diff:+.1%}pt（要る差±{need:.1%}pt・判定不能）")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--venue", action="append", required=True,
                     help="測る競馬場（複数回指定可）")
    args = ap.parse_args()
    for v in args.venue:
        check_venue(v)

    print("\n===== 血統×コース =====")
    print("独立検証で「差なし」（scripts/ketto_course.py・2026-09-18・"
          "40セル・母数十分）。ここでは再測定しない。")


if __name__ == "__main__":
    main()
