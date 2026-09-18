#!/usr/bin/env python3
"""血統（種牡馬）×コース特性の適合を測る。

    python3 scripts/ketto_course.py --census          # 母数を数えるだけ
    python3 scripts/ketto_course.py --axis 小回り      # 測る

## なぜ「場」ではなく「特性」で束ねるのか

「この種牡馬は中山が得意」を場ごとに測ると、種牡馬521頭 × 10場 ×
4人気帯に割れて1セルが数頭になる。コース適性15点が死んでいた原因と
同じ形である（`keiba/courses.py` 冒頭）。そこで小回り・坂・芝種・回り・
直線の5軸で束ねる。

## 判定の設計（CLAUDE.mdの主指標に合わせる）

素の複勝率を比べても、良い種牡馬が上に来るだけで「コース適合」の話には
ならない。測るのは**その種牡馬の中での対比**:

    リフト = (その種牡馬の産駒が、特性Aの場で出した複勝率)
             − (同じ種牡馬の産駒が、特性A以外の場で出した複勝率)

さらに水準（良い種牡馬か）は市場が織り込んでいるので、
**同一人気帯の中**で取る。

## 独立検証を最初から組み込む

「2025年の産駒成績で『この種牡馬はこの特性が得意』を決め、2026年で
当てる」。in-sample のリフトは必ず出る（自分で選んだ側を自分で測る）
ので、それを成果と読まないため。騎手・血統補正が独立検証で消えた件と
同じ検証の形にしてある。
"""
from __future__ import annotations

import argparse
import collections
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import power
from keiba.courses import COURSES, traits
from keiba.racefiles import DEFAULT_RACES, VENUE_NO_RE, result_files

BANDS = [("1-3番人気", 1, 3), ("4-5番人気", 4, 5),
         ("6-9番人気", 6, 9), ("10番人気以下", 10, 99)]
AXES = ("小回り", "坂", "芝種", "回り", "直線")


def band_of(ninki: int | None) -> str | None:
    if ninki is None:
        return None
    for label, lo, hi in BANDS:
        if lo <= ninki <= hi:
            return label
    return None


def load_race_conditions(path: str) -> dict[str, dict]:
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            out[r["stem"]] = r
    return out


