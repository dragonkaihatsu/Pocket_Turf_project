#!/usr/bin/env python3
"""連闘（前走から中0週）が着順に効くかを測る。

## なぜ間隔日数ではなくラベルで測るのか

CLAUDE.md は間隔を**日数**で切って「中1〜2週(7-14日)は複勝率 −2.1p」と
記録してきた。ところが netkeiba の馬柱は `間隔表記` として
**「連闘」「中1週」…を自分で持っている**（コーパス9,401レースで
連闘3,521件）。日数で切ると順延・変則開催がずれる——2026-09-22の中山は
台風順延なので、連闘馬の間隔が9〜10日と出る（ふつうの連闘は7日）。
**ラベルのほうが開催の数え方に忠実**なので、こちらで測る。

## 判定の形は他の仮説と同じ

同一人気帯内リフト（`keiba/power.py`）＋3年（2024/2025/2026）の符号一致。
対照は「連闘でない同じ人気帯の馬」。前走着順との組み合わせも見る
（乗り替わり・不利痕跡が前走二桁のときだけ効いたのと同じ形を探す）。

    python3 scripts/rento.py --races 1-12
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.power import HEADER, judge
from keiba.racefiles import result_paths

BANDS = ("1-3番人気", "4-5番人気", "6-9番人気", "10番人気以下")
PERIODS = ("2024", "2025", "2026")
# 前走着順の帯。乗り替わり・不利痕跡と同じ切り方に合わせる
CHAKU = (("前走1-5着", lambda c: 1 <= c <= 5),
         ("前走6-9着", lambda c: 6 <= c <= 9),
         ("前走二桁", lambda c: c >= 10))


def band_of(nk: int | None) -> str | None:
    if nk is None:
        return None
    if nk <= 3:
        return "1-3番人気"
    if nk <= 5:
        return "4-5番人気"
    if nk <= 9:
        return "6-9番人気"
    return "10番人気以下"


def load(dir_: str, races: str, months: str | None) -> list[dict]:
    """出走馬CSV（間隔表記・前走着順）と結果CSV（着順・人気）を突き合わせる。"""
    out: list[dict] = []
    for fp in result_paths(dir_, races, months):
        res = Path(fp)
        ent = res.with_name(res.name.replace("_結果.csv", "_出走馬.csv"))
        if not ent.exists():
            continue
        info: dict[str, dict] = {}
        for r in csv.DictReader(open(ent, encoding="utf-8-sig")):
            nm = (r.get("馬名") or "").strip()
            if nm:
                info[nm] = r
        rows = [r for r in csv.DictReader(open(res, encoding="utf-8-sig"))
                if (r.get("着順") or "").isdigit()]
        if len(rows) < 5:
            continue
        date = res.name[:10]
        for r in rows:
            nm = (r.get("馬名") or "").strip()
            e = info.get(nm)
            if not e:
                continue
            lab = (e.get("間隔表記") or "").strip()
            if not lab:
                continue
            nk = (r.get("人気") or "").strip()
            zc = (e.get("前走着順") or "").strip()
            out.append({
                "date": date, "label": lab,
                "band": band_of(int(nk) if nk.isdigit() else None),
                "chaku": int(r["着順"]),
                "zenso": int(zc) if zc.isdigit() else None,
                "rento": lab == "連闘",
            })
    return out


def rate(rows: list[dict], place: bool) -> tuple[int, int]:
    k = sum(1 for r in rows if (r["chaku"] <= 3 if place else r["chaku"] == 1))
    return k, len(rows)


def reproduced(test: list[dict], ctrl: list[dict], place: bool) -> str:
    signs = []
    for p in PERIODS:
        t = [r for r in test if r["date"].startswith(p)]
        c = [r for r in ctrl if r["date"].startswith(p)]
        kt, nt = rate(t, place)
        kc, nc = rate(c, place)
        if not nt or not nc or kt < 10:
            continue
        signs.append(1 if kt / nt >= kc / nc else -1)
    if len(signs) < 2:
        return "期間不足"
    return "再現" if len(set(signs)) == 1 else "反転"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="1-12")
    ap.add_argument("--months", default=None)
    args = ap.parse_args()

    rows = load(args.dir, args.races, args.months)
    rento = [r for r in rows if r["rento"]]
    print(f"{len(rows):,}出走（間隔表記あり）／連闘 {len(rento):,}\n")

    # 測る前に帯ごとの母数を数える（CLAUDE.mdの手順）
    print("== 帯ごとの母数（測る前に数える）==")
    print(f"  {'帯':<14}{'連闘':>8}{'対照':>10}"
          + "".join(f"{f'連闘×{l}':>16}" for l, _ in CHAKU))
    for b in BANDS:
        t = [r for r in rento if r["band"] == b]
        c = [r for r in rows if r["band"] == b and not r["rento"]]
        cells = [sum(1 for r in t if r["zenso"] is not None and f(r["zenso"]))
                 for _, f in CHAKU]
        print(f"  {b:<14}{len(t):>8,}{len(c):>10,}"
              + "".join(f"{n:>16,}" for n in cells))
    print()

    for place, lab in ((True, "複勝率"), (False, "勝率")):
        print(f"== {lab}: 連闘 vs 同じ人気帯の非連闘 ==")
        print("  " + HEADER)
        for b in BANDS:
            t = [r for r in rento if r["band"] == b]
            c = [r for r in rows if r["band"] == b and not r["rento"]]
            if len(t) < 50 or len(c) < 50:
                continue
            kt, nt = rate(t, place)
            kc, nc = rate(c, place)
            v = judge(f"{b} 連闘", kt, nt, kc, nc)
            print(f"  {v.line()}[{reproduced(t, c, place)}]")
        print()

        print(f"-- {lab}: 前走着順との組み合わせ --")
        print("  " + HEADER)
        for b in BANDS:
            for clab, f in CHAKU:
                t = [r for r in rento
                     if r["band"] == b and r["zenso"] is not None and f(r["zenso"])]
                c = [r for r in rows
                     if r["band"] == b and not r["rento"]
                     and r["zenso"] is not None and f(r["zenso"])]
                if len(t) < 50 or len(c) < 50:
                    continue
                kt, nt = rate(t, place)
                kc, nc = rate(c, place)
                v = judge(f"{b} {clab}×連闘", kt, nt, kc, nc)
                print(f"  {v.line()}[{reproduced(t, c, place)}]")
        print()

    # 間隔ラベル全体の並び（連闘がどこに位置するか）
    print("== 間隔ラベル別の複勝率（全体・参考）==")
    by = defaultdict(list)
    for r in rows:
        by[r["label"]].append(r)
    order = ["連闘"] + [f"中{i}週" for i in range(1, 13)]
    print(f"  {'間隔':<10}{'n':>9}{'複勝率':>9}{'勝率':>8}")
    for k in order:
        v = by.get(k)
        if not v or len(v) < 200:
            continue
        kp, n = rate(v, True)
        kw, _ = rate(v, False)
        print(f"  {k:<10}{n:>9,}{kp / n:>9.1%}{kw / n:>8.1%}")
    print()


if __name__ == "__main__":
    main()
