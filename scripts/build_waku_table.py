#!/usr/bin/env python3
"""枠順補正の実測テーブルを作る（2026-09-20）。

## 背景
`correction_wakuban` は「同一レース名の過去10年データ」（`HistoryRecord`）を
要求する設計で、日々の自動予想パイプラインには一度も渡っていない
（発火率0%・CLAUDE.md「戦績の既定が薄いファイルを指していて…」）。
同一レース名を年ごとに集めるのは特別戦では非現実的なので、
`keiba/courses.py`（コース適性を「場」で束ねた前例）と同じやり方で、
**場×芝ダ**に束ねた枠番バイアスを手元のコーパス（1-12R・2024〜2026）から
作れるか `scripts/waku_table.py` で検証した。

## 検証結果（同一人気帯内リフト・3期間再現・母数十分）
40セル（10場×2芝ダ×内/外）のうち13セルが「差あり」、うち11セルが
2024/2025/2026すべてで符号一致。**人気帯で統制しても数値は変わらない**
（枠は抽選なので交絡が無い）。中山・新潟は複数距離帯でも符号が一致し、
場一発の偶然ではないことを確認した（函館・阪神は距離で割ると母数不足）。

この11セルだけを採用してテーブル化する。**それ以外の場は「差なし」
または「判定不能」であり、0点で扱う**（数字を作らない）。

    python3 scripts/build_waku_table.py --races 1-12 \
        --out data/profiles/jra/waku_stats.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import power, profile
from keiba.racefiles import DEFAULT_RACES
from scripts.waku_table import WAKU, load, load_race_info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--min-field", type=int, default=10)
    ap.add_argument("--out", default="data/profiles/jra/waku_stats.json")
    a = ap.parse_args()

    profile.assert_same_profile(a.dir, a.out)

    d = Path(a.dir)
    info = load_race_info(Path(a.race_info))
    rows = load(d, a.races, info, a.min_field)
    venues = sorted({r["venue"] for r in rows})

    entries = []
    for venue in venues:
        for shu in ("芝", "ダ"):
            cell_all = [r for r in rows if r["venue"] == venue and r["shu"] == shu]
            if len(cell_all) < 200:
                continue
            for wl, ws in WAKU:
                sub_all = [r for r in cell_all if r["waku"] in ws]
                if len(sub_all) < 60:
                    continue
                hc = sum(1 for r in cell_all if r["chaku"] <= 3)
                h = sum(1 for r in sub_all if r["chaku"] <= 3)
                v = power.judge("", h, len(sub_all), hc, len(cell_all))
                per_year = {}
                for y in ("2024", "2025", "2026"):
                    yc = [r for r in cell_all if r["year"] == y]
                    ys = [r for r in yc if r["waku"] in ws]
                    if len(ys) >= 30 and len(yc) >= 100:
                        yh = sum(1 for r in ys if r["chaku"] <= 3)
                        yhc = sum(1 for r in yc if r["chaku"] <= 3)
                        per_year[y] = round(yh / len(ys) - yhc / len(yc), 4)
                signs = [s for s in per_year.values() if s != 0]
                reproduced = (len(signs) >= 2 and
                              all((s > 0) == (v.diff > 0) for s in signs))
                entries.append({
                    "場": venue, "芝ダ": shu, "枠帯": wl,
                    "n": v.n, "複勝率": round(v.rate, 4),
                    "対照複勝率": round(v.p_control, 4),
                    "差": round(v.diff, 4), "要る差": round(v.mdd, 4),
                    "判定": v.code, "年別差": per_year,
                    "再現": reproduced,
                    "採用": v.code == "差あり" and reproduced,
                })

    adopted = sum(1 for e in entries if e["採用"])
    out = {
        "対象": f"{a.races}R・{a.min_field}頭立て以上",
        "レース数": len({r['stem'] for r in rows}),
        "出走数": len(rows),
        "年": sorted({r["year"] for r in rows}),
        "方法": ("場×芝ダの枠帯(内1-2/外7-8)複勝率を、同じ場×芝ダの全馬平均と比較。"
                 "『採用』は 差あり(Wilson区間) かつ 2024/2025/2026のうち"
                 "測れた年すべてで符号一致 のセルのみ。表示・点数化ともこのフラグで絞る"),
        "組み合わせ": entries,
    }

    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(entries)}セル中 採用{adopted}件 → {out_path}")
    for e in entries:
        if e["採用"]:
            print(f"  {e['場']}・{e['芝ダ']}・{e['枠帯']}: {e['差']*100:+.1f}p "
                  f"(n={e['n']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
