#!/usr/bin/env python3
"""平場で頑張っている騎手と、上のクラスで落ちる騎手を比べる。

「平場で頑張っている騎手、重賞では勝てない騎手などの比較」（本人の言葉・2026-09-12）。

## 重賞だけは切り出せない（先に断っておく）

`data/profiles/jra/race_info.csv` に `等級` 列を追加したが、等級は結果HTMLの
キャッシュからしか読めず、**2,141レース中6レースしか埋まっていない**
（キャッシュは運用の途中で縮む）。レース名からも分けられない——固有名の
レースが1,363本あり、そこに2勝クラスの特別からG1までが混ざっている。

そこで**機械的に100%分類できる階層**で比べる:

    下級条件 … レース名にクラス表記がある（新馬・未勝利・1勝・2勝クラス）
    特別以上 … 固有名のレース（特別・L・OP・重賞が混ざる）

「重賞では勝てない」の厳密な検証には等級の収集し直しが要る（結果ページ
2,176件・1.5秒間隔で約1時間）。1-8Rの収集と同時に走らせない。

## 人気帯の構成で調整する

騎手ごとに乗る馬の人気分布が違う。人気薄ばかり乗る騎手の複勝率が低いのは
当たり前なので、**その階層・その人気帯の平均複勝率から期待値を作り、
実績との差（リフト）**で測る。CLAUDE.mdの主指標（同一人気帯内の正解率リフト）
を騎手単位に当てたもの。

    リフト = (実際の複勝数 − 期待複勝数) / 騎乗数

    python3 scripts/jockey_class.py
    python3 scripts/jockey_class.py --races 1-12   # 1-8Rの収集後
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.power import min_detectable_diff, required_n, wilson
from keiba.racefiles import DEFAULT_RACES, result_paths

NAME_RE = re.compile(r"\d{4}-\d{2}-\d{2}_\D+?(\d{2})R_(.+)_結果\.csv$")
BANDS = ((1, 3), (4, 5), (6, 9), (10, 99))
LOWER, UPPER = "下級条件", "特別以上"


def klass(name: str) -> str:
    """レース名から階層を決める。クラス表記が残っているのが下級条件。

    特別競走はクラスを名前に出さない（竹田城Sは3勝クラス）ので、
    固有名なら「特別以上」に入る。ここに重賞も混ざる。
    """
    if "新馬" in name or "未勝利" in name:
        return LOWER
    if re.search(r"[1-3]勝クラス", name):
        return LOWER
    return UPPER


def band_of(ninki: int) -> tuple[int, int] | None:
    return next((b for b in BANDS if b[0] <= ninki <= b[1]), None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--months", default=None,
                    help="対象月。1-8Rの収集が途中のあいだ `--races 1-12` をそのまま渡すと「1-8Rが入っている数ヶ月」と「9-12Rだけの残り」が混ざるので、効果を測るときは期間を揃える（例 2025-01..2025-03）")
    ap.add_argument("--min-rides", type=int, default=100,
                    help="両方の階層でこの騎乗数を満たす騎手だけ比べる")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    rides: list[dict] = []
    for path in result_paths(args.dir, args.races, args.months):
        m = NAME_RE.match(Path(path).name)
        if not m:
            continue
        lv = klass(m.group(2))
        for r in csv.DictReader(open(str(path), encoding="utf-8-sig")):
            if not (r.get("着順") or "").isdigit():
                continue
            nk = r.get("人気") or ""
            if not nk.isdigit():
                continue
            b = band_of(int(nk))
            if not b:
                continue
            rides.append({"j": (r.get("騎手") or "").strip(), "level": lv,
                          "band": b, "plc": int(r["着順"]) <= 3})

    # 階層 × 人気帯 の平均複勝率（期待値の土台）
    base: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for r in rides:
        c = base[(r["level"], r["band"])]
        c[0] += 1
        c[1] += r["plc"]
    print(f"延べ {len(rides):,}騎乗")
    print(f"  {'階層':<10}{'人気帯':<14}{'n':>8}{'複勝率':>9}")
    for (lv, b), (n, k) in sorted(base.items()):
        print(f"  {lv:<10}{f'{b[0]}-{b[1]}番人気':<14}{n:>8,}{k / n * 100:>8.1f}%")
    print()

    per: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {LOWER: [0, 0, 0.0], UPPER: [0, 0, 0.0]})   # n, 複勝, 期待複勝
    for r in rides:
        n, k = base[(r["level"], r["band"])]
        cell = per[r["j"]][r["level"]]
        cell[0] += 1
        cell[1] += r["plc"]
        cell[2] += k / n

    rows = []
    for j, lv in per.items():
        lo, up = lv[LOWER], lv[UPPER]
        if lo[0] < args.min_rides or up[0] < args.min_rides:
            continue
        if lo[1] < 10 or up[1] < 10:      # 複勝の的中10本以上（CLAUDE.mdの基準）
            continue
        lift_lo = (lo[1] - lo[2]) / lo[0] * 100
        lift_up = (up[1] - up[2]) / up[0] * 100
        mdd = max(min_detectable_diff(int(lo[0]), lo[2] / lo[0]),
                  min_detectable_diff(int(up[0]), up[2] / up[0])) * 100
        rows.append({"j": j, "lo": lo, "up": up, "lift_lo": lift_lo,
                     "lift_up": lift_up, "gap": lift_lo - lift_up, "mdd": mdd})
    print(f"■ 両階層で騎乗{args.min_rides}以上・複勝的中10本以上の騎手 {len(rows)}人")
    print("  リフト＝その階層・その人気帯の平均からの差（pt）。プラスなら市場より走らせている\n")

    def show(title: str, key, rev: bool) -> None:
        print(f"  {title}")
        print(f"    {'騎手':<10}{'下級 n':>7}{'複勝率':>8}{'リフト':>8}"
              f"{'特別以上 n':>11}{'複勝率':>8}{'リフト':>8}{'差':>8}{'見える差':>10}")
        for r in sorted(rows, key=key, reverse=rev)[:args.top]:
            lo, up = r["lo"], r["up"]
            print(f"    {r['j']:<10}{lo[0]:>7,}{lo[1] / lo[0] * 100:>7.1f}%"
                  f"{r['lift_lo']:>+7.1f}{up[0]:>11,}{up[1] / up[0] * 100:>7.1f}%"
                  f"{r['lift_up']:>+7.1f}{r['gap']:>+7.1f}{r['mdd']:>9.1f}")
        print()

    show("▼ 平場で稼いで上で落ちる（差が大きい順）", lambda r: r["gap"], True)
    show("▲ 上のクラスでこそ走らせる（差が小さい順）", lambda r: r["gap"], False)

    big = [r for r in rows if abs(r["gap"]) > r["mdd"]]
    print(f"■ 差がこの母数で見える大きさを超えた騎手: {len(big)}/{len(rows)}人")
    for r in sorted(big, key=lambda r: r["gap"], reverse=True):
        side = "平場型" if r["gap"] > 0 else "上級型"
        print(f"  {r['j']:<10}差{r['gap']:+.1f}pt（見える差{r['mdd']:.1f}pt）{side}")
    print()
    print(f"  ※ {len(rows)}人を同時に見ているので、偶然でも数人はこの線を越える。")
    print("    期間で割って符号が揃うかまでは測っていない（母数が半分になる）")
    print()

    # いま見えている差を主張するには何騎乗必要か。1-8Rの収集で下級条件が
    # 大きく増えるので、そこに届くかを見る
    print("■ いま差が大きく見える騎手に、あと何騎乗必要か")
    print(f"  {'騎手':<10}{'差':>8}{'下級 n':>8}{'必要n':>8}{'倍率':>7}{'特別以上 n':>11}{'必要n':>8}{'倍率':>7}")
    for r in sorted(rows, key=lambda x: abs(x["gap"]), reverse=True)[:6]:
        diff = abs(r["gap"]) / 100
        need_lo = required_n(r["lo"][2] / r["lo"][0], diff)
        need_up = required_n(r["up"][2] / r["up"][0], diff)
        print(f"  {r['j']:<10}{r['gap']:>+7.1f}{r['lo'][0]:>8,}{need_lo:>8,}"
              f"{need_lo / r['lo'][0]:>6.1f}倍{r['up'][0]:>11,}{need_up:>8,}"
              f"{need_up / r['up'][0]:>6.1f}倍")
    print()
    print("  1-8Rを17ヶ月ぶん入れて測った結果（2026-09-12）: 下級条件の騎乗は")
    print("  10倍規模になり、両階層で騎乗100以上の騎手は33人→63人に増えたが、")
    print("  **差が見える大きさを超えた騎手は0人のまま**だった。上の必要nを見ると")
    print("  下級側は「0.4〜0.5倍」＝すでに足りていて、**特別以上が1.1〜1.7倍**")
    print("  必要な状態。1-8Rでは特別以上が増えないので、ここから先は年数が要る")


if __name__ == "__main__":
    main()
