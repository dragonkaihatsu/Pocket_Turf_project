#!/usr/bin/env python3
"""騎手別の「得意条件」を実測する。

「騎手Aは実績上位だから加点」という一律のやり方ではなく、**騎手×競馬場×
距離帯×馬場種別**の組み合わせで単勝回収率を集計し、100%を超える組み合わせを
拾う。ネームバリューの無い騎手でも特定条件だけ回収率が高いことがあり、
そこに市場が気づいていなければ期待値が生まれる、という発想（本人の言葉）。

**母数の注意（CLAUDE.mdの一貫した方針）**: 組み合わせを細かくするほど
母数が減り、「回収率100%超」の多くは偶然の産物になる。実際の的中数・
レース数を必ず併記し、数字だけで判断しないこと。

対象データは data/collected_jra の結果CSV（2026年1〜8月・803レース、
中央のみ・大井は含まない）。3年分の蓄積はまだ無く、この期間だけの実測
である点を明記して出す。

    python3 scripts/jockey_stats.py --dir data/collected_jra \
        --race-info data/profiles/jra/race_info.csv \
        --out data/profiles/jra/jockey_stats.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

STAKE = 100
MIN_N_SHOW = 5     # これ未満は集計自体を出さない（ノイズにしかならない）
MIN_N_TRUST = 10   # これ未満は「回収率100%超」でも参考扱いにする
# 単勝回収率は「n件中1勝が高配当だった」だけで簡単に跳ね上がる
# （例: n=12・1勝でも当該馬が20倍なら回収率167%）。scripts/single.py /
# scripts/tanpuku.py で使っている「実際の的中本数10本以上」という
# 基準をここでも揃える。n だけで足切りすると、この手の一発高配当が
# 「得意条件」の上位を占めてしまう
MIN_WINS_TRUST = 10

RACE_VENUE_RE = re.compile(r"_(\D+?)\d{2}R_")


def race_venue(stem: str) -> str | None:
    m = RACE_VENUE_RE.search(stem + "_")
    return m.group(1) if m else None


def distance_band(kyori: int) -> str:
    if kyori <= 1400:
        return "短距離(~1400)"
    if kyori <= 1800:
        return "マイル(1401-1800)"
    if kyori <= 2200:
        return "中距離(1801-2200)"
    return "長距離(2201~)"


def load_race_info(path: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    p = Path(path)
    if not p.exists():
        return out
    with open(p, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if (row.get("距離") or "").isdigit():
                out[row["stem"]] = row
    return out


def load_tansho_payouts(path: Path) -> dict[int, int]:
    """単勝配当を 馬番 → 配当円 で返す（勝ち馬以外は0扱いなのでキーに無い）。"""
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("券種") == "単勝":
                try:
                    out[int(row["組み合わせ"])] = int(row["配当"])
                except ValueError:
                    continue
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--out", help="結果をJSONで書き出す")
    ap.add_argument("--csv-out", help="組み合わせ別の一覧をCSVでも書き出す")
    args = ap.parse_args()

    d = Path(args.dir)
    race_info = load_race_info(args.race_info)

    # key = (騎手, 粒度, 条件文字列) → [(投資, 払戻, 着順)]
    rides: dict[tuple, list[tuple[int, int, int]]] = defaultdict(list)
    used_races = 0
    used_rides = 0
    no_info = 0

    for res_path in sorted(d.glob("*_結果.csv")):
        stem = res_path.name[: -len("_結果.csv")]
        venue = race_venue(stem)
        info = race_info.get(stem)
        pay = load_tansho_payouts(res_path.with_name(f"{stem}_配当.csv"))
        if not venue:
            continue
        used_races += 1

        kyori = int(info["距離"]) if info and (info.get("距離") or "").isdigit() else None
        surface = info.get("馬場種別") if info else None
        if kyori is None or not surface:
            no_info += 1

        with open(res_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                jockey = (row.get("騎手") or "").strip()
                chaku = row.get("着順")
                umaban = row.get("馬番")
                if not jockey or not chaku or not chaku.isdigit() or not umaban:
                    continue
                chaku_i = int(chaku)
                ret = pay.get(int(umaban), 0) if umaban.isdigit() else 0
                used_rides += 1

                rides[(jockey, "場", venue)].append((STAKE, ret, chaku_i))
                if kyori is not None:
                    band = distance_band(kyori)
                    rides[(jockey, "距離帯", band)].append((STAKE, ret, chaku_i))
                    if surface:
                        rides[(jockey, "場×距離帯×馬場", f"{venue}/{surface}/{band}")].append(
                            (STAKE, ret, chaku_i))

    print(f"{args.dir}: {used_races}レース・{used_rides}騎乗 を集計"
          f"（距離・馬場種別が引けなかったレース: {no_info}件）\n")

    rows = []
    for (jockey, granularity, cond), lst in rides.items():
        n = len(lst)
        if n < MIN_N_SHOW:
            continue
        inv = sum(a for a, _, _ in lst)
        ret = sum(b for _, b, _ in lst)
        win = sum(1 for _, _, c in lst if c == 1)
        show = sum(1 for _, _, c in lst if c <= 3)
        recovery = ret / inv
        rows.append({
            "騎手": jockey, "粒度": granularity, "条件": cond,
            "n": n, "勝利数": win, "複勝内数": show,
            "勝率": round(win / n, 4), "複勝率": round(show / n, 4),
            "単勝回収率": round(recovery, 4),
            "信頼できる母数": n >= MIN_N_TRUST and win >= MIN_WINS_TRUST,
        })

    rows.sort(key=lambda r: (-r["単勝回収率"], -r["n"]))

    over100 = [r for r in rows if r["単勝回収率"] >= 1.0]
    trusted = [r for r in over100 if r["信頼できる母数"]]
    print(f"回収率100%超の組み合わせ: {len(over100)}件"
          f"（うちn>={MIN_N_TRUST}かつ勝利{MIN_WINS_TRUST}本以上で参考にできるもの: "
          f"{len(trusted)}件）\n")

    print(f"{'騎手':<10}{'粒度':<12}{'条件':<28}{'n':>5}{'勝利':>5}{'勝率':>7}"
          f"{'複勝率':>7}{'単勝回収率':>10}")
    for r in trusted[:40]:
        print(f"{r['騎手']:<10}{r['粒度']:<12}{r['条件']:<28}{r['n']:>5}{r['勝利数']:>5}"
              f"{r['勝率']:>7.0%}{r['複勝率']:>7.0%}{r['単勝回収率']:>10.0%}")

    if args.out:
        payload = {
            "対象": args.dir, "レース数": used_races, "騎乗数": used_rides,
            "母数閾値_表示": MIN_N_SHOW, "母数閾値_信頼": MIN_N_TRUST,
            "組み合わせ": rows,
        }
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"\n書き出し: {args.out}")

    if args.csv_out:
        with open(args.csv_out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["騎手", "粒度", "条件", "n", "勝利数",
                                              "複勝内数", "勝率", "複勝率", "単勝回収率",
                                              "信頼できる母数"])
            w.writeheader()
            w.writerows(rows)
        print(f"書き出し: {args.csv_out}")


if __name__ == "__main__":
    main()
