#!/usr/bin/env python3
"""雨の中山で内枠は有利か（本人の仮説・2026-09-17）。

    python3 scripts/ame_uchi.py --races 1-12
    python3 scripts/ame_uchi.py --races 1-12 --venue 中山 --horse レガレイラ

## 仮説
「中山競馬場であれば配水管が整備されているので、雨でも内が有利になる」
（本人の言葉）。中山は排水設備の更新が進んでおり、渋っても内が荒れにくい
＝雨でも内枠の優位が残る、という読み。

## 測り方（CLAUDE.mdの主指標に合わせる）
枠番は**発走前に分かる**（仕分け条件1を満たす）。頭数に関わらず1-8で
固定なので、内(1-2)・中(3-6)・外(7-8)の3帯に分ける。

リフトは**同一人気帯内**で取る。内枠に人気馬が偏る／少頭数で外枠の頭数が
少ないといった交絡を、価格を固定することで抑える:

    対照   = その(場 × 芝ダ × 馬場 × 人気帯)の全馬の複勝率
    検証群 = 同じ区分のうち内枠(1-2)だけ

**「雨で内が有利」は、良馬場との差として出なければ意味がない。** 内枠が
常に有利なら、それは雨の話ではないため。だから 良 と 稍重以上 の両方で
リフトを出し、その差（雨−良）を見る。さらに他場を対照に置く。

頭数が少ないと枠帯の意味が薄れる（8頭以下は枠と馬番が1:1）ので
`--min-field` で下限を置く。既定12頭。
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

BANDS = [("1-3番人気", 1, 3), ("4-5番人気", 4, 5),
         ("6-9番人気", 6, 9), ("10番人気以下", 10, 99)]
WAKU = [("内枠(1-2)", (1, 2)), ("中枠(3-6)", (3, 4, 5, 6)), ("外枠(7-8)", (7, 8))]
MIN_CELL = 60
MIN_CONTROL = 200
# 小回り4場。中山だけが特別なのかを見るための対照
KOMAWARI = ("福島", "小倉", "札幌", "函館")


def band(ninki: int) -> str | None:
    for name, lo, hi in BANDS:
        if lo <= ninki <= hi:
            return name
    return None


def load(d: Path, races: str, info: dict, min_field: int) -> list[dict]:
    out = []
    for path in result_files(d, races=races):
        name = path.name
        m = VENUE_NO_RE.search(name)
        if not m:
            continue
        venue = m.group(1)
        stem = name.replace("_結果.csv", "")
        ri = info.get(stem)
        if not ri:
            continue
        baba = ri["馬場"]
        rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
        if len(rows) < min_field:
            continue
        for r in rows:
            try:
                chaku = int(r["着順"])
                waku = int(r["枠番"])
                ninki = int(r["人気"])
            except (ValueError, KeyError, TypeError):
                continue          # 中止・除外・オッズ欠け。推測しない
            b = band(ninki)
            if not b or not 1 <= waku <= 8:
                continue
            out.append({"venue": venue, "shu": ri["馬場種別"], "baba": baba,
                        "kyori": ri["距離"],
                        "wet": baba != "良", "band": b, "waku": waku,
                        "chaku": chaku, "year": stem[:4], "stem": stem,
                        "name": r.get("馬名", ""), "field": len(rows)})
    return out


def lift(rows: list[dict], waku_set) -> tuple[power.Verdict, float] | None:
    """その区分の中で、枠帯の複勝率が帯全体からどれだけ離れるか。"""
    if len(rows) < MIN_CONTROL:
        return None
    sub = [r for r in rows if r["waku"] in waku_set]
    if len(sub) < MIN_CELL:
        return None
    hc = sum(1 for r in rows if r["chaku"] <= 3)
    h = sum(1 for r in sub if r["chaku"] <= 3)
    v = power.judge("", h, len(sub), hc, len(rows))
    return v, hc / len(rows)


def section(title: str, rows: list[dict], waku_label: str, waku_set) -> None:
    print(f"\n■ {title}")
    print(f"  {'区分':<22}{'n':>6}{'複勝率':>8}{'帯全体':>8}"
          f"{'リフト':>8}{'要る差':>8}  判定   2025 / 2026")
    for shu in ("芝", "ダ"):
        for wet, wl in ((False, "良"), (True, "稍重以上")):
            cell = [r for r in rows if r["shu"] == shu and r["wet"] == wet]
            got = lift(cell, waku_set)
            if not got:
                n = len([r for r in cell if r["waku"] in waku_set])
                print(f"  {shu}・{wl:<18}{n:>6}  母数不足")
                continue
            v, base = got
            per = []
            for y in ("2025", "2026"):
                g = lift([r for r in cell if r["year"] == y], waku_set)
                per.append(f"{g[0].diff * 100:+.1f}p" if g else "—")
            print(f"  {shu}・{wl:<18}{v.n:>6}{v.rate:>8.1%}{base:>8.1%}"
                  f"{v.diff * 100:>+7.1f}p{v.mdd * 100:>7.1f}p"
                  f"  {v.code}  {per[0]:>7} / {per[1]:>7}")


def wet_minus_dry(rows: list[dict], waku_set) -> None:
    """雨のリフト − 良のリフト。仮説が言っているのはこの差である。"""
    print(f"\n  ▼ 雨−良（この差が正なら「雨でこそ内」）")
    for shu in ("芝", "ダ"):
        a = lift([r for r in rows if r["shu"] == shu and r["wet"]], waku_set)
        b = lift([r for r in rows if r["shu"] == shu and not r["wet"]], waku_set)
        if not a or not b:
            print(f"    {shu}: 母数不足")
            continue
        d = (a[0].diff - b[0].diff) * 100
        print(f"    {shu}: 雨{a[0].diff * 100:+.1f}p − 良{b[0].diff * 100:+.1f}p"
              f" = {d:+.1f}p   （雨n={a[0].n:,} 良n={b[0].n:,}"
              f" 雨の要る差{a[0].mdd * 100:.1f}p）")



def dose(rows: list[dict], venue: str) -> None:
    """馬場の重さごと（用量反応）。排水が効くなら重くなっても内が落ちない。"""
    print(f"\n■ {venue} 馬場の重さごと（内枠1-2のリフト）")
    print(f"  {'区分':<20}{'R数':>5}{'n':>6}{'複勝率':>8}{'帯全体':>8}"
          f"{'リフト':>8}{'要る差':>8}  判定")
    for shu in ("芝", "ダ"):
        for bl in ("良", "稍", "重", "不"):
            cell = [r for r in rows if r["shu"] == shu and r["baba"] == bl]
            races = len({r["stem"] for r in cell})
            got = lift(cell, (1, 2))
            if not got:
                n = len([r for r in cell if r["waku"] in (1, 2)])
                print(f"  {shu}・{bl:<17}{races:>5}{n:>6}  母数不足")
                continue
            v, base = got
            print(f"  {shu}・{bl:<17}{races:>5}{v.n:>6}{v.rate:>8.1%}{base:>8.1%}"
                  f"{v.diff * 100:>+7.1f}p{v.mdd * 100:>7.1f}p  {v.code}")


def by_kyori(rows: list[dict], venue: str) -> None:
    """距離ごと。ひとつの距離だけで出ているなら、場の性質とは言えない。"""
    print(f"\n■ {venue} 稍重以上・距離ごと")
    print(f"  {'区分':<20}{'R数':>5}{'内n':>5}{'内リフト':>9}"
          f"{'外n':>5}{'外リフト':>9}{'要る差(内)':>11}")
    for shu in ("芝", "ダ"):
        cell = [r for r in rows if r["shu"] == shu and r["wet"]]
        for lo, hi, kl in ((0, 1400, "〜1400m"), (1401, 1800, "1401-1800m"),
                           (1801, 9999, "1801m〜")):
            sub = [r for r in cell if lo <= int(r["kyori"]) <= hi]
            races = len({r["stem"] for r in sub})
            a, b = lift(sub, (1, 2)), lift(sub, (7, 8))
            av = f"{a[0].diff * 100:+.1f}p" if a else "—"
            bv = f"{b[0].diff * 100:+.1f}p" if b else "—"
            an = a[0].n if a else len([r for r in sub if r["waku"] in (1, 2)])
            bn = b[0].n if b else len([r for r in sub if r["waku"] in (7, 8)])
            md = f"{a[0].mdd * 100:.1f}p" if a else "—"
            print(f"  {shu}・{kl:<17}{races:>5}{an:>5}{av:>9}"
                  f"{bn:>5}{bv:>9}{md:>11}")


def horse(rows_all: list[dict], info: dict, d: Path, name: str) -> None:
    print(f"\n■ {name} の手元の全戦（馬場つき）")
    found = []
    for f in result_files(d, races="1-12"):
        stem = f.name.replace("_結果.csv", "")
        ri = info.get(stem)
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            if r.get("馬名") == name:
                found.append((stem, ri, r))
    if not found:
        print("  手元のコーパスに無い")
        return
    print(f"  {'日付・レース':<40}{'条件':<16}{'枠':>3}{'人気':>5}{'着':>4}")
    for stem, ri, r in found:
        cond = (f"{ri['馬場種別']}{ri['距離']}m {ri['馬場']}" if ri else "条件なし")
        print(f"  {stem:<40}{cond:<16}{r['枠番']:>3}{r['人気']:>5}{r['着順']:>4}")
    wet = [x for x in found if x[1] and x[1]["馬場"] != "良"]
    dry = [x for x in found if x[1] and x[1]["馬場"] == "良"]
    print(f"\n  良 {len(dry)}走 / 稍重以上 {len(wet)}走")
    if wet:
        print("  稍重以上の内訳: "
              + "、".join(f"{x[0].split('_')[1]} {x[2]['枠番']}枠"
                          f"{x[2]['人気']}人気{x[2]['着順']}着" for x in wet))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--venue", default="中山")
    ap.add_argument("--min-field", type=int, default=12)
    ap.add_argument("--horse", action="append", default=[])
    a = ap.parse_args()

    d = Path(a.dir)
    from scripts.build_mochidokei import load_race_info
    info = load_race_info(Path(a.race_info))
    rows = load(d, a.races, info, a.min_field)
    print(f"対象 {len(rows):,}出走（{a.races}R・{a.min_field}頭立て以上・"
          f"レース条件が読めるもの）")
    byv = collections.Counter(r["venue"] for r in rows)
    print("場ごと: " + " ".join(f"{k}{v:,}" for k, v in byv.most_common()))

    here = [r for r in rows if r["venue"] == a.venue]
    other = [r for r in rows if r["venue"] != a.venue]
    koma = [r for r in rows if r["venue"] in KOMAWARI]

    for wl, ws in WAKU:
        if wl == "中枠(3-6)":
            continue
        print(f"\n{'=' * 78}\n{wl}")
        section(f"{a.venue}", here, wl, ws)
        wet_minus_dry(here, ws)
        section(f"対照: 小回り他場（{'・'.join(KOMAWARI)}）", koma, wl, ws)
        wet_minus_dry(koma, ws)
        section(f"対照: {a.venue}以外の全場", other, wl, ws)
        wet_minus_dry(other, ws)

    print(f"\n{'=' * 78}")
    dose(here, a.venue)
    by_kyori(here, a.venue)
    dose(koma, "小回り他場")

    for name in a.horse:
        horse(rows, info, d, name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
