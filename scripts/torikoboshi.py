#!/usr/bin/env python3
"""取りこぼし（取れたはずを取れなかった分）を2種類に分けて数える。

「着実に制度づくりによる、ルールを決めた方法で、取りに行けば取れたかもしれない
ところをきちんと取りこぼしを減らすことが出来た」（本人の言葉・2026-09-12）。

CLAUDE.mdの設計思想は「恐れるべきは間違えることではなく、期待値の欠損と
取りこぼし」である。ただし**取りこぼしには性質の違う2種類がある**:

  A 構造的な取りこぼし … 点数を絞った代償。1着が印の外から出る、上位4頭BOXの
                        外で決まる。減らすには点数を増やすしかなく、
                        回収率とのトレードオフから逃れられない
  B 事故による取りこぼし … 実装の追随漏れ・データ欠落・設定ミス。
                        **点数を増やさずに減らせる**＝純粋な改善

**制度づくりが減らせるのはBだけである。** このスクリプトはAを実測して
「どこまでが構造的に避けられないのか」を出す。Bは計算ではなく履歴なので
CLAUDE.mdの「取りこぼしは2種類ある」の節に台帳として置いた。

    python3 scripts/torikoboshi.py
    python3 scripts/torikoboshi.py --marks 6   # 印を絞ったときのカバー率
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keiba.scoring as sc
from backtest import load_race_info, race_date, race_venue
from keiba.horsedb import load_records
from keiba.models import load_horses
from keiba.racefiles import DEFAULT_RACES, result_files

RESULT_RE = re.compile(r"_結果\.csv$")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--records", default="data/profiles/jra/horse_records_corpus.csv")
    ap.add_argument("--marks", type=int, default=8, help="印を付ける頭数")
    args = ap.parse_args()

    sc.load_ratings = lambda *a, **k: {}   # 騎手・血統補正は切る（後知恵排除）
    kyori_by = load_race_info(args.race_info)
    recs = load_records(args.records)
    by_name: dict[str, list[dict]] = {}
    for rows in recs.values():
        if rows and rows[0]["馬名"]:
            by_name.setdefault(rows[0]["馬名"], []).extend(rows)
    for rows in by_name.values():
        rows.sort(key=lambda r: r["日付"])

    # 1着・2着・3着のスコア順位を集める
    ranks: dict[int, list[int]] = defaultdict(list)   # 着順 → スコア順位の並び
    pairs: list[tuple[int, int]] = []                 # (1着の順位, 2着の順位)
    fields: list[int] = []
    for res in result_files(Path(args.dir), args.races):
        stem = RESULT_RE.sub("", res.name)
        ent = res.with_name(f"{stem}_出走馬.csv")
        if not ent.exists():
            continue
        chaku = {int(r["馬番"]): int(r["着順"])
                 for r in csv.DictReader(open(res, encoding="utf-8-sig"))
                 if (r.get("着順") or "").isdigit() and (r.get("馬番") or "").isdigit()}
        if len(chaku) < 5:
            continue
        horses = load_horses(ent)
        if len(horses) < 5:
            continue
        scores = sc.score_race(horses, None, kyori=kyori_by.get(stem),
                               records=by_name, as_of=race_date(stem),
                               venue=race_venue(stem))
        order = {s.horse.umaban: i for i, s in
                 enumerate(sorted(scores, key=lambda s: s.total_yoi, reverse=True), 1)}
        got = {c: order.get(u) for u, c in chaku.items() if c <= 3 and u in order}
        if 1 not in got or got[1] is None:
            continue
        fields.append(len(scores))
        for c in (1, 2, 3):
            if got.get(c):
                ranks[c].append(got[c])
        if got.get(2):
            pairs.append((got[1], got[2]))

    n = len(ranks[1])
    print(f"■ A 構造的な取りこぼし（{n:,}レース・平均{sum(fields)/len(fields):.1f}頭立て）")
    print("  点数を絞った代償。減らすには点数を増やすしかない\n")
    print(f"  {'上位n頭':<10}{'1着を含む':>10}{'1-2着を両方含む':>18}{'点数(馬連BOX)':>16}")
    for k in (1, 2, 3, 4, 5, 6, 8, 10):
        win = sum(1 for r in ranks[1] if r <= k) / n
        both = sum(1 for a, b in pairs if a <= k and b <= k) / len(pairs)
        pts = k * (k - 1) // 2
        mark = "  ← 印の外側" if k == args.marks else ""
        print(f"  上位{k:<7}{win * 100:>9.1f}%{both * 100:>17.1f}%{pts:>13}点{mark}")
    print()
    out8 = sum(1 for r in ranks[1] if r > args.marks) / n
    print(f"  **1着が印（上位{args.marks}頭）の外から出たのは {out8 * 100:.1f}%**")
    print(f"  1着の順位の中央値は {sorted(ranks[1])[n // 2]} 位")
    print("  → ここは制度では減らない。点数を増やすか、スコア自体を良くするしかない")
    print()
    print("  印を絞ると、この構造的な取りこぼしがそのまま増える:")
    for k in (6, 8):
        miss = sum(1 for r in ranks[1] if r > k) / n
        print(f"    印{k}頭 → 1着が印外 {miss * 100:.1f}%")
    print("  2026-09-12は `--marks 6` で出したため、8位「注」だった中山12Rの1着が")
    print("  記録上「無印」になった（買い目は上位4頭BOXなので実害は無い）。")
    print("  **制度から外れて手で絞ると、記録の意味が変わる**")
    print()

    print("■ B 事故による取りこぼし（計算ではなく履歴）")
    print("  点数を増やさずに減らせる＝回収率とのトレードオフが無い改善。")
    print("  回収できた分の台帳は CLAUDE.md「取りこぼしは2種類ある」の節に置いた")


if __name__ == "__main__":
    main()
