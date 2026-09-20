#!/usr/bin/env python3
"""枠順補正のための「過去データCSV」を作る方法の検討（2026-09-20）。

## 背景
`correction_wakuban`（keiba/scoring.py）は `HistoryRecord`（同一レース名の
過去10年分・`data/サンプルステークス_過去10年.csv` のような手入力CSV）を
要求する設計で、**日々の自動予想パイプライン（cmd_text）はこれを一度も
渡していない**。延べ4,016頭の実測で発火率0%（CLAUDE.md
「戦績の既定が薄いファイルを指していて…」の節）。

同じ「同一レース名の過去実施分」を集めるのは非現実的（そのレースが
何回開催されたかに依存し、多くの特別戦は年1回しかない）。そこで
`keiba/courses.py`（コース適性を「場」ではなく「特性」で束ねた前例）・
`scripts/ame_uchi.py`（中山の道悪×内枠）と同じやり方で、
**場×芝ダ×距離帯**に束ねた枠番バイアスを手元のコーパスから作れるか検証する。

## 測り方（CLAUDE.mdの主指標に合わせる）
枠番は発走前に分かる。リフトは**同一人気帯内**で取る
（対照 = 同じ(場×芝ダ×距離帯×人気帯)の全馬複勝率）。

`ame_uchi.py` は馬場（良/稍重以上）で条件を割ったが、ここでは**馬場を
問わない基礎バイアス**（過去10年枠別複勝率の代用）を見る。3期間
（2024/2025/2026）で符号が一致するかを見る。

    python3 scripts/waku_table.py --races 1-12
    python3 scripts/waku_table.py --races 1-12 --min-field 12
"""
from __future__ import annotations

import argparse
import collections
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import power
from keiba.racefiles import DEFAULT_RACES, VENUE_NO_RE, result_files
from keiba.sanko import distance_band, waku_band

BANDS = [("1-3番人気", 1, 3), ("4-5番人気", 4, 5),
         ("6-9番人気", 6, 9), ("10番人気以下", 10, 99)]
WAKU = [("内枠(1-2)", (1, 2)), ("外枠(7-8)", (7, 8))]


def ninki_band(ninki: int) -> str | None:
    for name, lo, hi in BANDS:
        if lo <= ninki <= hi:
            return name
    return None


def load(d: Path, races: str, info: dict, min_field: int) -> list[dict]:
    out = []
    for path in result_files(d, races=races):
        m = VENUE_NO_RE.search(path.name)
        if not m:
            continue
        venue = m.group(1)
        stem = path.name.replace("_結果.csv", "")
        ri = info.get(stem)
        if not ri or not ri.get("距離") or not ri.get("馬場種別"):
            continue
        try:
            kyori = int(ri["距離"])
        except (TypeError, ValueError):
            continue
        rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
        if len(rows) < min_field:
            continue
        for r in rows:
            try:
                chaku = int(r["着順"])
                waku = int(r["枠番"])
                ninki = int(r["人気"])
            except (ValueError, KeyError, TypeError):
                continue
            nb = ninki_band(ninki)
            if not nb or not 1 <= waku <= 8:
                continue
            out.append({
                "venue": venue, "shu": ri["馬場種別"][:1], "kyori": kyori,
                "band": distance_band(kyori), "nb": nb, "waku": waku,
                "chaku": chaku, "year": stem[:4], "stem": stem,
            })
    return out