def starters(d: Path, races: str, cond: dict[str, dict]) -> list[dict]:
    """(種牡馬, 場, 芝ダ, 人気帯, 複勝, 年) のレコードを作る。

    血統父は**出走馬CSVにしか無い**（結果CSVには載らない）ので、
    馬番で突き合わせる。
    """
    rows = []
    for res in result_files(d, races):
        stem = res.name[: -len("_結果.csv")]
        c = cond.get(stem)
        if not c or not c.get("馬場種別"):
            continue
        m = VENUE_NO_RE.search(stem)
        venue = m.group(1) if m else None
        if venue not in COURSES:
            continue
        ent = res.with_name(f"{stem}_出走馬.csv")
        if not ent.exists():
            continue

        sire = {}
        with open(ent, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if (r.get("馬番") or "").isdigit():
                    sire[int(r["馬番"])] = (r.get("血統父") or "").strip()

        year = stem[:4]
        surface = c["馬場種別"]
        tr = traits(venue, surface)
        with open(res, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if not (r.get("馬番") or "").isdigit():
                    continue
                if not (r.get("着順") or "").isdigit():
                    continue
                ninki = int(r["人気"]) if (r.get("人気") or "").isdigit() else None
                b = band_of(ninki)
                s = sire.get(int(r["馬番"]))
                if not s or b is None:
                    continue
                rows.append({"種牡馬": s, "場": venue, "芝ダ": surface,
                             "帯": b, "複": int(r["着順"]) <= 3,
                             "年": year, "特性": tr})
    return rows


def census(rows: list[dict]) -> None:
    per_sire = collections.Counter(r["種牡馬"] for r in rows)
    print(f"延べ{len(rows):,}出走 / 種牡馬{len(per_sire):,}頭\n")

    print("■ 種牡馬ごとの産駒出走数")
    for lo in (2000, 1000, 500, 200, 100, 50):
        k = sum(1 for v in per_sire.values() if v >= lo)
        print(f"  {lo:>5}出走以上: {k:>4}頭")

    print("\n■ 帯ごとの母数（同一人気帯内で判定するので、ここが本当の母数）")
    print(f"{'軸':<8}{'両側30以上':>12}{'両側100以上':>12}"
          f"{'最大セル':>10}{'見える差':>10}")
    for axis in AXES:
        both30 = both100 = 0
        biggest = 0
        for sire, n in per_sire.items():
            if n < 50:
                continue
            for label, _, _ in BANDS:
                sel = [r for r in rows
                       if r["種牡馬"] == sire and r["帯"] == label
                       and axis in r["特性"]]
                by = collections.Counter(r["特性"][axis] for r in sel)
                if len(by) < 2:
                    continue
                top2 = by.most_common(2)
                biggest = max(biggest, top2[0][1])
                if top2[1][1] >= 30:
                    both30 += 1
                if top2[1][1] >= 100:
                    both100 += 1
        mdd = power.min_detectable_diff(biggest, 0.22) if biggest else None
        print(f"{axis:<8}{both30:>12}{both100:>12}{biggest:>10}"
              f"{(f'{mdd:.1%}' if mdd else '—'):>10}")


def measure(rows: list[dict], axis: str, min_side: int, train: str,
            test: str) -> None:
    """train年で「得意な特性値」を決め、test年で当てる（独立検証）。"""
    print(f"■ {axis} — {train}年で決め、{test}年で当てる\n")

    def hits(sel):
        return sum(1 for r in sel if r["複"])

    def rate(sel):
        return (hits(sel) / len(sel)) if sel else None

    # train: 種牡馬ごとに、どの特性値が得意か
    pref: dict[str, str] = {}
    tr_rows = [r for r in rows if r["年"] == train and axis in r["特性"]]
    by_sire = collections.defaultdict(list)
    for r in tr_rows:
        by_sire[r["種牡馬"]].append(r)
    for sire, sel in by_sire.items():
        by_val = collections.defaultdict(list)
        for r in sel:
            by_val[r["特性"][axis]].append(r)
        ok = {v: s for v, s in by_val.items() if len(s) >= min_side}
        if len(ok) < 2:
            continue
        best = max(ok, key=lambda v: rate(ok[v]))
        pref[sire] = best
    print(f"  {train}年で判定できた種牡馬: {len(pref)}頭"
          f"（各特性値に{min_side}出走以上）\n")

    te_rows = [r for r in rows if r["年"] == test and axis in r["特性"]
               and r["種牡馬"] in pref]
    print(f"{'人気帯':<14}{'区分':<16}{'n':>7}{'複勝率':>8}"
          f"{'帯全体':>8}{'リフト':>8}{'要る差':>8}  判定")
    for label, _, _ in BANDS:
        band_all = [r for r in rows if r["年"] == test and r["帯"] == label]
        base = rate(band_all)
        if base is None:
            continue
        print(f"{label:<14}{'帯の全体':<16}{len(band_all):>7,}"
              f"{base:>8.1%}{'—':>8}{'—':>8}{'—':>8}")
        for name, want in (("得意な特性で走る", True),
                           ("それ以外で走る", False)):
            sel = [r for r in te_rows if r["帯"] == label
                   and (r["特性"][axis] == pref[r["種牡馬"]]) == want]
            if len(sel) < 30:
                continue
            got = rate(sel)
            j = power.judge(name, hits(sel), len(sel),
                            hits(band_all), len(band_all))
            # 期間で符号が揃うかも見る（in-sample の選択が効いていないか）
            print(f"{'':<14}{name:<16}{len(sel):>7,}{got:>8.1%}"
                  f"{base:>8.1%}{got - base:>+8.1%}"
                  f"{j.mdd:>8.1%}  {j.code}")
        print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="1-12",
                    help="履歴として使うレース帯。産駒成績は帯を絞る理由が"
                         "無いので既定は全帯")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--census", action="store_true",
                    help="母数を数えるだけ（測る前に必ずこちらを通す）")
    ap.add_argument("--axis", choices=AXES)
    ap.add_argument("--min-side", type=int, default=30,
                    help="train年で「得意」を決めるのに要る、片側あたりの出走数")
    ap.add_argument("--train", default="2025")
    ap.add_argument("--test", default="2026")
    a = ap.parse_args()

    cond = load_race_conditions(a.race_info)
    rows = starters(Path(a.dir), a.races, cond)

    if a.census or not a.axis:
        census(rows)
        return
    measure(rows, a.axis, a.min_side, a.train, a.test)


if __name__ == "__main__":
    main()
