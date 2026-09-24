#!/usr/bin/env python3
"""G1ペース・シミュレーターの材料を作る（`data/profiles/jra/pace_sim.json`）。

    python3 scripts/build_pace_sim.py

「スロー／ミドル／ハイを入力してアニメーションにする。G1のみで確認できる
シミュレーター」（本人の言葉・2026-09-24）の数字を、**すべて収集済みの
結果・通過順・出走馬CSVから測る**。動きを見せる都合で値を作ることはしない。

## 何を測るか

1. ペース指標（`keiba/tenkai.py` の定義そのまま）
       素 = 勝ち馬の(前半の1F平均) − (上がり3Fの1F平均)
       指標 = 同じ(場×芝ダ×距離)の平均からの残差   正ならスロー
   既存の `pace.json` は2025-01以降しか無く、2024年のG1が入っていない
   ので、1-12R・全期間で作り直す（既存分との一致は実行時に表示する）
2. スロー／ミドル／ハイの境目 = 芝ダ別に残差の3分位
3. 3帯それぞれの
     - 4コーナーの1頭あたり間隔（馬身）と先頭〜最後方（馬身）
     - 脚質ごとの4コーナー位置（0=先頭／1=最後方）の平均
     - 脚質ごとの勝率・3着内率（母数つき）
     - 着順ごとの勝ち馬からの着差（馬身）の中央値
4. G1 60レースの実際の隊列（4コーナーの馬身差）と着差 — 再生用

G1 は `race_info.csv` の等級が埋まっている2024年の24レース名で判定する
（2025年以降は等級列がほぼ空なので、同じレース名で拾う。障害G1は除く）。
"""
from __future__ import annotations

import csv
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.courses import COURSES
from keiba.models import parse_agari_3f
from keiba.racefiles import VENUE_NO_RE, result_files
from keiba.tenkai import GAP, pace_raw, parse_corner, spread_per_horse

D = Path("data/collected_jra")
OUT = Path("data/profiles/jra/pace_sim.json")
KYAKU = ("逃げ", "先行", "差し", "追込")
PACES = ("スロー", "ミドル", "ハイ")

# 着差の表記 → 馬身
MARGIN = {"ハナ": 0.1, "アタマ": 0.2, "クビ": 0.3, "同着": 0.0, "大差": 10.0}


def margin_len(s: str) -> float | None:
    s = (s or "").strip()
    if not s:
        return None
    if s in MARGIN:
        return MARGIN[s]
    m = re.fullmatch(r"(\d+)?(?:\.?(\d)/(\d))?", s)
    if not m or not (m.group(1) or m.group(2)):
        return None
    v = float(m.group(1) or 0)
    if m.group(2):
        v += int(m.group(2)) / int(m.group(3))
    return v


def secs(t: str) -> float | None:
    m = re.fullmatch(r"(?:(\d+):)?(\d+\.\d)", (t or "").strip())
    if not m:
        return None
    return int(m.group(1) or 0) * 60 + float(m.group(2))


def corner_lengths(s: str) -> list[tuple[int, float, int, int]]:
    """4コーナーの通過順を (馬番, 先頭からの馬身, 何番目のかたまりか, かたまり内の並び) にする。

    馬身は `keiba/tenkai.field_spread` と同じ換算で、**括弧の外にある記号だけを
    数える**（括弧内は併走、記号の無い区切りは0馬身）。帯ごとの間隔の実測も
    この換算なので、再生と帯の数字が同じ物差しになる。
    馬番の桁が連結された表記は tenkai と同じく読まずに捨てる。
    """
    out, cur, depth = [], 0.0, 0
    grp, lane = -1, 0
    for t in re.findall(r"\(|\)|\d+|[,\-=]", (s or "").replace("*", "")):
        if t == "(":
            depth += 1
            grp += 1
            lane = 0
        elif t == ")":
            depth -= 1
        elif t in GAP:
            if depth == 0:
                cur += GAP[t]
        else:
            v = int(t)
            if v > 18:
                return []
            if depth == 0:
                grp += 1
                lane = 0
            out.append((v, cur, grp, lane))
            lane += 1
    return out


def load_cond() -> dict[str, dict]:
    with open("data/profiles/jra/race_info.csv", encoding="utf-8-sig") as f:
        return {r["stem"]: r for r in csv.DictReader(f)}


