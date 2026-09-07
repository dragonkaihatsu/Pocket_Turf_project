#!/usr/bin/env python3
"""時計指数のDBを作る。

外部AIの重要度表で1位(20.7%)と2位(14.5%)を占めるのが「近走時計指数と
メンバートップ／平均との差」だった。うちには時計を使う仕組みが無かったが、
走破タイムは収集済みCSVに100%入っている。**収集を足さずに作れる。**

生のタイムは距離・コース・馬場状態で比べられないので、2段階で補正する。

  1. 基準タイム  (場, 芝ダ, 距離) ごとの全出走馬タイムの中央値と標準偏差
  2. 馬場差      その開催日・その場・その芝ダで、勝ちタイムが基準から
                 どれだけずれたか（中央値）。時計の出やすい日／かかる日を吸収する

    補正タイム = 実タイム − 馬場差
    時計指数   = 50 + 10 × (基準タイム − 補正タイム) / 標準偏差

標準偏差で割るのは、1秒の重みが距離で違うため。係数を手で決めずに済み、
距離をまたいで比較できる。50が平均、10上がるごとに1標準偏差ぶん速い。

**未来の情報について**: 馬場差はその日のレースが終わってから決まる。
これは「過去のレースの指数」を作るぶんには問題ない（予想する時点で
その日は終わっている）。**予想対象レース当日の馬場差は使わないこと。**

    python3 scripts/build_speed_db.py --profile jra

出力 data/profiles/<prof>/
    base_time.csv     場,馬場種別,距離,基準タイム,標準偏差,頭数
    track_variant.csv 日付,場,馬場種別,馬場差,レース数
    speed_index.csv   stem,R,馬名,日付,場,馬場種別,距離,着順,人気,頭数,
                      タイム,補正タイム,時計指数,上がり3F
                      ※ stem が無いと、同じ日・同じ場・同じ距離の別レース
                         （例: 2025-04-20 中山芝2000 の 9R と 11R皐月賞）を
                         区別できず、集計側でレースを取り違える
"""
from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MIN_CELL = 10       # (場,芝ダ,距離) がこの数に満たない区分は指数を作らない
MIN_RACES_DAY = 2   # 1日1レースしかない場では馬場差を出さない


def sec(t: str):
    """'1:24.5' → 84.5 秒"""
    t = (t or "").strip()
    m = re.match(r"(\d+):(\d+)\.(\d)$", t)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 10
    m = re.match(r"(\d+)\.(\d)$", t)
    return int(m.group(1)) + int(m.group(2)) / 10 if m else None


def _num(x, default=None):
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return default


def race_venue(stem):
    m = re.search(r"_(\D+?)\d{2}R_", stem)
    return m.group(1) if m else ""


def race_number(stem):
    m = re.search(r"_\D+?(\d{2})R_", stem)
    return int(m.group(1)) if m else None


