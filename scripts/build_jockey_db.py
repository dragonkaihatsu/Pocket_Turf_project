#!/usr/bin/env python3
"""騎手の成績DBを作る（年で分けて保存する）。

**年ごとに行を分けて持つのが肝**である。ある年のレースを採点するときは
「その年より前」の行だけを足して使う。こうしておけば、集計側で気を
つけなくても未来の情報が混ざらない。

生の勝率は乗る馬で決まるため、人気から計算した期待値も一緒に持つ。
    勝/期待 = 実際の勝利数 ÷ Σ P(勝ち | その馬の人気)

    python3 scripts/build_jockey_db.py --profile jra

出力 data/profiles/<prof>/jockey_stats.csv
    騎手,年,場,馬場種別,距離帯,騎乗,勝,複,期待勝,期待複,単勝払戻
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIELDS = ["騎手", "年", "場", "馬場種別", "距離帯", "騎乗", "勝", "複",
          "期待勝", "期待複", "単勝払戻"]
ALL = "計"          # 場・馬場種別・距離帯をまとめた行に入れる印


def _num(x, default=None):
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return default


def race_venue(stem):
    m = re.search(r"_(\D+?)\d{2}R_", stem)
    return m.group(1) if m else ""


def dist_band(k):
    if not k:
        return ""
    k = int(k)
    return "〜1400" if k <= 1400 else "1401-1800" if k <= 1800 else "1801〜"


def load_rows(directory: Path, info: dict):
    """1行1頭。障害は除く。"""
    out = []
    for p in sorted(directory.glob("*_結果.csv")):
        stem = p.name[: -len("_結果.csv")]
        m = info.get(stem)
        if not m or m.get("馬場種別") not in ("芝", "ダ"):
            continue          # 障害戦とレース条件不明を除く
        venue = race_venue(stem)
        band = dist_band(m.get("距離"))
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            if not (r.get("着順") or "").isdigit():
                continue
            nk = _num(r.get("人気"))
            j = (r.get("騎手") or "").strip()
            if not nk or not j:
                continue
            out.append({
                "騎手": j, "年": stem[:4], "場": venue,
                "馬場種別": m["馬場種別"], "距離帯": band,
                "着順": int(r["着順"]), "人気": int(nk),
                "単勝オッズ": _num(r.get("単勝オッズ")),
            })
    return out


def popularity_rates(rows):
    """人気ごとの勝率・複勝率。期待値の物差し。"""
    w = defaultdict(lambda: [0, 0])
    p = defaultdict(lambda: [0, 0])
    for r in rows:
        k = min(r["人気"], 18)
        w[k][1] += 1
        p[k][1] += 1
        if r["着順"] == 1:
            w[k][0] += 1
        if r["着順"] <= 3:
            p[k][0] += 1
    return ({k: a / b for k, (a, b) in w.items() if b},
            {k: a / b for k, (a, b) in p.items() if b})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["nar", "jra"], default="jra")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    import keiba.profile as profile
    prof = profile.use(args.profile)
    info = {r["stem"]: r for r in csv.DictReader(
        open(prof.path("race_info.csv"), encoding="utf-8-sig"))}
    d = Path(args.dir or ("data/collected" if args.profile == "nar"
                          else "data/collected_jra"))
    rows = load_rows(d, info)
    pwin, pplc = popularity_rates(rows)
    print(f"延べ {len(rows):,}頭 / 騎手 {len({r['騎手'] for r in rows}):,}人")

    # 同じ1頭を複数の粒度に足す。使う側は必要な粒度の行だけ引けばよい
    agg = defaultdict(lambda: {"騎乗": 0, "勝": 0, "複": 0,
                               "期待勝": 0.0, "期待複": 0.0, "単勝払戻": 0})
    for r in rows:
        pw = pwin.get(min(r["人気"], 18), 0.0)
        pp = pplc.get(min(r["人気"], 18), 0.0)
        ret = (r["単勝オッズ"] * 100 if r["着順"] == 1 and r["単勝オッズ"] else 0)
        keys = [
            (r["騎手"], r["年"], ALL, ALL, ALL),               # 年ごとの通算
            (r["騎手"], r["年"], r["場"], ALL, ALL),           # 場別
            (r["騎手"], r["年"], ALL, r["馬場種別"], ALL),      # 芝ダ別
            (r["騎手"], r["年"], ALL, ALL, r["距離帯"]),        # 距離帯別
            (r["騎手"], r["年"], r["場"], r["馬場種別"], r["距離帯"]),  # 全部指定
        ]
        for k in set(keys):
            a = agg[k]
            a["騎乗"] += 1
            a["勝"] += 1 if r["着順"] == 1 else 0
            a["複"] += 1 if r["着順"] <= 3 else 0
            a["期待勝"] += pw
            a["期待複"] += pp
            a["単勝払戻"] += ret

    out = Path(args.out or prof.path("jockey_stats.csv"))
    out.parent.mkdir(parents=True, exist_ok=True)
    # BOM付きUTF-8。WindowsのExcelが文字コードを取り違えないようにする
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for (j, y, v, s, b), a in sorted(agg.items()):
            w.writerow({"騎手": j, "年": y, "場": v, "馬場種別": s, "距離帯": b,
                        "騎乗": a["騎乗"], "勝": a["勝"], "複": a["複"],
                        "期待勝": round(a["期待勝"], 3),
                        "期待複": round(a["期待複"], 3),
                        "単勝払戻": a["単勝払戻"]})
    print(f"{len(agg):,}行 → {out}")


if __name__ == "__main__":
    main()
