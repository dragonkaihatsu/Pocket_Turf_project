#!/usr/bin/env python3
"""「荒れそう／堅そう」を発走前に言えるか（本人の指示・2026-09-15）。

    python3 scripts/arare.py --races 9-12

「見送り判定ではなく、総合的判断で荒れそう・堅そうの判定を出すこと」。
CLAUDE.mdが確認済みなのは**1番人気の単勝オッズだけ**で、頭数もレース内
偏差値の帯も効かなかった。そこで「オッズ以外に足せるものがあるか」を測る。

## 判定の仕方
足せるかどうかは、**1番人気オッズ帯で統制したうえで残るか**で決める。
統制しないと、ただオッズを言い換えただけの指標が「効いた」ように見える
（上がり3F偏差値・相手の質が落ちたのと同じ形）。

  対照   … その帯の全レース
  検証群 … その帯の中で、特徴量が上位／下位の3分の1

## 測る対象（すべて発走前に分かる）
| 特徴 | 意味 |
|---|---|
| 1番人気オッズ | 現行の型判定。基準として置く |
| 上位3人気の支持集中度 | Σ(1/オッズ)。票が割れているか |
| 2番人気÷1番人気 | 1頭が抜けているか |
| 頭数 | 効かないと既出。対照として残す |
| 先行勢の比率 | 逃げ+先行の割合。② の検証で人気の先行馬が崩れると出た |
| スコア1位-2位の差 | 偏差値の差では出なかったが、生スコアは未検証 |
| ◎と1番人気の一致 | ◎の信頼度には効くと既出。レースの荒れに効くかは別 |

## 荒れの定義（2つ並べる。片方だけだと読み違える）
  1番人気が着外 … 市場から見た荒れ
  馬連 上位4頭BOX が外れ … 我々から見た荒れ（推奨の買い方）
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest import load_race, load_race_info, race_date, race_venue, settle
from keiba import power
from keiba.marks import assign_marks
from keiba.racefiles import DEFAULT_RACES, parse_months, result_files
from keiba.scoring import score_race

SENKOU = ("逃げ", "先行")
MIN_CELL = 120


def odds_band(o: float | None) -> str:
    if o is None:
        return "不明"
    return "1倍台" if o < 2.0 else "2倍台" if o < 3.0 else "3倍以上"


def features(race: dict, scores, order: list[int]) -> dict:
    hs = race["horses"]
    by_ninki = sorted((h for h in hs if h.ninki), key=lambda h: h.ninki)
    odds = [h.tansho_odds for h in by_ninki[:3]
            if h.tansho_odds and h.tansho_odds > 0]
    fav = by_ninki[0] if by_ninki else None
    f: dict[str, float | None] = {
        "1番人気オッズ": fav.tansho_odds if fav else None,
        "上位3人気の支持集中度": sum(1 / o for o in odds) if len(odds) == 3 else None,
        "2番人気÷1番人気": (by_ninki[1].tansho_odds / by_ninki[0].tansho_odds
                       if len(by_ninki) > 1 and by_ninki[0].tansho_odds
                       and by_ninki[1].tansho_odds else None),
        "頭数": float(len(hs)),
        "先行勢の比率": (sum(1 for h in hs if (h.kyakushitsu or "") in SENKOU)
                   / len(hs)) if hs else None,
    }
    vals = sorted((s.total_yoi for s in scores), reverse=True)
    f["スコア1位-2位の差"] = vals[0] - vals[1] if len(vals) >= 2 else None
    f["◎が1番人気"] = (1.0 if fav and order and order[0] == fav.umaban else 0.0) \
        if fav else None
    return f


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--months")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--records", default="data/profiles/jra/horse_records.csv",
                    help="馬別戦績CSV。**canonical な名前を渡すこと**"
                         "（コーパスを直接指すとマージが働かず、"
                         "全キャリアの220頭が抜ける）")
    ap.add_argument("--out", help="判定表をJSONで書き出す（予想時に引く）")
    a = ap.parse_args()

    d = Path(a.dir)
    months = parse_months(a.months) if a.months else None
    stems = [Path(f).name.replace("_結果.csv", "")
             for f in result_files(d, a.races, months)]

    import keiba.scoring as sc
    sc.load_ratings = lambda *a_, **k: {}     # 後知恵を排除

    from keiba.horsedb import load_records
    kyori = load_race_info(a.race_info)
    recs = load_records(a.records) if Path(a.records).exists() else None
    if recs:
        by_name: dict[str, list[dict]] = {}
        for rows in recs.values():
            if rows and rows[0]["馬名"]:
                by_name.setdefault(rows[0]["馬名"], []).extend(rows)
        for rows in by_name.values():
            rows.sort(key=lambda r: r["日付"])
        recs = by_name

    rows = []
    for stem in stems:
        race = load_race(d, stem)
        if race is None:
            continue
        scores = score_race(race["horses"], None, kyori=kyori.get(stem),
                            records=recs, as_of=race_date(stem),
                            venue=race_venue(stem))
        marked = assign_marks(scores, baba="良")
        if len(marked) < 6:
            continue
        order = [m.score.horse.umaban for m in marked]
        fav = next((h for h in race["horses"] if h.ninki == 1), None)
        if fav is None or not fav.tansho_odds:
            continue
        tickets = [frozenset(c) for c in combinations(order[:4], 2)]
        _, ret = settle("馬連", tickets, race)
        rows.append({
            "stem": stem, "year": stem[:4],
            "band": odds_band(fav.tansho_odds),
            "荒れ(1番人気が着外)": 0 if fav.umaban in race["top3"] else 1,
            "荒れ(4頭BOXが外れ)": 0 if ret > 0 else 1,
            **features(race, scores, order)})

    print(f"{len(rows):,}レース（{a.races}R）\n")
    keys = ["1番人気オッズ", "上位3人気の支持集中度", "2番人気÷1番人気",
            "頭数", "先行勢の比率", "スコア1位-2位の差", "◎が1番人気"]
    targets = ["荒れ(1番人気が着外)", "荒れ(4頭BOXが外れ)"]

    for tgt in targets:
        base = sum(r[tgt] for r in rows) / len(rows)
        print(f"\n{'=' * 84}\n■ {tgt}  全体 {base:.1%}")
        for band in ("1倍台", "2倍台", "3倍以上"):
            sub = [r for r in rows if r["band"] == band]
            if len(sub) < MIN_CELL:
                continue
            ck = sum(r[tgt] for r in sub)
            print(f"\n  【{band}】n={len(sub):,}  この帯の{tgt}={ck/len(sub):.1%}"
                  f"  ← 現行の型判定はここまで")
            print(f"    {'特徴（帯の中で3分位）':<26}{'n':>5}{'率':>7}"
                  f"{'差':>7}{'要る差':>7}  判定    2025 / 2026")
            for k in keys:
                vals = [r[k] for r in sub if r[k] is not None]
                if len(vals) < MIN_CELL:
                    continue
                if k == "◎が1番人気":
                    groups = [("一致", [r for r in sub if r[k] == 1.0]),
                              ("不一致", [r for r in sub if r[k] == 0.0])]
                else:
                    lo, hi = (statistics.quantiles(vals, n=3)
                              if len(set(vals)) > 2 else (vals[0], vals[0]))
                    groups = [(f"{k} 上位", [r for r in sub
                                           if r[k] is not None and r[k] >= hi]),
                              (f"{k} 下位", [r for r in sub
                                           if r[k] is not None and r[k] <= lo])]
                for label, g in groups:
                    if len(g) < 60:
                        continue
                    h = sum(r[tgt] for r in g)
                    v = power.judge(label, h, len(g), ck, len(sub))
                    per = []
                    for y in ("2025", "2026"):
                        gy = [r for r in g if r["year"] == y]
                        sy = [r for r in sub if r["year"] == y]
                        if len(gy) >= 30 and sy:
                            dy = (sum(r[tgt] for r in gy) / len(gy)
                                  - sum(r[tgt] for r in sy) / len(sy)) * 100
                            per.append(f"{dy:+.1f}p")
                        else:
                            per.append("—")
                    print(f"    {label:<26}{v.n:>5}{v.rate:>7.1%}"
                          f"{v.diff*100:>+6.1f}p{v.mdd*100:>6.1f}p"
                          f"  {v.code:<6}{per[0]:>8} /{per[1]:>8}")
    # ------------------------------------------------------------------
    # 判定表: 1番人気オッズ帯 × 支持集中度の3分位
    # 帯の中でも残った唯一の特徴が支持集中度だったので、この2軸で作る
    KEY = "上位3人気の支持集中度"
    print(f"\n{'=' * 84}\n■ 判定表（1番人気オッズ帯 × {KEY}）")
    print(f"  {'帯':<8}{'集中度':<6}{'n':>6}{'1番人気が着外':>14}{'4頭BOX的中':>12}")
    table: dict[str, dict] = {}
    for band in ("1倍台", "2倍台", "3倍以上"):
        sub = [r for r in rows if r["band"] == band]
        vals = sorted(r[KEY] for r in sub if r[KEY] is not None)
        if len(vals) < MIN_CELL:
            continue
        lo, hi = statistics.quantiles(vals, n=3)
        table[band] = {"下限": round(lo, 4), "上限": round(hi, 4), "n": len(sub),
                       "区分": {}}
        for name, pred in (("低い", lambda v: v <= lo),
                           ("ふつう", lambda v: lo < v < hi),
                           ("高い", lambda v: v >= hi)):
            g = [r for r in sub if r[KEY] is not None and pred(r[KEY])]
            if not g:
                continue
            out_r = sum(r["荒れ(1番人気が着外)"] for r in g) / len(g)
            box = 1 - sum(r["荒れ(4頭BOXが外れ)"] for r in g) / len(g)
            table[band]["区分"][name] = {"n": len(g),
                                         "1番人気が着外": round(out_r, 4),
                                         "4頭BOX的中": round(box, 4)}
            print(f"  {band:<8}{name:<6}{len(g):>6}{out_r:>14.1%}{box:>12.1%}")

    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(
            {"対象": f"中央{a.races}R", "レース数": len(rows),
             "軸": ["1番人気オッズ帯", KEY],
             "注意": "in-sample。1番人気オッズ帯で統制しても残った特徴だけを軸にしている",
             "表": table}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n書き出し: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