def load(directory: Path, info: dict):
    """1行1頭。障害と、条件が分からないレースは除く。"""
    out = []
    for p in sorted(directory.glob("*_結果.csv")):
        stem = p.name[: -len("_結果.csv")]
        m = info.get(stem)
        if not m or m.get("馬場種別") not in ("芝", "ダ"):
            continue
        if not (m.get("距離") or "").isdigit():
            continue
        venue = race_venue(stem)
        if not venue:
            continue
        rows = [r for r in csv.DictReader(open(p, encoding="utf-8-sig"))
                if (r.get("着順") or "").isdigit()]
        if not rows:
            continue
        n = len(rows)
        for r in rows:
            t = sec(r.get("タイム"))
            nm = (r.get("馬名") or "").strip()
            if t is None or not nm:
                continue
            out.append({
                "馬名": nm, "日付": stem[:10], "stem": stem, "場": venue,
                "R": race_number(stem) or "",
                "馬場種別": m["馬場種別"], "距離": int(m["距離"]),
                "着順": int(r["着順"]), "人気": _num(r.get("人気")),
                "頭数": n, "タイム": t,
                "上がり3F": _num(r.get("上がり3F")),
            })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["nar", "jra"], default="jra")
    ap.add_argument("--dir", default=None)
    args = ap.parse_args()

    import keiba.profile as profile
    prof = profile.use(args.profile)
    info = {r["stem"]: r for r in csv.DictReader(
        open(prof.path("race_info.csv"), encoding="utf-8-sig"))}
    d = Path(args.dir or ("data/collected" if args.profile == "nar"
                          else "data/collected_jra"))
    rows = load(d, info)
    print(f"延べ {len(rows):,}頭 / {len({r['stem'] for r in rows}):,}レース")

    # --- 1. 基準タイム（全出走馬のタイムから）
    cells = defaultdict(list)
    for r in rows:
        cells[(r["場"], r["馬場種別"], r["距離"])].append(r["タイム"])
    base = {}
    for k, v in cells.items():
        if len(v) < MIN_CELL:
            continue
        sd = statistics.pstdev(v)
        if sd <= 0:
            continue
        base[k] = (statistics.median(v), sd, len(v))
    print(f"基準タイム {len(base)}区分（{MIN_CELL}頭未満の区分は作らない）")

    with open(prof.path("base_time.csv"), "w", newline="",
              encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["場", "馬場種別", "距離", "基準タイム", "標準偏差", "頭数"])
        for (v, s, k), (med, sd, n) in sorted(base.items()):
            w.writerow([v, s, k, f"{med:.2f}", f"{sd:.3f}", n])

    # --- 2. 馬場差（その日その場その芝ダの勝ちタイムが基準からどれだけずれたか）
    day = defaultdict(list)
    for r in rows:
        if r["着順"] != 1:
            continue
        b = base.get((r["場"], r["馬場種別"], r["距離"]))
        if not b:
            continue
        day[(r["日付"], r["場"], r["馬場種別"])].append(r["タイム"] - b[0])
    variant = {k: (statistics.median(v), len(v))
               for k, v in day.items() if len(v) >= MIN_RACES_DAY}
    print(f"馬場差 {len(variant):,}組（1日{MIN_RACES_DAY}レース未満は作らない）")

    with open(prof.path("track_variant.csv"), "w", newline="",
              encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["日付", "場", "馬場種別", "馬場差", "レース数"])
        for (dt, v, s), (mv, n) in sorted(variant.items()):
            w.writerow([dt, v, s, f"{mv:+.2f}", n])

    # --- 3. 1頭1レースの時計指数
    made = skipped = 0
    with open(prof.path("speed_index.csv"), "w", newline="",
              encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["stem", "R", "馬名", "日付", "場", "馬場種別", "距離",
                    "着順", "人気", "頭数", "タイム", "補正タイム",
                    "時計指数", "上がり3F"])
        for r in sorted(rows, key=lambda r: (r["日付"], r["stem"], r["着順"])):
            b = base.get((r["場"], r["馬場種別"], r["距離"]))
            if not b:
                skipped += 1
                continue
            med, sd, _ = b
            mv = variant.get((r["日付"], r["場"], r["馬場種別"]), (0.0, 0))[0]
            adj = r["タイム"] - mv
            idx = 50 + 10 * (med - adj) / sd
            made += 1
            w.writerow([r["stem"], r["R"], r["馬名"], r["日付"], r["場"],
                        r["馬場種別"], r["距離"],
                        r["着順"], int(r["人気"]) if r["人気"] else "",
                        r["頭数"], f"{r['タイム']:.1f}", f"{adj:.2f}",
                        f"{idx:.1f}", r["上がり3F"] or ""])
    print(f"時計指数 {made:,}行（区分不足で作れず {skipped:,}）"
          f" → {prof.path('speed_index.csv')}")


if __name__ == "__main__":
    main()
