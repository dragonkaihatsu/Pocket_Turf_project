#!/usr/bin/env python3
"""「1日2〜3本当たれば勝てる」水準を実測から設計する（本人の指示・2026-09-15）。

    python3 scripts/day_target.py --races 9-12
    python3 scripts/day_target.py --from-dump data/profiles/jra/day_dump.csv

## 平均配当で答えてはいけない
「何本当たれば黒字か」を平均払戻で割ると、**1本の大穴に支配された数字**が出る。
CLAUDE.mdの実戦記録がまさにその形で、週末170%のうち収支のすべてを
セントライト記念の馬連11,560円が作っていた（除くと63%）。

だから2つ並べる:

  中央値ベースの損益分岐 … 1日の投資 ÷ **的中時払戻の中央値**
                          ＝「ふつうの配当なら何本要るか」
  日別収支の実測       … その買い方で実際に黒字だった日の割合と、
                          的中本数ごとの黒字率

**前者が2〜3本に収まり、かつ後者で「2本当たった日」がだいたい黒字**に
なる買い方が、指示された水準を満たす。片方だけでは足りない。

## 日は「開催日まるごと」で数える
1日＝その日に開催された全場の対象レース（中山4＋阪神4＝8レースなど）。
帯で絞る買い方では**買うレースが0本の日**が出るので、その日数も出す
（CLAUDE.md「半分の開催日は1点も買わない」と同じ読み方をするため）。
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest import load_race, load_race_info, race_date, race_venue, settle
from keiba.marks import assign_marks
from keiba.racefiles import DEFAULT_RACES, parse_months, result_files
from keiba.scoring import score_race

STAKE = 100
WIDTHS = (3, 4, 5, 6)
KINDS = ("ワイド", "馬連")
BANDS = ("全体", "1倍台", "2倍台", "3倍以上")
DUMP_COLS = ["date", "stem", "band", "kind", "width", "points", "invest", "ret"]


def odds_band(o: float | None) -> str:
    if o is None:
        return "不明"
    return "1倍台" if o < 2.0 else "2倍台" if o < 3.0 else "3倍以上"


def build_dump(a) -> list[dict]:
    d = Path(a.dir)
    months = parse_months(a.months) if a.months else None
    stems = [Path(f).name.replace("_結果.csv", "")
             for f in result_files(d, a.races, months)]

    import keiba.scoring as sc
    sc.load_ratings = lambda *x, **k: {}       # 後知恵を排除

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

    out = []
    for stem in stems:
        race = load_race(d, stem)
        if race is None:
            continue
        scores = score_race(race["horses"], None, kyori=kyori.get(stem),
                            records=recs, as_of=race_date(stem),
                            venue=race_venue(stem))
        marked = assign_marks(scores, baba="良")
        if len(marked) < max(WIDTHS):
            continue
        order = [m.score.horse.umaban for m in marked]
        fav = next((h for h in race["horses"] if h.ninki == 1), None)
        band = odds_band(fav.tansho_odds if fav else None)
        for kind in KINDS:
            for w in WIDTHS:
                tickets = [frozenset(c) for c in combinations(order[:w], 2)]
                inv, ret = settle(kind, tickets, race)
                out.append({"date": stem[:10], "stem": stem, "band": band,
                            "kind": kind, "width": w, "points": len(tickets),
                            "invest": inv, "ret": ret})
    return out


def analyse(rows: list[dict], want_days: int) -> None:
    for kind in KINDS:
        for w in WIDTHS:
            print(f"\n{'=' * 86}\n■ {kind} 上位{w}頭BOX")
            print(f"  {'買う帯':<8}{'買うR':>6}{'買う日':>6}{'0本の日':>7}"
                  f"{'的中率':>7}{'回収率':>7}{'中央値':>8}"
                  f"{'損益分岐':>9}{'期待的中':>9}{'黒字日':>7}")
            for band in BANDS:
                sel = [r for r in rows
                       if r["kind"] == kind and r["width"] == w
                       and (band == "全体" or r["band"] == band)]
                if len(sel) < 100:
                    continue
                by_day: dict[str, list[dict]] = defaultdict(list)
                for r in sel:
                    by_day[r["date"]].append(r)
                all_days = {r["date"] for r in rows}
                zero = len(all_days) - len(by_day)

                hits = [r["ret"] for r in sel if r["ret"] > 0]
                hit_rate = len(hits) / len(sel)
                inv_tot = sum(r["invest"] for r in sel)
                roi = sum(r["ret"] for r in sel) / inv_tot
                med = statistics.median(hits) if hits else 0
                per_day_r = statistics.median(len(v) for v in by_day.values())
                day_inv = per_day_r * sel[0]["points"] * STAKE
                need = day_inv / med if med else float("inf")
                exp_hits = per_day_r * hit_rate
                plus = sum(1 for v in by_day.values()
                           if sum(x["ret"] for x in v) > sum(x["invest"] for x in v))
                print(f"  {band:<8}{per_day_r:>6.0f}{len(by_day):>6}{zero:>7}"
                      f"{hit_rate:>7.0%}{roi:>7.0%}{med:>8,.0f}"
                      f"{need:>9.1f}{exp_hits:>9.1f}{plus/len(by_day):>7.0%}")

            # 的中本数ごとの黒字率（「2本当たった日は黒字か」への直接の答え）
            sel = [r for r in rows if r["kind"] == kind and r["width"] == w]
            by_day = defaultdict(list)
            for r in sel:
                by_day[r["date"]].append(r)
            tally: dict[int, list[int]] = defaultdict(list)
            for v in by_day.values():
                n = sum(1 for x in v if x["ret"] > 0)
                tally[n].append(1 if sum(x["ret"] for x in v)
                                > sum(x["invest"] for x in v) else 0)
            line = "  全レース買った場合の的中本数別 黒字率: "
            parts = [f"{n}本 {sum(t)/len(t):.0%}({len(t)}日)"
                     for n, t in sorted(tally.items()) if len(t) >= want_days]
            print(line + " / ".join(parts))


def design(rows: list[dict], want: int) -> None:
    """「n本当たれば黒字」を満たす買い方と、その n 本が当たる確率。

    **「2〜3本当たれば勝てる」は買う本数を絞れば必ず作れる。** 1日の投資を
    下げれば損益分岐の本数は下がるからで、そこは設計の自由度でしかない。
    難しいのは**その本数が実際に当たること**なので、両方を並べる。

        買える本数 b = floor(n × 的中時払戻の中央値 ÷ 1レースの投資)
        P(n本以上) = 二項分布 Bin(b, 実測の的中率)

    期待的中 ÷ 損益分岐 は必ず回収率に一致する（b で約分される）ので、
    **本数をどう絞っても長期の期待値は動かない**。動くのは当たった日の
    黒字の出やすさだけである。
    """
    from math import comb
    print(f"\n{'=' * 86}\n■ 設計: 「{want}本当たれば黒字」を満たす買い方")
    print(f"  {'買い方':<22}{'帯':<8}{'1点':>5}{'点数':>5}"
          f"{'中央値':>8}{'買える本数':>11}{'その日に出る':>13}"
          f"{'的中率':>7}{f'P({want}本以上)':>12}")
    best = []
    for kind in KINDS:
        for w in WIDTHS:
            for band in BANDS:
                sel = [r for r in rows if r["kind"] == kind and r["width"] == w
                       and (band == "全体" or r["band"] == band)]
                if len(sel) < 100:
                    continue
                hits = [r["ret"] for r in sel if r["ret"] > 0]
                if not hits:
                    continue
                med = statistics.median(hits)
                pts = sel[0]["points"]
                per_race = pts * STAKE
                b = int(want * med // per_race)
                if b < want:
                    continue           # 1本あたりの投資が重すぎて成立しない
                by_day: dict[str, list] = defaultdict(list)
                for r in sel:
                    by_day[r["date"]].append(r)
                avail = statistics.median(len(v) for v in by_day.values())
                b = min(b, int(avail))
                if b < want:
                    continue           # その帯はそもそも本数が出ない
                p = len(hits) / len(sel)
                pn = sum(comb(b, k) * p ** k * (1 - p) ** (b - k)
                         for k in range(want, b + 1))
                best.append((pn, kind, w, band, pts, med, b, avail, p))
    for pn, kind, w, band, pts, med, b, avail, p in sorted(best, reverse=True):
        print(f"  {kind + ' 上位' + str(w) + '頭BOX':<22}{band:<8}"
              f"{STAKE:>5}{pts:>5}{med:>8,.0f}{b:>11}{avail:>13.0f}"
              f"{p:>7.0%}{pn:>12.0%}")
    if not best:
        print("  該当なし（どの買い方も、その本数を買うだけの配当が出ていない）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--months")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--records", default="data/profiles/jra/horse_records_corpus.csv")
    ap.add_argument("--dump", help="レース×買い方の明細をCSVに書き出す")
    ap.add_argument("--from-dump", help="採点をやり直さず明細から読む")
    ap.add_argument("--min-days", type=int, default=5,
                    help="的中本数別の黒字率を出す最小日数")
    a = ap.parse_args()

    if a.from_dump:
        with open(a.from_dump, encoding="utf-8-sig") as f:
            rows = [{**r, "width": int(r["width"]), "points": int(r["points"]),
                     "invest": int(r["invest"]), "ret": int(r["ret"])}
                    for r in csv.DictReader(f)]
    else:
        rows = build_dump(a)
        if a.dump:
            Path(a.dump).parent.mkdir(parents=True, exist_ok=True)
            with open(a.dump, "w", encoding="utf-8-sig", newline="") as f:
                wtr = csv.DictWriter(f, fieldnames=DUMP_COLS)
                wtr.writeheader()
                wtr.writerows(rows)
            print(f"明細: {a.dump}")

    days = len({r["date"] for r in rows})
    races = len({r["stem"] for r in rows})
    print(f"{races:,}レース / {days}開催日"
          f"（1日あたり {races/days:.1f}レース）")
    print("\n損益分岐 = 1日の投資 ÷ 的中時払戻の**中央値**"
          "（平均だと大穴1本に支配される）")
    print("期待的中 = 1日に買うレース数 × 実測の的中率")
    analyse(rows, a.min_days)
    for n in (2, 3):
        design(rows, n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
