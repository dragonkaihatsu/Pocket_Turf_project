#!/usr/bin/env python3
"""秋の「古豪 vs 夏の上がり馬」を勝敗別に数える。

「前走テーブルについてはある程度レース格を重視した馬選びというのもあるが、
古豪の馬VS夏の上がり馬という構図についても勝敗別をつけてほしい。
そこまで重視はしません」（本人の言葉・2026-09-12）。

`ZENSO_TABLE`（前走着順→素点）の作り直しに関わる補足材料である。前走1着に
満点20点を与える現在の形は、**昇級初戦の壁**で実測と合っていない
（前走1着の今走複勝率30.4% < 前走2着40.5%）。「夏に勝ち上がってきた馬」は
まさにその昇級組にあたるので、古豪と正面から比べる。

## 定義（すべて発走前に分かる情報だけ）

    夏の上がり馬 … 4歳以下 かつ その年の6〜9月に1勝以上（今走より前）
    古豪         … 5歳以上 かつ その年の6〜9月に勝ち鞍なし

対象は**秋（9〜12月）のレース**。この構図が成立する時期に限る。

## 主指標は直接対決

群ごとの勝率を比べると、レースの格・頭数・馬場が混ざる。**同じレースに
両方が出ているときどちらが上に来たか**を数えれば、条件の違いは完全に消える。
人気帯内のリフトも併記する（CLAUDE.mdの主指標）。

    python3 scripts/kogo_natsu.py
    python3 scripts/kogo_natsu.py --races 1-12   # 1-8Rの収集後に母数を増やす
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.power import min_detectable_diff, wilson
from keiba.racefiles import (DEFAULT_RACES, parse_races, race_number,
                             result_paths)

DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})_")
AUTUMN = (9, 10, 11, 12)
SUMMER = (6, 7, 8, 9)
BANDS = (("1-3番人気", 1, 3), ("4-5番人気", 4, 5), ("6-9番人気", 6, 9),
         ("10番人気以下", 10, 99), ("（全体）", 1, 99))


def load(directory: str, races: str, months: str | None = None
         ) -> tuple[list[dict], dict[str, list[dict]]]:
    """出走を1行ずつ読み、馬名ごとの履歴も作る。"""
    runs: list[dict] = []
    for path in result_paths(directory, races, months):
        m = DATE_RE.search(Path(path).name)
        if not m:
            continue
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        rows = [r for r in csv.DictReader(open(str(path), encoding="utf-8-sig"))
                if (r.get("着順") or "").isdigit()]
        if len(rows) < 5:
            continue
        for r in rows:
            age = re.search(r"(\d+)$", (r.get("性齢") or "").strip())
            nk = r.get("人気") or ""
            try:
                odds = float(r.get("単勝オッズ"))
            except (TypeError, ValueError):
                odds = None
            runs.append({
                "race": Path(path).name, "date": d, "field": len(rows),
                "R": race_number(Path(path).name),
                "name": (r.get("馬名") or "").strip(),
                "age": int(age.group(1)) if age else None,
                "chaku": int(r["着順"]),
                "ninki": int(nk) if nk.isdigit() else None,
                "odds": odds,
            })
    hist: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        hist[r["name"]].append(r)
    for v in hist.values():
        v.sort(key=lambda x: x["date"])
    return runs, hist


def summer_wins(hist: dict[str, list[dict]], run: dict) -> int:
    """その年の夏（6〜9月）で、今走より前に挙げた勝ち鞍の数。"""
    return sum(1 for x in hist[run["name"]]
               if x["date"] < run["date"] and x["date"].year == run["date"].year
               and x["date"].month in SUMMER and x["chaku"] == 1)


def classify(hist: dict[str, list[dict]], run: dict) -> str | None:
    if run["age"] is None:
        return None
    wins = summer_wins(hist, run)
    if run["age"] <= 4 and wins >= 1:
        return "夏の上がり馬"
    if run["age"] >= 5 and wins == 0:
        return "古豪"
    return None


def rate(rows: list[dict], key) -> tuple[int, int, float]:
    hits = sum(1 for r in rows if key(r))
    return len(rows), hits, (hits / len(rows) if rows else 0.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--target-races", default=None,
                    help="秋の評価対象にするレース番号。既定は --races と同じ。"
                         "夏の勝ち鞍は --races から拾うので、`--races 1-12 "
                         "--target-races 9-12` で「夏の勝ち鞍は平場まで見て、"
                         "秋は9-12Rだけ評価する」になる")
    ap.add_argument("--months", default=None,
                    help="対象月。1-8Rの収集が途中のあいだ `--races 1-12` をそのまま渡すと「1-8Rが入っている数ヶ月」と「9-12Rだけの残り」が混ざるので、効果を測るときは期間を揃える（例 2025-01..2025-03）")
    args = ap.parse_args()

    runs, hist = load(args.dir, args.races, args.months)
    # 夏の勝ち鞍（hist）は全帯から拾い、秋の評価対象だけ帯で絞る。
    # CLAUDE.md「秋の54%が判定できない側に落ちている」の原因は、平場で
    # 勝ち上がった馬＝いちばん典型的な夏の上がり馬を見られないことだった
    target = parse_races(args.target_races or args.races)
    autumn = [r for r in runs if r["date"].month in AUTUMN
              and (target is None or r["R"] in target)]
    for r in autumn:
        r["group"] = classify(hist, r)
    print(f"夏の勝ち鞍は{args.races}R / 秋の評価は"
          f"{args.target_races or args.races}R")
    print(f"収集 延べ{len(runs):,}出走 / 秋(9-12月) {len(autumn):,}出走"
          f" / {len(set(r['race'] for r in autumn)):,}レース")
    years = sorted({r["date"].year for r in autumn})
    print(f"秋の年: {years}（期間再現を測るには秋が2つ以上必要）\n")

    groups = defaultdict(list)
    for r in autumn:
        if r["group"]:
            groups[r["group"]].append(r)
    print("■ 群ごとの成績（レースの格・頭数・馬場が混ざる。参考）")
    print(f"  {'区分':<16}{'n':>7}{'勝率':>8}{'複勝率':>9}{'95%CI':>18}{'平均人気':>10}")
    for g in ("夏の上がり馬", "古豪"):
        v = groups[g]
        if not v:
            continue
        n, w, pw = rate(v, lambda r: r["chaku"] == 1)
        _, k, pp = rate(v, lambda r: r["chaku"] <= 3)
        lo, hi = wilson(k, n)
        nk = [r["ninki"] for r in v if r["ninki"]]
        print(f"  {g:<16}{n:>7,}{pw * 100:>7.1f}%{pp * 100:>8.1f}%"
              f"   [{lo * 100:.1f}%-{hi * 100:.1f}%]{sum(nk) / len(nk):>9.1f}")
    print()

    # --- 主指標: 同じレースでの直接対決
    by_race: dict[str, list[dict]] = defaultdict(list)
    for r in autumn:
        if r["group"]:
            by_race[r["race"]].append(r)
    pairs = wins_r = wins_k = 0
    pair_races = 0
    band_pairs: dict[str, list[int]] = defaultdict(list)
    for rows in by_race.values():
        risers = [r for r in rows if r["group"] == "夏の上がり馬"]
        vets = [r for r in rows if r["group"] == "古豪"]
        if not risers or not vets:
            continue
        pair_races += 1
        for a in risers:
            for b in vets:
                pairs += 1
                if a["chaku"] < b["chaku"]:
                    wins_r += 1
                else:
                    wins_k += 1
                # 同じ人気帯どうしの対決だけを別に数える（価格をそろえる）
                if a["ninki"] and b["ninki"]:
                    for label, lo, hi in BANDS[:-1]:
                        if lo <= a["ninki"] <= hi and lo <= b["ninki"] <= hi:
                            band_pairs[label].append(1 if a["chaku"] < b["chaku"] else 0)
    print(f"■ 直接対決（同じレースに両方が出た {pair_races:,}レース・{pairs:,}組）")
    print("  同じ条件で走った者どうしなので、格・頭数・馬場の違いが消える\n")
    if pairs:
        p = wins_r / pairs
        lo, hi = wilson(wins_r, pairs)
        print(f"  夏の上がり馬が先着: {wins_r:,}組 ({p * 100:.1f}%)"
              f"  [{lo * 100:.1f}%-{hi * 100:.1f}%]")
        print(f"  古豪が先着        : {wins_k:,}組 ({(1 - p) * 100:.1f}%)")
        mdd = min_detectable_diff(pairs, 0.5)
        verdict = ("夏の上がり馬が優勢" if lo > 0.5 else
                   "古豪が優勢" if hi < 0.5 else "互角（五分から区別できない）")
        print(f"  → **{verdict}**（この母数で見える差は五分から{mdd * 100:.1f}pt）")
    print()
    if band_pairs:
        print("  同じ人気帯どうしの対決に限ると（市場評価をそろえる）:")
        print(f"    {'人気帯':<14}{'組数':>7}{'上がり馬の先着率':>18}{'95%CI':>18}")
        for label, _, _ in BANDS[:-1]:
            v = band_pairs.get(label) or []
            if len(v) < 30:
                print(f"    {label:<14}{len(v):>7,}   母数不足")
                continue
            k = sum(v)
            lo, hi = wilson(k, len(v))
            print(f"    {label:<14}{len(v):>7,}{k / len(v) * 100:>17.1f}%"
                  f"   [{lo * 100:.1f}%-{hi * 100:.1f}%]")
    print()

    # **ペアは独立でない**。1頭の古豪が複数の上がり馬と組になるため、
    # 上の信頼区間は実際より狭く出る。レースごとに「各群の最上位人気1頭」だけを
    # 取り出して1レース1組にすると、レース間で独立になる
    print("■ レースごとに1組だけ（各群の最上位人気どうし・ペアを独立にする）")
    one = []
    for rows in by_race.values():
        risers = [r for r in rows if r["group"] == "夏の上がり馬" and r["ninki"]]
        vets = [r for r in rows if r["group"] == "古豪" and r["ninki"]]
        if not risers or not vets:
            continue
        a = min(risers, key=lambda r: r["ninki"])
        b = min(vets, key=lambda r: r["ninki"])
        one.append((a, b))
    if one:
        w = sum(1 for a, b in one if a["chaku"] < b["chaku"])
        lo, hi = wilson(w, len(one))
        mdd = min_detectable_diff(len(one), 0.5)
        code = ("夏の上がり馬が優勢" if lo > 0.5 else
                "古豪が優勢" if hi < 0.5 else "互角（五分から区別できない）")
        print(f"  {len(one):,}レース中 夏の上がり馬が先着 {w:,} ({w / len(one) * 100:.1f}%)"
              f"  [{lo * 100:.1f}%-{hi * 100:.1f}%]")
        print(f"  → **{code}**（見える差は五分から{mdd * 100:.1f}pt）")
        # 人気の近さでそろえる（人気差が小さい組だけ）
        print(f"\n  人気差でそろえると:")
        print(f"    {'人気差':<14}{'R数':>6}{'上がり馬の先着率':>18}{'95%CI':>18}")
        for lab, lo_d, hi_d in (("2以内", 0, 2), ("3-5", 3, 5), ("6以上", 6, 99)):
            v = [(a, b) for a, b in one if lo_d <= abs(a["ninki"] - b["ninki"]) <= hi_d]
            if len(v) < 30:
                print(f"    {lab:<14}{len(v):>6,}   母数不足")
                continue
            k = sum(1 for a, b in v if a["chaku"] < b["chaku"])
            l2, h2 = wilson(k, len(v))
            print(f"    {lab:<14}{len(v):>6,}{k / len(v) * 100:>17.1f}%"
                  f"   [{l2 * 100:.1f}%-{h2 * 100:.1f}%]")
    print()

    print("■ 秋ごとに分けて再現するか")
    print(f"  {'年':<8}{'組数':>7}{'上がり馬の先着率':>18}")
    for y in years:
        v = 0
        w = 0
        for rows in by_race.values():
            if not rows or rows[0]["date"].year != y:
                continue
            risers = [r for r in rows if r["group"] == "夏の上がり馬"]
            vets = [r for r in rows if r["group"] == "古豪"]
            for a in risers:
                for b in vets:
                    v += 1
                    w += 1 if a["chaku"] < b["chaku"] else 0
        if v:
            print(f"  {y:<8}{v:>7,}{w / v * 100:>17.1f}%")


if __name__ == "__main__":
    main()
