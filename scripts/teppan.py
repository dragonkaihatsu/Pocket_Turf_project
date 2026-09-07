#!/usr/bin/env python3
"""1番人気（鉄板）が来る条件・飛ぶ条件をまとめる。

これは買い目を作る道具ではなく、**レースの読みやすさを事前に測る道具**である。
中央の1番人気は勝率31%・複勝率63%しかなく、どのレースで信用してよいかを
分けられれば「見送り」の判断材料になる。

2本立てにする。どちらも欠かせない。

  1. 条件ごとの実測表（単独条件）。前半2年と後半2年で再現するかを必ず見る
  2. LightGBM（条件の重なりを見る）。**校正表**を必ず出す。
     「80%と言ったレースが実際に80%来るか」を確かめないと、
     予測値は数字が付いているだけの飾りになる

学習2023-24 / 試験2025-26。試験年の数字は最後にまとめて見る。

    python3 scripts/teppan.py --profile jra
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

PARAMS = {
    "objective": "binary", "learning_rate": 0.05, "num_leaves": 15,
    "min_data_in_leaf": 50, "feature_fraction": 0.8, "bagging_fraction": 0.8,
    "bagging_freq": 1, "lambda_l2": 10.0, "verbose": -1, "seed": 0,
    "num_threads": 4,
}
CAT_COLS = ["馬場種別", "馬場", "天候", "開催場", "クラス", "格", "斤量条件",
            "脚質", "性別", "騎手", "血統父"]


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - s) / d, (c + s) / d


def _num(x, default=None):
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return default


def race_number(stem):
    m = re.search(r"_\D+?(\d{2})R_", stem)
    return int(m.group(1)) if m else None


def race_venue(stem):
    m = re.search(r"_(\D+?)\d{2}R_", stem)
    return m.group(1) if m else ""


def dist_band(k):
    if not k:
        return ""
    k = int(k)
    return "〜1400m" if k <= 1400 else "1401-1800m" if k <= 1800 else "1801m〜"


def head_band(n):
    if not n:
        return ""
    n = int(n)
    return "〜9頭" if n <= 9 else "10-12頭" if n <= 12 else "13-15頭" if n <= 15 else "16頭〜"


def odds_band(o):
    if not o:
        return "不明"
    return "1倍台" if o < 2 else "2倍台" if o < 3 else "3倍台" if o < 4 else "4倍〜"


def parse_bataiju(t):
    if not t:
        return None, None
    m = re.match(r"\s*(\d+)\s*\(([-+]?\d+)\)", t)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.match(r"\s*(\d+)", t)
    return (float(m.group(1)), None) if m else (None, None)


def parse_seirei(t):
    if not t:
        return "", None
    return t[0], _num(t[1:])


def build(directory: Path, info: dict, races: set[int]):
    """1レース1行。1番人気の馬の情報と、レース条件をまとめる。"""
    rows = []
    hist = defaultdict(list)          # 馬名 -> [(日付, 着順)]
    stems = sorted({p.name[: -len("_結果.csv")]
                    for p in directory.glob("*_結果.csv")})

    # 先に全レースの着順を読んで履歴を作る（使うときに日付で切る）
    cache = {}
    for stem in stems:
        rn = race_number(stem)
        if rn is None or rn not in races:
            continue
        ent = directory / f"{stem}_出走馬.csv"
        res = directory / f"{stem}_結果.csv"
        if not ent.exists():
            continue
        rres = [r for r in csv.DictReader(open(res, encoding="utf-8-sig"))
                if (r.get("着順") or "").isdigit()]
        if len(rres) < 5:
            continue
        chaku = {int(r["馬番"]): int(r["着順"]) for r in rres
                 if (r.get("馬番") or "").isdigit()}
        ents = [e for e in csv.DictReader(open(ent, encoding="utf-8-sig"))
                if (e.get("馬番") or "").strip().isdigit()]
        if not ents:
            continue
        cache[stem] = (ents, chaku)
        for e in ents:
            nm = (e.get("馬名") or "").strip()
            ch = chaku.get(int(e["馬番"]))
            if nm and ch:
                hist[nm].append((stem[:10], ch))
    for v in hist.values():
        v.sort()

    for stem, (ents, chaku) in cache.items():
        fav = None
        for e in ents:
            nk = _num(e.get("人気"))
            if nk and (fav is None or nk < _num(fav.get("人気"), 99)):
                fav = e
        if fav is None:
            continue
        uma = int(fav["馬番"])
        ch = chaku.get(uma)
        if ch is None:
            continue
        odds = sorted(o for o in (_num(e.get("単勝オッズ")) for e in ents) if o)
        if len(odds) < 3:
            continue
        # 市場確率のエントロピー（0=1頭に集中 / 1=拮抗）
        inv = [1 / o for o in odds]
        s = sum(inv)
        ps = [x / s for x in inv]
        ent_val = (-sum(p * math.log(p) for p in ps if p > 0)
                   / math.log(len(ps))) if len(ps) > 1 else 0.0

        date = stem[:10]
        nm = (fav.get("馬名") or "").strip()
        past = [h for h in hist.get(nm, ()) if h[0] < date]
        m = info.get(stem, {})
        sex, age = parse_seirei(fav.get("性齢", ""))
        bw, bwd = parse_bataiju(fav.get("馬体重", ""))
        n_head = _num(m.get("頭数")) or len(ents)

        rows.append({
            "stem": stem, "year": stem[:4], "date": date,
            "着内": 1 if ch <= 3 else 0, "勝ち": 1 if ch == 1 else 0,
            "着順": ch,
            # --- 市場
            "1番人気オッズ": odds[0], "log1番人気オッズ": math.log(odds[0]),
            "2番人気オッズ": odds[1], "オッズ比": odds[1] / odds[0],
            "エントロピー": ent_val,
            "1番人気オッズ帯": odds_band(odds[0]),
            # --- レース条件
            "頭数": n_head, "頭数帯": head_band(n_head),
            "距離": _num(m.get("距離")), "距離帯": dist_band(m.get("距離")),
            "馬場種別": m.get("馬場種別", "") or "不明",
            "馬場": m.get("馬場", "") or "不明",
            "天候": m.get("天候", "") or "不明",
            "開催場": race_venue(stem),
            "クラス": m.get("クラス", "") or "不明",
            "格": m.get("格") or "平場",
            "斤量条件": m.get("斤量条件", "") or "不明",
            "R": race_number(stem),
            # --- 1番人気の馬
            "枠番": _num(fav.get("枠番")), "馬番": uma,
            "馬番比": uma / n_head if n_head else np.nan,
            "性別": sex, "年齢": age,
            "脚質": (fav.get("脚質") or "").strip() or "不明",
            "馬体重": bw, "馬体重増減": bwd,
            "前走着順": _num(fav.get("前走着順")),
            "前走間隔日数": _num(fav.get("前走間隔日数")),
            "上がり3F": _num(fav.get("上がり3F")),
            "長期休養明け": 1 if (fav.get("長期休養明け") or "").strip() else 0,
            "直近3走JRA数": _num(fav.get("直近3走JRA数")),
            "騎手": (fav.get("騎手") or "").strip(),
            "血統父": (fav.get("血統父") or "").strip(),
            "履歴_出走数": len(past),
            "履歴_着内率": (sum(1 for h in past if h[1] <= 3) / len(past)
                        if past else np.nan),
        })
    return rows


def cross(rows, key, target="着内", min_n=60):
    groups = defaultdict(list)
    for r in rows:
        v = r.get(key)
        if v not in (None, ""):
            groups[v].append(r)
    out = []
    for name, g in groups.items():
        if len(g) < min_n:
            continue
        k = sum(r[target] for r in g)
        lo, hi = wilson(k, len(g))
        out.append((name, len(g), k / len(g), lo, hi,
                    sum(r["勝ち"] for r in g) / len(g)))
    out.sort(key=lambda x: -x[2])
    if not out:
        return []
    print(f"\n── {key} " + "─" * 46)
    print(f"{'区分':<12}{'R数':>6}{'着内率':>7}{'95%区間':>15}{'勝率':>7}"
          f"{'前半':>8}{'後半':>8}{'向き':>5}")
    early = [r for r in rows if r["year"] in ("2023", "2024")]
    late = [r for r in rows if r["year"] in ("2025", "2026")]
    base = sum(r[target] for r in rows) / len(rows)
    for name, n, rate, lo, hi, win in out:
        a = [r for r in early if r.get(key) == name]
        b = [r for r in late if r.get(key) == name]
        ra = sum(r[target] for r in a) / len(a) if len(a) >= 20 else None
        rb = sum(r[target] for r in b) / len(b) if len(b) >= 20 else None
        same = "—"
        if ra is not None and rb is not None:
            same = "○" if (ra >= base) == (rb >= base) else "×"
        ci = f"{lo:.0%}〜{hi:.0%}"
        sa = f"{ra:.0%}" if ra is not None else "—"
        sb = f"{rb:.0%}" if rb is not None else "—"
        print(f"{str(name):<12}{n:>6}{rate:>7.1%}{ci:>15}{win:>7.1%}"
              f"{sa:>8}{sb:>8}{same:>5}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=["nar", "jra"], default="jra")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--races", default="9,10,11,12")
    args = ap.parse_args()

    import lightgbm as lgb
    import keiba.profile as profile
    prof = profile.use(args.profile)
    info = {}
    p = prof.path("race_info.csv")
    if p.exists():
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            info[r["stem"]] = r
    d = Path(args.dir or ("data/collected" if args.profile == "nar"
                          else "data/collected_jra"))
    rows = build(d, info, {int(x) for x in args.races.split(",")})
    base = sum(r["着内"] for r in rows) / len(rows)
    win = sum(r["勝ち"] for r in rows) / len(rows)
    label = "中央" if args.profile == "jra" else "地方"
    print(f"{label} {args.races}R {len(rows)}レース")
    print(f"1番人気の全体: 勝率 {win:.1%} / 着内率 {base:.1%}")
    print("「向き」○＝前半2年と後半2年が全体平均に対して同じ側にある（再現した）")

    print("\n" + "=" * 70)
    print("【1】条件ごとの実測（1番人気の着内率）")
    print("=" * 70)
    for key in ("1番人気オッズ帯", "頭数帯", "距離帯", "馬場種別", "馬場",
                "クラス", "格", "斤量条件", "脚質", "開催場", "R"):
        cross(rows, key)

    print("\n" + "=" * 70)
    print("【2】LightGBM（条件の重なりを見る）")
    print("=" * 70)
    tr = [r for r in rows if r["year"] in ("2023", "2024")]
    te = [r for r in rows if r["year"] in ("2025", "2026")]
    tr.sort(key=lambda r: r["date"])
    cut = int(len(tr) * 0.8)
    tr, es = tr[:cut], tr[cut:]
    print(f"学習{len(tr)} / 早期打ち切り{len(es)} / 試験{len(te)} レース")

    drop = {"stem", "year", "date", "着内", "勝ち", "着順",
            "1番人気オッズ帯", "頭数帯", "距離帯"}
    feats = [k for k in rows[0] if k not in drop]
    cats = [c for c in CAT_COLS if c in feats]
    cmaps = {c: {v: i for i, v in enumerate(sorted({r.get(c) for r in tr if r.get(c)}))}
             for c in cats}

    def mat(part):
        X = np.full((len(part), len(feats)), np.nan)
        for j, f in enumerate(feats):
            for i, r in enumerate(part):
                v = cmaps[f].get(r.get(f)) if f in cats else r.get(f)
                X[i, j] = np.nan if v is None else float(v)
        return X

    cat_idx = [feats.index(c) for c in cats]
    dtr = lgb.Dataset(mat(tr), np.array([r["着内"] for r in tr]),
                      feature_name=feats, categorical_feature=cat_idx)
    des = lgb.Dataset(mat(es), np.array([r["着内"] for r in es]), reference=dtr,
                      feature_name=feats, categorical_feature=cat_idx)
    model = lgb.train(PARAMS, dtr, 2000, valid_sets=[des],
                      callbacks=[lgb.early_stopping(100, verbose=False)])
    pte = model.predict(mat(te), num_iteration=model.best_iteration)
    yte = np.array([r["着内"] for r in te])
    o = np.argsort(pte)
    ranks = np.empty(len(pte)); ranks[o] = np.arange(len(pte))
    pos, neg = yte.sum(), (1 - yte).sum()
    auc = (ranks[yte == 1].sum() - pos * (pos - 1) / 2) / (pos * neg)
    print(f"木の本数 {model.best_iteration} / 試験年のAUC {auc:.3f}")

    print("\n  校正表（予測が当たっているか）— 試験年2025-26")
    print(f"  {'予測の帯':<14}{'R数':>6}{'予測平均':>9}{'実際の着内率':>13}{'95%区間':>15}")
    edges = [0, .45, .55, .62, .68, .75, 1.01]
    for lo_e, hi_e in zip(edges, edges[1:]):
        idx = [i for i, v in enumerate(pte) if lo_e <= v < hi_e]
        if len(idx) < 30:
            continue
        k = int(yte[idx].sum())
        lo, hi = wilson(k, len(idx))
        ci = f"{lo:.0%}〜{hi:.0%}"
        print(f"  {f'{lo_e:.0%}〜{hi_e:.0%}':<14}{len(idx):>6}"
              f"{np.mean(pte[idx]):>9.1%}{k/len(idx):>13.1%}{ci:>15}")

    print("\n  寄与の大きい特徴量")
    for f, g in sorted(zip(feats, model.feature_importance("gain")),
                       key=lambda x: -x[1])[:15]:
        print(f"    {f:<16}{g:>12,.0f}")


if __name__ == "__main__":
    main()
