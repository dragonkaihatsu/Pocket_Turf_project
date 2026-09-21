#!/usr/bin/env python3
"""「堅いレースに紛れが起こることを祈る」買い方を測る。

## 何を測るのか

本人の狙い方（2026-09-21）:

> ねらい方としては　硬いレースに紛れが起こることを祈るスタイル
> 神戸新聞杯は惜しかったです

神戸新聞杯（9/21 阪神11R）がその形だった。1着ロブチェン・2着アルトラムスは
人気どころで**馬連は590円**しか付かなかったのに、3着に11番人気の
シートゥサミットが飛び込み、**ワイド 1-8 が2,180円**になった。
つまり「堅い決着の3着だけが紛れる」と、ワイドだけが跳ねる。

この狙い方には**2つの前提**があり、どちらも実測できる。

  (1) 堅いレース（1番人気が短い）でも3着に人気薄が入ることがある
  (2) そのときのワイドは、堅い帯ほど配当が大きい（市場が見ていないから）

(1)が低すぎれば祈っても来ないし、(2)が成り立たなければ堅い帯を選ぶ意味が
無い（荒れる帯で同じことをすればよい）。

## 買い方も一緒に測る

「祈る」は買い方に落とすと**軸を人気どころに置き、相手を人気薄へ伸ばす**
ことになる。既定の上位n頭BOXは相手をスコア順に伸ばすので、そこと比べる。

    python3 scripts/magire.py --dump data/profiles/jra/magire_dump.jsonl
    python3 scripts/magire.py --from-dump data/profiles/jra/magire_dump.jsonl

採点は重いので**1回だけ**ダンプに落とし、切り口を変えるときは
`--from-dump` で測り直す（`day_target.py` と同じ作り）。
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keiba.scoring as sc
from backtest import (load_race, load_race_info, parse_races, race_date,
                      race_number, race_venue)
from keiba import profile
from keiba.cli import _load_horse_records
from keiba.marks import assign_marks

STAKE = 100
BANDS = ("1倍台", "2倍台", "3倍以上")
# 「人気薄」の境目。6番人気以下は CLAUDE.md の人気帯（6-9番人気）に合わせ、
# 8番人気以下は神戸新聞杯の11番人気に近い側を見るため
ANA_CUTS = (6, 8)


def band_of(odds: float) -> str:
    return "1倍台" if odds < 2.0 else "2倍台" if odds < 3.0 else "3倍以上"


def key(a: int, b: int) -> str:
    return f"{min(a, b)}-{max(a, b)}"


# ---------------------------------------------------------------------------
# ダンプ（採点は1回だけ）
# ---------------------------------------------------------------------------

def dump(args) -> None:
    profile.assert_same_profile(args.dir, args.records)
    if args.ratings:
        table = json.loads(Path(args.ratings).read_text(encoding="utf-8"))
        sc.load_ratings = lambda *a, **k: table

    wanted = parse_races(args.races)
    kyori_by = load_race_info(args.race_info)
    surface_by: dict[str, str] = {}
    import csv as _csv
    p = Path(args.race_info)
    if p.exists():
        for row in _csv.DictReader(open(p, encoding="utf-8-sig")):
            if row.get("馬場種別"):
                surface_by[row["stem"]] = row["馬場種別"] + (row.get("距離") or "") + "m"
    records = _load_horse_records(args.records)
    d = Path(args.dir)

    out = Path(args.dump)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(out, "w", encoding="utf-8") as f:
        for stem in sorted({q.name.replace("_結果.csv", "")
                            for q in d.glob("*_結果.csv")}):
            rn = race_number(stem)
            if rn is None or rn not in wanted:
                continue
            race = load_race(d, stem)
            if race is None:
                continue
            fav = min((h for h in race["horses"] if h.ninki),
                      key=lambda h: h.ninki, default=None)
            if fav is None or not fav.tansho_odds:
                continue
            scores = sc.score_race(race["horses"], None, kyori=kyori_by.get(stem),
                                   records=records, as_of=race_date(stem),
                                   venue=race_venue(stem),
                                   surface=surface_by.get(stem))
            marked = assign_marks(scores, baba="良")
            if len(marked) < 8:
                continue
            order = [m.score.horse.umaban for m in marked]
            ninki = {h.umaban: h.ninki for h in race["horses"] if h.ninki}
            odds = {h.umaban: h.tansho_odds for h in race["horses"]
                    if h.tansho_odds}
            # 上位3人気の支持集中度（arare.py と同じ量）
            top3 = sorted((v for v in odds.values()), key=float)[:3]
            conc = sum(1.0 / o for o in top3 if o > 0)
            top3set = sorted(race["top3"])
            f.write(json.dumps({
                "stem": stem, "date": stem[:10],
                "fav": fav.umaban, "fav_odds": fav.tansho_odds,
                "band": band_of(fav.tansho_odds), "conc": round(conc, 4),
                "field": len(race["horses"]),
                "order": order, "ninki": ninki,
                "top2": sorted(race["top2"]), "top3": top3set,
                "wide": {key(*sorted(c)): v for c, v
                         in race["payouts"].get("ワイド", {}).items()
                         if len(c) == 2},
                "umaren": {key(*sorted(c)): v for c, v
                           in race["payouts"].get("馬連", {}).items()
                           if len(c) == 2},
            }, ensure_ascii=False) + "\n")
            n += 1
    print(f"{n:,}レースを {out} に書いた")


# ---------------------------------------------------------------------------
# 測る
# ---------------------------------------------------------------------------

def load_dump(path: str) -> list[dict]:
    rows = []
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        r["ninki"] = {int(k): v for k, v in r["ninki"].items()}
        rows.append(r)
    return rows


def bootstrap(pairs, b=10000):
    if not pairs:
        return (0.0, 0.0, 0.0)
    rng = random.Random(20260921)
    n = len(pairs)
    rates = []
    for _ in range(b):
        inv = ret = 0
        for _ in range(n):
            i, r = pairs[rng.randrange(n)]
            inv += i
            ret += r
        rates.append(ret / inv if inv else 0.0)
    rates.sort()
    return (rates[int(0.05 * len(rates))], rates[int(0.95 * len(rates))],
            sum(1 for r in rates if r >= 1.0) / len(rates))


def settle_wide(tickets: list[tuple[int, int]], r: dict) -> tuple[int, int]:
    top3 = set(r["top3"])
    ret = 0
    for a, b in tickets:
        if a in top3 and b in top3:
            ret += r["wide"].get(key(a, b), 0)
    return len(tickets) * STAKE, ret


def settle_umaren(tickets: list[tuple[int, int]], r: dict) -> tuple[int, int]:
    top2 = set(r["top2"])
    ret = 0
    for a, b in tickets:
        if {a, b} == top2:
            ret += r["umaren"].get(key(a, b), 0)
    return len(tickets) * STAKE, ret


# --- 前提(1)(2) を測る -----------------------------------------------------

def magire_rate(rows: list[dict]) -> None:
    print("== 前提(1) 堅いレースでも3着に人気薄は入るか ==")
    print(f"  {'帯':<8}{'R数':>6}" + "".join(f"{f'{c}人気以下が3着内':>18}"
                                            for c in ANA_CUTS)
          + f"{'1番人気が3着内':>16}")
    for b in BANDS:
        sel = [r for r in rows if r["band"] == b]
        if not sel:
            continue
        cells = []
        for c in ANA_CUTS:
            k = sum(1 for r in sel
                    if any(r["ninki"].get(u, 99) >= c for u in r["top3"]))
            cells.append(f"{k / len(sel):>17.1%}")
        fav_in = sum(1 for r in sel if r["fav"] in set(r["top3"]))
        print(f"  {b:<8}{len(sel):>6,}" + "".join(cells)
              + f"{fav_in / len(sel):>15.1%}")
    print()

    print("== 前提(2) 紛れたときのワイド配当（1番人気×人気薄の組）==")
    print("  堅い帯ほど配当が大きければ、堅いレースを選ぶ意味がある\n")
    print(f"  {'帯':<8}{'人気薄':<10}{'該当R':>7}{'配当 中央値':>13}"
          f"{'25%':>9}{'75%':>9}{'最大':>10}")
    for b in BANDS:
        sel = [r for r in rows if r["band"] == b]
        for c in ANA_CUTS:
            pays = []
            for r in sel:
                t3 = set(r["top3"])
                if r["fav"] not in t3:
                    continue
                for u in t3:
                    if u != r["fav"] and r["ninki"].get(u, 99) >= c:
                        v = r["wide"].get(key(r["fav"], u))
                        if v:
                            pays.append(v)
            if len(pays) < 20:
                continue
            pays.sort()
            q = lambda f: pays[int(f * (len(pays) - 1))]
            print(f"  {b:<8}{f'{c}人気以下':<10}{len(pays):>7,}"
                  f"{statistics.median(pays):>12,.0f}円{q(0.25):>8,.0f}"
                  f"{q(0.75):>9,.0f}{pays[-1]:>10,.0f}")
    print()


# --- 買い方を比べる --------------------------------------------------------

def plans(r: dict) -> dict[str, tuple[str, list[tuple[int, int]]]]:
    """買い目を作る。軸は**1番人気**（発走前に分かる）。"""
    o = r["order"]
    fav = r["fav"]
    nk = r["ninki"]
    # 軸を除いたスコア順の相手（軸自身は外す）
    rest = [u for u in o if u != fav]
    # スコア8位以内で人気薄
    ana6 = [u for u in o[:8] if u != fav and nk.get(u, 99) >= 6]
    ana8 = [u for u in o[:8] if u != fav and nk.get(u, 99) >= 8]
    out: dict[str, tuple[str, list[tuple[int, int]]]] = {
        "ワイド 上位3頭BOX(3点)": ("ワイド", list(combinations(o[:3], 2))),
        "ワイド 上位4頭BOX(6点)": ("ワイド", list(combinations(o[:4], 2))),
        "馬連 上位4頭BOX(6点)": ("馬連", list(combinations(o[:4], 2))),
        "ワイド 1番人気×スコア上位3(3点)": ("ワイド", [(fav, u) for u in rest[:3]]),
        "ワイド 1番人気×スコア4-8位(5点)": ("ワイド", [(fav, u) for u in rest[3:8]]),
        "ワイド 1番人気×スコア上位8(8点)": ("ワイド", [(fav, u) for u in rest[:8]]),
    }
    if ana6:
        out["ワイド 1番人気×6人気以下(上位8内)"] = ("ワイド", [(fav, u) for u in ana6])
    if ana8:
        out["ワイド 1番人気×8人気以下(上位8内)"] = ("ワイド", [(fav, u) for u in ana8])
    return out


def compare(rows: list[dict]) -> None:
    print("== 買い方の比較（1点100円・軸は1番人気）==")
    series: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for r in rows:
        for name, (kind, tickets) in plans(r).items():
            if not tickets:
                continue
            f = settle_wide if kind == "ワイド" else settle_umaren
            pair = f(tickets, r)
            for scope in ("全体", r["band"]):
                series.setdefault((name, scope), []).append(pair)

    names = list(plans(rows[0]).keys()) + ["ワイド 1番人気×6人気以下(上位8内)",
                                           "ワイド 1番人気×8人気以下(上位8内)"]
    seen = []
    for n in names:
        if n not in seen:
            seen.append(n)
    for scope in ("全体",) + BANDS:
        print(f"\n-- {scope} --")
        print(f"  {'買い方':<34}{'R数':>6}{'平均点':>7}{'的中率':>8}"
              f"{'回収率':>8}{'90%区間':>17}{'黒字確率':>9}")
        for name in seen:
            pairs = series.get((name, scope))
            if not pairs or len(pairs) < 50:
                continue
            inv = sum(i for i, _ in pairs)
            ret = sum(r for _, r in pairs)
            hit = sum(1 for _, r in pairs if r > 0)
            lo, hi, win = bootstrap(pairs)
            pts = inv / STAKE / len(pairs)
            print(f"  {name:<34}{len(pairs):>6,}{pts:>7.1f}"
                  f"{hit / len(pairs):>8.1%}{ret / inv:>8.0%}"
                  f"{lo:>8.0%}〜{hi:<8.0%}{win:>8.0%}")
    print()


def by_year(rows: list[dict], name: str) -> None:
    """期間で割る（CLAUDE.mdの『両期間で再現』基準）。"""
    print(f"== 期間再現: {name} ==")
    print(f"  {'帯':<8}" + "".join(f"{y:>12}" for y in ("2024", "2025", "2026")))
    for scope in ("全体",) + BANDS:
        cells = []
        for y in ("2024", "2025", "2026"):
            pairs = []
            for r in rows:
                if not r["date"].startswith(y):
                    continue
                if scope != "全体" and r["band"] != scope:
                    continue
                p = plans(r).get(name)
                if not p or not p[1]:
                    continue
                f = settle_wide if p[0] == "ワイド" else settle_umaren
                pairs.append(f(p[1], r))
            if len(pairs) < 50:
                cells.append(f"{'—':>12}")
                continue
            inv = sum(i for i, _ in pairs)
            ret = sum(x for _, x in pairs)
            cells.append(f"{ret / inv:>11.0%}")
        print(f"  {scope:<8}" + "".join(cells))
    print()


def by_conc(rows: list[dict]) -> None:
    """帯の中を支持集中度で3分割する（`keiba/arare.py` と同じ軸）。

    集中度で絞ると数字は上がるが、**3年で再現しない**（下の期間再現）。
    帯を絞ったあと更に3分割すると1年あたり40〜70レースしか残らない。
    """
    print("== 帯の中を支持集中度で割る（絞りすぎの確認）==")
    for band in ("1倍台", "2倍台"):
        sel = [r for r in rows if r["band"] == band]
        if len(sel) < 150:
            continue
        cs = sorted(r["conc"] for r in sel)
        k = len(cs) // 3
        lo, hi = cs[k], cs[2 * k]
        print(f"\n  {band}（{len(sel):,}R・境目 {lo:.3f}/{hi:.3f}）")
        print(f"    {'集中度':<8}{'R数':>5}"
              + "".join(f"{n:>28}" for n in
                        ("ワイド上位3頭BOX", "1番人気×スコア上位3")))
        for lab, f in (("高い", lambda r: r["conc"] >= hi),
                       ("ふつう", lambda r: lo <= r["conc"] < hi),
                       ("低い", lambda r: r["conc"] < lo)):
            part = [r for r in sel if f(r)]
            if len(part) < 50:
                continue
            cells = []
            for name in ("ワイド 上位3頭BOX(3点)", "ワイド 1番人気×スコア上位3(3点)"):
                pairs = [settle_wide(plans(r)[name][1], r) for r in part]
                inv = sum(i for i, _ in pairs)
                ret = sum(x for _, x in pairs)
                hit = sum(1 for _, x in pairs if x > 0)
                cells.append(f"的中{hit / len(pairs):>5.0%} 回収{ret / inv:>5.0%}")
            print(f"    {lab:<8}{len(part):>5}"
                  + "".join(f"{c:>28}" for c in cells))
        # いちばん良い区分だけ年で割る
        top = [r for r in sel if r["conc"] >= hi]
        if len(top) >= 150:
            print(f"    → 集中度 高い を年で割る（{band}）: ", end="")
            outs = []
            for y in ("2024", "2025", "2026"):
                part = [r for r in top if r["date"].startswith(y)]
                if len(part) < 30:
                    continue
                pairs = [settle_wide(
                    plans(r)["ワイド 1番人気×スコア上位3(3点)"][1], r) for r in part]
                inv = sum(i for i, _ in pairs)
                outs.append(f"{y} {sum(x for _, x in pairs) / inv:.0%}(n={len(part)})")
            print(" / ".join(outs))
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default="9-12")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--records", default="data/profiles/jra/horse_records.csv")
    ap.add_argument("--ratings", default="data/profiles/jra/ratings.json")
    ap.add_argument("--dump", help="採点してダンプを書く（1回だけ）")
    ap.add_argument("--from-dump", help="ダンプから測り直す")
    args = ap.parse_args()

    if args.dump:
        dump(args)
        return
    if not args.from_dump:
        ap.error("--dump か --from-dump のどちらかを指定する")

    rows = load_dump(args.from_dump)
    print(f"{len(rows):,}レース（{rows[0]['date']}〜{rows[-1]['date']}）\n")
    magire_rate(rows)
    compare(rows)
    by_conc(rows)
    for n in ("ワイド 1番人気×スコア4-8位(5点)",
              "ワイド 1番人気×スコア上位3(3点)",
              "ワイド 上位3頭BOX(3点)"):
        by_year(rows, n)


if __name__ == "__main__":
    main()