def load_race_info(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    for row in csv.DictReader(open(path, encoding="utf-8-sig")):
        out[row["stem"]] = row
    return out


def cell_lift(rows: list[dict], waku_set) -> power.Verdict | None:
    """**人気帯を統制しない**粗い版（一次スクリーニングのみ）。"""
    if len(rows) < 200:
        return None
    sub = [r for r in rows if r["waku"] in waku_set]
    if len(sub) < 60:
        return None
    hc = sum(1 for r in rows if r["chaku"] <= 3)
    h = sum(1 for r in sub if r["chaku"] <= 3)
    return power.judge("", h, len(sub), hc, len(rows))


def stratified_lift(rows: list[dict], waku_set) -> tuple[float, float, int, int] | None:
    """**人気帯ごとに対照を取り、プールする**（Mantel-Haenszel型）。

    ame_uchi.py の `lift()` は band(人気帯) を「読めない行の除外」にしか
    使っておらず、docstring の「対照=同じ人気帯の全馬」を実装していない
    （枠は抽選で決まるため交絡は小さいはずだが、それでも統制した値を
    見ておく）。ここでは人気帯ごとに(検証群の的中, 対照群の的中)を集計し、
    足し合わせてから比率にする＝人気帯構成の違いを取り除く。
    """
    sub_h = sub_n = ctl_h = ctl_n = 0
    for nb, _, _ in BANDS:
        cell = [r for r in rows if r["nb"] == nb]
        if len(cell) < 40:
            continue
        s = [r for r in cell if r["waku"] in waku_set]
        if not s:
            continue
        sub_h += sum(1 for r in s if r["chaku"] <= 3)
        sub_n += len(s)
        ctl_h += sum(1 for r in cell if r["chaku"] <= 3)
        ctl_n += len(cell)
    if sub_n < 60 or ctl_n < 200:
        return None
    return sub_h / sub_n, ctl_h / ctl_n, sub_n, ctl_n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--min-field", type=int, default=10)
    a = ap.parse_args()

    d = Path(a.dir)
    info = load_race_info(Path(a.race_info))
    rows = load(d, a.races, info, a.min_field)
    print(f"対象 {len(rows):,}出走（{a.races}R・{a.min_field}頭立て以上・"
          f"レース条件が読めるもの、race_info {len(info):,}行）")
    years = collections.Counter(r["year"] for r in rows)
    print("年ごと: " + " ".join(f"{k}={v:,}" for k, v in sorted(years.items())))

    venues = sorted({r["venue"] for r in rows})
    print(f"\n{'区分':<28}{'n':>7}{'複勝率':>8}{'帯全体':>8}"
          f"{'リフト':>8}{'要る差':>8}  判定   2024/2025/2026")
    hits = []
    for venue in venues:
        for shu in ("芝", "ダ"):
            cell_all = [r for r in rows if r["venue"] == venue and r["shu"] == shu]
            if len(cell_all) < 200:
                continue
            for wl, ws in WAKU:
                v = cell_lift(cell_all, ws)
                if not v:
                    continue
                per = []
                for y in ("2024", "2025", "2026"):
                    g = cell_lift([r for r in cell_all if r["year"] == y], ws)
                    per.append(f"{g.diff * 100:+.1f}" if g else "—")
                label = f"{venue}・{shu}・{wl}"
                print(f"{label:<28}{v.n:>7,}{v.rate:>8.1%}{v.p_control:>8.1%}"
                      f"{v.diff * 100:>+7.1f}p{v.mdd * 100:>7.1f}p"
                      f"  {v.code}   {'/'.join(per)}")
                if v.code == "差あり":
                    signs = [g for g in per if g != "—"]
                    agree = len(signs) >= 2 and all(
                        (float(s) > 0) == (v.diff > 0) for s in signs)
                    hits.append((label, v, agree))

    print(f"\n■ 「差あり」だった区分（{len(hits)}件）のうち、"
          f"符号が他の年でも一致するもの")
    for label, v, agree in hits:
        mark = "○ 再現" if agree else "× 年をまたぐと崩れる"
        print(f"  {label:<28}{v.diff * 100:+.1f}p  {mark}")

    print(f"\n※ 場×芝ダの組み合わせは最大 {len(venues) * 2 * 2}セル"
          "（10場×2芝ダ×内外）を同時に見ている。多重比較に注意。")

    print(f"\n■ 人気帯で統制した版（Mantel-Haenszel型プール）— 抽選なので"
          "交絡は薄いはずだが確認")
    print(f"{'区分':<28}{'n':>7}{'複勝率':>8}{'対照':>8}{'差':>8}  判定(粗)")
    reproduced2 = []
    for label, v, agree in hits:
        if not agree:
            continue
        venue, shu, wl = label.split("・")
        ws = dict(WAKU)[wl]
        cell_all = [r for r in rows if r["venue"] == venue and r["shu"] == shu]
        got = stratified_lift(cell_all, ws)
        if not got:
            print(f"{label:<28}  母数不足（統制後）")
            continue
        rate, ctl, n, nc = got
        vv = power.judge("", int(round(rate * n)), n, int(round(ctl * nc)), nc)
        print(f"{label:<28}{n:>7,}{rate:>8.1%}{ctl:>8.1%}"
              f"{(rate - ctl) * 100:>+7.1f}p  {vv.code}"
              f"（粗い版{v.diff * 100:+.1f}p）")
        if vv.code == "差あり" and (rate - ctl > 0) == (v.diff > 0):
            reproduced2.append(label)

    print(f"\n■ 粗い版で3期間再現 かつ 人気帯統制後も向きが一致・差あり: "
          f"{len(reproduced2)}件")
    for label in reproduced2:
        print(f"  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