def g1_names(cond: dict[str, dict]) -> set[str]:
    return {r["レース名"] for r in cond.values()
            if r.get("等級") == "G1" and r.get("馬場種別") in ("芝", "ダ")}


def main() -> int:
    cond = load_cond()
    names = g1_names(cond)
    races = []
    for res in result_files(D, "1-12"):
        stem = res.name[: -len("_結果.csv")]
        c = cond.get(stem)
        if not c or c.get("馬場種別") not in ("芝", "ダ") or not c["距離"].isdigit():
            continue
        m = VENUE_NO_RE.search(stem)
        if not m:
            continue
        rows = [r for r in csv.DictReader(open(res, encoding="utf-8-sig"))
                if (r.get("着順") or "").isdigit()]
        if len(rows) < 5:
            continue
        win = next((r for r in rows if r["着順"] == "1"), None)
        kyori = int(c["距離"])
        raw = None
        if win:
            raw = pace_raw(secs(win.get("タイム")), parse_agari_3f(win.get("上がり3F")), kyori)
        corner = ""
        tp = res.with_name(f"{stem}_通過順.csv")
        if tp.exists():
            cs = [r for r in csv.DictReader(open(tp, encoding="utf-8-sig"))
                  if (r.get("通過順") or "").strip()]
            corner = cs[-1]["通過順"] if cs else ""
        # 4コーナー先頭の馬で測ったペース。勝ち馬で測ると
        # 「差し馬が勝つ＝上がりが速い＝スローと読む」循環が入る（下の注記）。
        # 先頭の馬の (タイム − 上がり3F) はレース前半の通過そのものなので、
        # 誰が勝ったかに引きずられない
        lead_raw = None
        order = parse_corner(corner, len(rows)) if corner else None
        if order:
            lead = next((r for r in rows if r["馬番"] == str(order[0])), None)
            if lead:
                lead_raw = pace_raw(secs(lead.get("タイム")),
                                    parse_agari_3f(lead.get("上がり3F")), kyori)
        kyaku = {}
        ep = res.with_name(f"{stem}_出走馬.csv")
        if ep.exists():
            for e in csv.DictReader(open(ep, encoding="utf-8-sig")):
                if (e.get("馬番") or "").isdigit():
                    kyaku[int(e["馬番"])] = (e.get("脚質") or "").strip()
        base = re.sub(r"\(G\d\)$", "", stem.split("_", 2)[2])
        races.append({"stem": stem, "venue": m.group(1), "surface": c["馬場種別"],
                      "kyori": kyori, "baba": c.get("馬場", ""), "raw": raw,
                      "lead_raw": lead_raw,
                      "corner": corner, "rows": rows, "kyaku": kyaku,
                      "g1": base in names, "name": base})

    # 残差 = 同じ(場×芝ダ×距離)の平均からの差
    def residual(key_raw: str, key_out: str) -> None:
        grp = defaultdict(list)
        for r in races:
            if r[key_raw] is not None:
                grp[(r["venue"], r["surface"], r["kyori"])].append(r[key_raw])
        mean = {k: statistics.fmean(v) for k, v in grp.items() if len(v) >= 5}
        for r in races:
            k = (r["venue"], r["surface"], r["kyori"])
            r[key_out] = (r[key_raw] - mean[k]) if r[key_raw] is not None and k in mean else None

    residual("raw", "pace_win")
    residual("lead_raw", "pace")

    # 既存 pace.json（勝ち馬で測る）との一致＝定義を写し間違えていない確認。
    # そのうえで、帯分けに使う先頭馬版がどれだけ近いかも出す
    old = json.loads(Path("data/profiles/jra/pace.json").read_text(encoding="utf-8"))
    pairs = [(old[r["stem"]], r["pace_win"]) for r in races
             if r["stem"] in old and r["pace_win"] is not None]
    if len(pairs) > 30:
        xs, ys = zip(*pairs)
        print(f"既存pace.jsonとの相関 r={statistics.correlation(xs, ys):+.3f}（{len(pairs):,}本）")
    pairs = [(r["pace_win"], r["pace"]) for r in races
             if r["pace_win"] is not None and r["pace"] is not None]
    xs, ys = zip(*pairs)
    print(f"勝ち馬版と先頭馬版の相関 r={statistics.correlation(xs, ys):+.3f}（{len(pairs):,}本）")

    # 芝ダ別の3分位
    cuts = {}
    for sf in ("芝", "ダ"):
        v = sorted(r["pace"] for r in races if r["surface"] == sf and r["pace"] is not None)
        cuts[sf] = (v[len(v) // 3], v[2 * len(v) // 3])

    def band(r):
        if r["pace"] is None:
            return None
        lo, hi = cuts[r["surface"]]
        return "ハイ" if r["pace"] < lo else ("スロー" if r["pace"] >= hi else "ミドル")

    stats = {}
    for sf in ("芝", "ダ"):
        stats[sf] = {}
        for pb in PACES:
            sel = [r for r in races if r["surface"] == sf and band(r) == pb]
            gaps, spreads = [], []
            pos = defaultdict(list)
            res_k = defaultdict(lambda: [0, 0, 0, 0.0, 0.0])   # n, win, top3, 期待win, 期待top3
            marg = defaultdict(list)
            for r in sel:
                n = len(r["rows"])
                sp = spread_per_horse(r["corner"])
                if sp is not None:
                    gaps.append(sp)
                    spreads.append(sp * (n - 1))
                order = parse_corner(r["corner"], n) if r["corner"] else None
                p4 = {ub: i for i, ub in enumerate(order or [])}
                cum = 0.0
                ok_margin = True
                for row in sorted(r["rows"], key=lambda x: int(x["着順"])):
                    ub = int(row["馬番"]) if row["馬番"].isdigit() else None
                    ch = int(row["着順"])
                    k = r["kyaku"].get(ub, "")
                    if ch > 1:
                        ml = margin_len(row.get("着差"))
                        if ml is None:
                            ok_margin = False
                        elif ok_margin:
                            cum += ml
                    if ok_margin and ch <= 18:
                        marg[ch].append(cum)
                    if k not in KYAKU:
                        continue
                    t = res_k[k]
                    t[0] += 1
                    t[1] += ch == 1
                    t[2] += ch <= 3
                    # 頭数の違いを消すため、頭数どおりの期待値でも数える
                    # （スローは少頭数に寄るので、素の率はどの脚質も上がって見える）
                    t[3] += 1 / n
                    t[4] += min(3, n) / n
                    if ub in p4 and len(order) > 1:
                        pos[k].append(p4[ub] / (len(order) - 1))
            stats[sf][pb] = {
                "races": len(sel),
                "gap": round(statistics.median(gaps), 3) if gaps else None,
                "spread": round(statistics.median(spreads), 1) if spreads else None,
                "kyaku": {k: {"n": res_k[k][0],
                              "win": round(res_k[k][1] / res_k[k][0], 4) if res_k[k][0] else None,
                              "top3": round(res_k[k][2] / res_k[k][0], 4) if res_k[k][0] else None,
                              # 実測÷頭数どおりの期待値（1.0＝頭数どおり）
                              "win_x": round(res_k[k][1] / res_k[k][3], 3) if res_k[k][3] else None,
                              "top3_x": round(res_k[k][2] / res_k[k][4], 3) if res_k[k][4] else None,
                              "pos4": round(statistics.fmean(pos[k]), 3) if pos[k] else None,
                              "pos4_n": len(pos[k])}
                          for k in KYAKU},
                "margin": {str(c): round(statistics.median(v), 2)
                           for c, v in sorted(marg.items()) if len(v) >= 30},
            }

    g1 = []
    for r in races:
        if not r["g1"]:
            continue
        cl = {ub: (L, g, ln) for ub, L, g, ln in corner_lengths(r["corner"])}
        horses = []
        cum, ok = 0.0, True
        for row in sorted(r["rows"], key=lambda x: int(x["着順"])):
            ub = int(row["馬番"])
            ch = int(row["着順"])
            if ch > 1:
                ml = margin_len(row.get("着差"))
                ok = ok and ml is not None
                if ok:
                    cum += ml
            horses.append({"ub": ub, "waku": int(row["枠番"]) if row["枠番"].isdigit() else 0,
                           "name": row["馬名"], "kyaku": r["kyaku"].get(ub, ""),
                           "ninki": int(row["人気"]) if (row.get("人気") or "").isdigit() else None,
                           "chaku": ch,
                           "c4": cl[ub][0] if ub in cl else None,
                           "grp": cl[ub][1] if ub in cl else None,
                           "lane": cl[ub][2] if ub in cl else None,
                           "fin": round(cum, 2) if ok else None,
                           "jockey": row.get("騎手", "")})
        g1.append({"stem": r["stem"], "date": r["stem"][:10], "name": r["name"],
                   "venue": r["venue"], "surface": r["surface"], "kyori": r["kyori"],
                   "baba": r["baba"], "pace": round(r["pace"], 3) if r["pace"] is not None else None,
                   "band": band(r), "horses": horses})
    g1.sort(key=lambda x: x["date"])

    # 次のG1: 枠順確定前の登録馬（馬番・枠番は無い）
    upcoming = []
    for p in sorted(D.glob("*_登録馬.csv")):
        stem = p.name[: -len("_登録馬.csv")]
        m = re.match(r"(\d{4}-\d{2}-\d{2})_(\D+?)(\d{2})R_(.+?)\(G1\)$", stem)
        if not m:
            continue
        # 馬柱で脚質が空の馬は、本人の見立てで補える（data/<日付>_<場><R>R_脚質補足.json）。
        # 実測ではないので kyaku_src="本人" を付け、ページ側で区別して見せる。
        # 馬柱に脚質がある馬は上書きしない（補うのは空欄だけ）
        hosoku = {}
        hp = Path("data") / f"{m.group(1)}_{m.group(2)}{m.group(3)}R_脚質補足.json"
        if hp.exists():
            hosoku = {k: v for k, v in json.loads(hp.read_text(encoding="utf-8")).items()
                      if not k.startswith("_")}
        hs = []
        for e in csv.DictReader(open(p, encoding="utf-8-sig")):
            if not (e.get("登録番号") or "").isdigit():
                continue
            h = {"reg": int(e["登録番号"]), "name": e["馬名"],
                 "kyaku": (e.get("脚質") or "").strip(), "jockey": e.get("騎手", "")}
            add = hosoku.get(h["name"])
            if add and not h["kyaku"] and add.get("脚質") in KYAKU:
                h["kyaku"] = add["脚質"]
                h["kyaku_src"] = "本人"
                if add.get("注記"):
                    h["kyaku_note"] = add["注記"]
            hs.append(h)
        info = next((g for g in reversed(g1) if g["name"] == m.group(4)), None)
        upcoming.append({"stem": stem, "date": m.group(1), "name": m.group(4),
                         "venue": m.group(2), "surface": info["surface"] if info else "芝",
                         "kyori": info["kyori"] if info else None, "horses": hs})

    band_count = defaultdict(lambda: defaultdict(int))
    for g in g1:
        band_count[g["surface"]][g["band"] or "不明"] += 1

    payload = {
        "作成": "scripts/build_pace_sim.py",
        "対象": f"中央1-12R {len(races):,}レース（2024-01〜2026-09）",
        "境目": {sf: {"ハイ未満": round(a, 3), "スロー以上": round(b, 3)} for sf, (a, b) in cuts.items()},
        "帯": stats,
        "G1の帯": {sf: dict(v) for sf, v in band_count.items()},
        "G1": g1,
        "次のG1": upcoming,
        # アニメーションの直線の長さ（芝の公表値・外回りのある場は外回り）
        "直線": {k: v.chokusen for k, v in COURSES.items()},
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(races):,}レース・G1 {len(g1)}本・次のG1 {len(upcoming)}本 → {OUT}")
    for sf in ("芝", "ダ"):
        print(f"\n■ {sf}  境目 {cuts[sf][0]:+.3f} / {cuts[sf][1]:+.3f}")
        for pb in PACES:
            s = stats[sf][pb]
            ks = "  ".join(f"{k}:位置{v['pos4']} 3着内{v['top3']:.1%}×{v['top3_x']} 勝×{v['win_x']}(n={v['n']})"
                           for k, v in s["kyaku"].items() if v["n"])
            print(f"  {pb:<4} {s['races']:>5}R 間隔{s['gap']}馬身 全長{s['spread']}馬身  {ks}")
    print("\nG1の帯:", payload["G1の帯"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
