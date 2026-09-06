#!/usr/bin/env python3
"""LightGBM で着内確率を学習し、回収率で評価する。

**必ず ml/PREREG.md を先に読むこと。** 分割・特徴量・戦略・ハイパーパラメータ・
「効かなかった」の定義は、結果を見る前に固定してある。

問いは1つだけ:
    勾配ブースティングは、単勝オッズが持っていない情報を見つけられるか。

そのため3つを必ず並べる:
    A 市場なし  オッズ・人気を入れない
    B 市場あり  A + log(単勝オッズ) + 人気
    C 対照      人気順（モデルを使わない）

B が C を上回らなければ、モデルは市場を作り直しただけである。

    python3 scripts/lgbm.py --dir data/collected_jra
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

STAKE = 100

# 事前登録で固定。探索しない
PARAMS = {
    "objective": "binary",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 200,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 10.0,
    "verbose": -1,
    "seed": 0,
    "num_threads": 4,
}
NUM_ROUNDS = 3000
EARLY_STOP = 100

# 事前登録で固定した4戦略のみ
STRATEGIES = [
    ("馬連", 4), ("馬連", 5), ("ワイド", 3), ("ワイド", 4),
]

CAT_COLS = ["脚質", "騎手", "血統父", "血統母父", "馬場種別", "馬場",
            "天候", "クラス", "斤量条件", "格", "開催場", "性別"]
MARKET_COLS = ["log単勝オッズ", "人気"]


# ---------------------------------------------------------------- 読み込み

def race_date(stem: str) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", stem)
    return m.group(1) if m else ""


def race_number(stem: str):
    m = re.search(r"_\D+?(\d{2})R_", stem)
    return int(m.group(1)) if m else None


def race_venue(stem: str) -> str:
    m = re.search(r"_(\D+?)\d{2}R_", stem)
    return m.group(1) if m else ""


def _num(x, default=None):
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return default


def parse_bataiju(text: str):
    """'538(+4)' → (538.0, 4.0)"""
    if not text:
        return None, None
    m = re.match(r"\s*(\d+)\s*\(([-+]?\d+)\)", text)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.match(r"\s*(\d+)", text)
    return (float(m.group(1)), None) if m else (None, None)


def parse_seirei(text: str):
    """'牡5' → ('牡', 5)"""
    if not text:
        return "", None
    sex = text[0]
    age = _num(text[1:])
    return sex, age


def load_race_info(path: Path) -> dict:
    if not path.exists():
        return {}
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        out[r["stem"]] = r
    return out


def load_races(directory: Path, races: set[int]) -> list[dict]:
    """収集済みCSVから、着順・払戻・出走馬が揃ったレースだけ返す。"""
    out = []
    stems = sorted({p.name[: -len("_結果.csv")]
                    for p in directory.glob("*_結果.csv")})
    for stem in stems:
        rn = race_number(stem)
        if rn is None or rn not in races:
            continue
        ent = directory / f"{stem}_出走馬.csv"
        res = directory / f"{stem}_結果.csv"
        pay = directory / f"{stem}_配当.csv"
        if not (ent.exists() and pay.exists()):
            continue

        rows = [r for r in csv.DictReader(open(res, encoding="utf-8-sig"))
                if (r.get("着順") or "").isdigit()]
        if len(rows) < 5:
            continue
        rows.sort(key=lambda r: int(r["着順"]))
        order = [int(r["馬番"]) for r in rows if (r.get("馬番") or "").isdigit()]
        if len(order) < 3:
            continue
        chaku = {int(r["馬番"]): int(r["着順"]) for r in rows
                 if (r.get("馬番") or "").isdigit()}

        payouts = {}
        for p in csv.DictReader(open(pay, encoding="utf-8-sig")):
            try:
                combo = frozenset(int(x) for x in p["組み合わせ"].split("-"))
                payouts.setdefault(p["券種"], {})[combo] = int(p["配当"])
            except (ValueError, KeyError):
                continue

        entries = [r for r in csv.DictReader(open(ent, encoding="utf-8-sig"))
                   if (r.get("馬番") or "").strip().isdigit()]
        if len(entries) < 5:
            continue

        out.append({
            "stem": stem, "date": race_date(stem), "venue": race_venue(stem),
            "entries": entries, "chaku": chaku, "payouts": payouts,
            "top2": frozenset(order[:2]), "top3": frozenset(order[:3]),
        })
    return out


# ---------------------------------------------------------------- 履歴

def build_history(races: list[dict]) -> dict:
    """馬名 → [(日付, 着順, 頭数, 開催場, 距離帯)] を日付順で持つ。

    特徴量を作るときは必ず「当該レース日より前」だけを使う。
    """
    hist = defaultdict(list)
    for r in races:
        n = len(r["entries"])
        for e in r["entries"]:
            name = (e.get("馬名") or "").strip()
            uma = int(e["馬番"])
            ch = r["chaku"].get(uma)
            if not name or ch is None:
                continue
            hist[name].append((r["date"], ch, n, r["venue"], r.get("band", "")))
    for v in hist.values():
        v.sort()
    return hist


def dist_band(kyori) -> str:
    if not kyori:
        return ""
    k = int(kyori)
    return "短" if k <= 1400 else "中" if k <= 1800 else "長"


def history_features(hist, name, date, venue, band) -> dict:
    """当該レース日より前の成績だけから作る。"""
    past = [h for h in hist.get(name, ()) if h[0] < date]
    if not past:
        return {"履歴_出走数": 0, "履歴_着内率": np.nan, "履歴_平均着順": np.nan,
                "履歴_同場着内率": np.nan, "履歴_同距離着内率": np.nan}
    n = len(past)
    same_v = [h for h in past if h[3] == venue]
    same_b = [h for h in past if h[4] == band]
    return {
        "履歴_出走数": n,
        "履歴_着内率": sum(1 for h in past if h[1] <= 3) / n,
        "履歴_平均着順": sum(h[1] for h in past) / n,
        "履歴_同場着内率": (sum(1 for h in same_v if h[1] <= 3) / len(same_v)
                       if same_v else np.nan),
        "履歴_同距離着内率": (sum(1 for h in same_b if h[1] <= 3) / len(same_b)
                        if same_b else np.nan),
    }


# ---------------------------------------------------------------- 特徴量

def make_rows(races: list[dict], info: dict, hist: dict) -> list[dict]:
    rows = []
    for r in races:
        meta = info.get(r["stem"], {})
        kyori = _num(meta.get("距離"))
        band = dist_band(kyori)
        n = len(r["entries"])
        for e in r["entries"]:
            uma = int(e["馬番"])
            ch = r["chaku"].get(uma)
            if ch is None:
                continue
            name = (e.get("馬名") or "").strip()
            sex, age = parse_seirei(e.get("性齢", ""))
            bw, bwd = parse_bataiju(e.get("馬体重", ""))
            odds = _num(e.get("単勝オッズ"))
            ninki = _num(e.get("人気"))
            row = {
                "stem": r["stem"], "date": r["date"], "馬番": uma,
                "着内": 1 if ch <= 3 else 0, "着順": ch,
                # --- 出走馬CSV
                "枠番": _num(e.get("枠番")), "性別": sex, "年齢": age,
                "脚質": (e.get("脚質") or "").strip(),
                "馬体重": bw, "馬体重増減": bwd,
                "前走着順": _num(e.get("前走着順")),
                "前走間隔日数": _num(e.get("前走間隔日数")),
                "上がり3F": _num(e.get("上がり3F")),
                "転入初戦": 1 if (e.get("転入初戦") or "").strip() else 0,
                "長期休養明け": 1 if (e.get("長期休養明け") or "").strip() else 0,
                "直近3走JRA数": _num(e.get("直近3走JRA数")),
                "騎手": (e.get("騎手") or "").strip(),
                "血統父": (e.get("血統父") or "").strip(),
                "血統母父": (e.get("血統母父") or "").strip(),
                # --- レース条件
                "距離": kyori, "頭数": n, "馬番比": uma / n if n else np.nan,
                "馬場種別": meta.get("馬場種別", ""), "馬場": meta.get("馬場", ""),
                "天候": meta.get("天候", ""), "クラス": meta.get("クラス", ""),
                "斤量条件": meta.get("斤量条件", ""), "格": meta.get("格", ""),
                "開催場": r["venue"],
                # --- 市場（セットBでのみ使う）
                "log単勝オッズ": math.log(odds) if odds and odds > 0 else np.nan,
                "人気": ninki,
            }
            row.update(history_features(hist, name, r["date"], r["venue"], band))
            rows.append(row)
    return rows


def to_matrix(rows, feats, cats, cat_maps):
    X = np.full((len(rows), len(feats)), np.nan, dtype=np.float64)
    for j, f in enumerate(feats):
        if f in cats:
            m = cat_maps[f]
            for i, r in enumerate(rows):
                v = m.get(r.get(f))
                X[i, j] = np.nan if v is None else v
        else:
            for i, r in enumerate(rows):
                v = r.get(f)
                X[i, j] = np.nan if v is None else float(v)
    return X


# ---------------------------------------------------------------- 評価

def settle(kind, tickets, race):
    table = race["payouts"].get(kind, {})
    inv = len(tickets) * STAKE
    ret = 0
    for t in tickets:
        hit = (t <= race["top3"]) if kind == "ワイド" else (t == race["top2"])
        if hit:
            ret += table.get(t, 0)
    return inv, ret


def bootstrap(pairs, n=10000, seed=0):
    if not pairs:
        return 0.0, 0.0, 0.0
    rnd = random.Random(seed)
    N = len(pairs)
    rates = []
    for _ in range(n):
        inv = ret = 0
        for _ in range(N):
            i, r = pairs[rnd.randrange(N)]
            inv += i
            ret += r
        rates.append(ret / inv if inv else 0.0)
    rates.sort()
    lo = rates[int(0.05 * n)]
    hi = rates[int(0.95 * n) - 1]
    win = sum(1 for x in rates if x >= 1.0) / n
    return lo, hi, win


def evaluate(races, order_by):
    """order_by: stem -> 馬番の並び（買いたい順）。戦略ごとに集計する。"""
    out = {}
    for kind, k in STRATEGIES:
        pairs = []
        for r in races:
            order = order_by.get(r["stem"])
            if not order or len(order) < k:
                continue
            tickets = [frozenset(c) for c in combinations(order[:k], 2)]
            pairs.append(settle(kind, tickets, r))
        if not pairs:
            continue
        inv = sum(i for i, _ in pairs)
        ret = sum(x for _, x in pairs)
        hit = sum(1 for _, x in pairs if x > 0)
        lo, hi, win = bootstrap(pairs)
        out[(kind, k)] = {
            "n": len(pairs), "hit": hit / len(pairs), "roi": ret / inv,
            "lo": lo, "hi": hi, "win": win,
        }
    return out


def order_from_scores(rows, scores):
    by = defaultdict(list)
    for r, s in zip(rows, scores):
        by[r["stem"]].append((s, r["馬番"]))
    return {k: [u for _, u in sorted(v, key=lambda x: -x[0])] for k, v in by.items()}


def order_from_ninki(rows):
    by = defaultdict(list)
    for r in rows:
        nk = r.get("人気")
        by[r["stem"]].append((nk if nk and nk == nk else 99, r["馬番"]))
    return {k: [u for _, u in sorted(v, key=lambda x: x[0])] for k, v in by.items()}


def print_table(title, res):
    print(f"\n── {title} " + "─" * max(0, 50 - len(title)))
    print(f"{'戦略':<14}{'R数':>6}{'的中率':>7}{'回収率':>7}{'90%区間':>17}{'100%超':>7}")
    for kind, k in STRATEGIES:
        d = res.get((kind, k))
        if not d:
            continue
        pts = k * (k - 1) // 2
        ci = "{:.0%} 〜 {:.0%}".format(d["lo"], d["hi"])
        name = "{} 上位{}頭({}点)".format(kind, k, pts)
        print(f"{name:<14}{d['n']:>6}{d['hit']:>7.0%}"
              f"{d['roi']:>7.0%}{ci:>17}{d['win']:>7.0%}")


# ---------------------------------------------------------------- 本体

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--race-info", default="data/profiles/jra/race_info.csv")
    ap.add_argument("--races", default="9,10,11,12")
    ap.add_argument("--out", default="ml/result.json")
    args = ap.parse_args()

    import lightgbm as lgb

    wanted = {int(x) for x in args.races.split(",")}
    races = load_races(Path(args.dir), wanted)
    info = load_race_info(Path(args.race_info))
    print(f"収集済み {len(races)}レース / race_info {len(info)}件")

    # 距離帯を履歴に持たせるため先に付ける
    for r in races:
        r["band"] = dist_band(_num(info.get(r["stem"], {}).get("距離")))

    hist = build_history(races)
    rows = make_rows(races, info, hist)
    print(f"延べ {len(rows)}頭")

    # 事前登録の分割（時系列）
    def pick(rows, lo, hi):
        return [r for r in rows if lo <= r["date"] <= hi]

    tr = pick(rows, "2023-01-01", "2024-08-31")
    es = pick(rows, "2024-09-01", "2024-12-31")
    va = pick(rows, "2025-01-01", "2025-12-31")
    te = pick(rows, "2026-01-01", "2026-12-31")
    print(f"学習{len(tr)} / 早期打ち切り{len(es)} / 検証{len(va)} / 試験{len(te)} 頭")
    for nm, part in (("学習", tr), ("早期打ち切り", es), ("検証", va), ("試験", te)):
        print(f"  {nm}: {len({r['stem'] for r in part})}レース")

    base_feats = [k for k in rows[0]
                  if k not in ("stem", "date", "着内", "着順", "馬番")
                  and k not in MARKET_COLS]
    sets = {"A 市場なし": base_feats, "B 市場あり": base_feats + MARKET_COLS}

    races_by = {r["stem"]: r for r in races}
    va_races = [races_by[s] for s in {r["stem"] for r in va}]
    te_races = [races_by[s] for s in {r["stem"] for r in te}]

    report = {"n_races": len(races), "sets": {}}

    # --- C 対照（人気順）
    for label, part, rs in (("検証(2025)", va, va_races), ("試験(2026)", te, te_races)):
        res = evaluate(rs, order_from_ninki(part))
        print_table(f"C 対照・人気順  {label}", res)
        report["sets"].setdefault("C 対照(人気順)", {})[label] = {
            f"{k}{n}": v for (k, n), v in res.items()}

    # --- A / B
    for name, feats in sets.items():
        cats = [c for c in CAT_COLS if c in feats]
        cat_maps = {}
        for c in cats:
            vals = sorted({r.get(c) for r in tr if r.get(c)})
            cat_maps[c] = {v: i for i, v in enumerate(vals)}
        Xtr = to_matrix(tr, feats, cats, cat_maps)
        Xes = to_matrix(es, feats, cats, cat_maps)
        ytr = np.array([r["着内"] for r in tr])
        yes = np.array([r["着内"] for r in es])
        cat_idx = [feats.index(c) for c in cats]

        dtr = lgb.Dataset(Xtr, ytr, feature_name=feats,
                          categorical_feature=cat_idx, free_raw_data=False)
        des = lgb.Dataset(Xes, yes, reference=dtr, feature_name=feats,
                          categorical_feature=cat_idx, free_raw_data=False)
        model = lgb.train(PARAMS, dtr, NUM_ROUNDS, valid_sets=[des],
                          callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)])
        print(f"\n【{name}】木の本数 {model.best_iteration} / 特徴量 {len(feats)}")

        for label, part, rs in (("検証(2025)", va, va_races),
                                ("試験(2026)", te, te_races)):
            X = to_matrix(part, feats, cats, cat_maps)
            p = model.predict(X, num_iteration=model.best_iteration)
            y = np.array([r["着内"] for r in part])
            # AUC は補助情報
            o = np.argsort(p)
            ranks = np.empty(len(p)); ranks[o] = np.arange(len(p))
            pos, neg = y.sum(), (1 - y).sum()
            auc = ((ranks[y == 1].sum() - pos * (pos - 1) / 2) / (pos * neg)
                   if pos and neg else float("nan"))
            res = evaluate(rs, order_from_scores(part, p))
            print_table(f"{name}  {label}  (AUC {auc:.3f})", res)
            report["sets"].setdefault(name, {})[label] = {
                "auc": auc, **{f"{k}{n}": v for (k, n), v in res.items()}}

        imp = sorted(zip(feats, model.feature_importance("gain")),
                     key=lambda x: -x[1])[:15]
        print(f"\n  寄与の大きい特徴量（{name}）")
        for f, g in imp:
            print(f"    {f:<16}{g:>12,.0f}")
        report["sets"][name]["importance"] = [[f, float(g)] for f, g in imp]

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"\n→ {args.out}")


if __name__ == "__main__":
    main()
