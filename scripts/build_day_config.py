#!/usr/bin/env python3
"""取得済みの馬柱HTMLから、その日の設定JSON（config/*.json）を生成する。

## なぜ必要か

この設定は長く**手書き**していた。その結果、2026-09-12の予想で:

  * 中山11R ラジオ日本賞 を「芝1200m」と書いた（正しくはダ1200m）
  * 中山10R レインボーS を「ダ2000m・不良」と書いた（正しくは芝2000m・重）

と誤った。スコア自体は馬場種別を使わないため印は変わらないが、
**馬場（良/稍重/重/不良）は印の並び順を決める**（良なら良馬場スコア、
それ以外なら重馬場スコアで並べる）。しかも競馬場ごと・芝ダートごとに
別の馬場状態なので、「同じ中山のダートだから全部不良」という推測は誤り。

netkeibaの馬柱には `<div class="RaceData01">` に

    14:50発走 / 芝2000m (右 B) / 天候:曇 / 馬場:重

と全部入っている。**推測せずここから読む**。

    python3 scripts/build_day_config.py --date 2026-09-12 \
        --races 9-12 --out config/2026-09-12_中央.json
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
from pathlib import Path

# 中央の場コード（race_id の 5-6 桁目）
VENUES = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
          "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}

SURFACE = {"芝": "芝", "ダ": "ダ", "障": "障"}


def parse(html: str) -> dict | None:
    """馬柱HTMLからレース条件を読む。読めない項目は None で返す（埋めない）。"""
    out: dict = {}
    if m := re.search(r'<h1 class="RaceName">\s*([^<]+)', html):
        out["name"] = htmllib.unescape(m.group(1)).strip()
    block = ""
    if m := re.search(r'<div class="RaceData01">(.*?)</div>', html, re.S):
        block = m.group(1)
    # 発走時刻
    if m := re.search(r"(\d{1,2}:\d{2})\s*発走", block):
        out["post_time"] = m.group(1)
    # 距離と芝ダ。**RaceData01 の中だけを見る**（ページ全体を検索すると
    # 過去走の表記を拾って別のレースの条件になる）
    if m := re.search(r"<span>\s*(芝|ダ|障)\s*(\d{3,4})m\s*</span>", block):
        out["surface"] = f"{SURFACE[m.group(1)]}{m.group(2)}m"
        out["kyori"] = int(m.group(2))
    if m := re.search(r"天候:\s*([^<\s]+)", block):
        out["weather"] = m.group(1)
    if m := re.search(r"馬場:\s*([^<\s]+)", block):
        b = m.group(1)
        # netkeibaは「稍」「不」と略す。スコア側は稍重/重/不良を期待する
        out["baba"] = {"稍": "稍重", "不": "不良", "稍重": "稍重",
                       "重": "重", "不良": "不良", "良": "良"}.get(b, b)
    # クラス・頭数（RaceData02）
    if m := re.search(r'<div class="RaceData02">(.*?)</div>', html, re.S):
        spans = [htmllib.unescape(s).strip() for s in
                 re.findall(r"<span>([^<]*)</span>", m.group(1))]
        for s in spans:
            if "クラス" in s or s in ("オープン",):
                out["grade"] = s.replace("３", "3").replace("２", "2").replace("１", "1")
            if re.fullmatch(r"\d{1,2}頭", s):
                out["tousuu"] = int(s[:-1])
    # タイトルに (G3) などがあればそれを等級にする
    if m := re.search(r"<title>([^<]+)", html):
        if g := re.search(r"\((G[I1-3]{1,3}|OP|L)\)", m.group(1)):
            out["grade"] = g.group(1)
    return out or None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--races", default="9-12")
    ap.add_argument("--cache-dir", default="data/raw")
    ap.add_argument("--entries-dir", default="data",
                    help="出走馬CSVのあるディレクトリ（entriesパスに使う）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title")
    ap.add_argument("--heading")
    args = ap.parse_args()

    lo, hi = (int(x) for x in args.races.split("-")) if "-" in args.races \
        else (int(args.races), int(args.races))
    y = args.date[:4]

    races = []
    for p in sorted(Path(args.cache_dir).glob("*_past.html")):
        rid = p.name.split("_")[0]
        if len(rid) != 12 or not rid.startswith(y):
            continue
        venue = VENUES.get(rid[4:6])
        rno = int(rid[10:12])
        if venue is None or not (lo <= rno <= hi):
            continue
        info = parse(p.read_text(encoding="utf-8", errors="replace"))
        if not info or "kyori" not in info:
            print(f"  ! {rid} は条件を読めなかった（スキップ）")
            continue
        name = info["name"]
        # **出走馬CSVは実ファイルを探す**。収集側（collect_jra_shutuba）は
        # ページの <title> からレース名を作るためクラス名が付き
        # （「御宿特別(2勝クラス)」）、<h1 class="RaceName"> の「御宿特別」とは
        # 一致しない。名前を組み立て直すとファイルが見つからない
        cand = sorted(Path(args.entries_dir).glob(
            f"{args.date}_{venue}{rno:02d}R_*_出走馬.csv"))
        if not cand:
            print(f"  ! {venue}{rno:02d}R の出走馬CSVが見つからない（スキップ）")
            continue
        entries = str(cand[0])
        name = cand[0].name[len(f"{args.date}_{venue}{rno:02d}R_"):-len("_出走馬.csv")]
        races.append({
            "venue": venue, "race_no": f"{rno}R", "name": name,
            "grade": info.get("grade", ""),
            "entries": entries,
            "kyori": info["kyori"], "surface": info["surface"],
            "baba": info.get("baba", "良"),
            "post_time": info.get("post_time", ""),
        })

    races.sort(key=lambda r: (r["venue"], int(r["race_no"][:-1])))
    cfg = {
        "title": args.title or f"{args.date} 中央予想",
        "heading": args.heading or f"{args.date} 中央 {args.races}R",
        "races": races,
    }
    Path(args.out).write_text(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n",
                              encoding="utf-8")
    print(f"{len(races)}レース → {args.out}\n")
    print(f"{'レース':<10}{'レース名':<22}{'条件':<10}{'馬場':<6}{'発走':<7}{'格'}")
    for r in races:
        print(f"{r['venue'] + r['race_no']:<10}{r['name']:<22}{r['surface']:<10}"
              f"{r['baba']:<6}{r['post_time']:<7}{r['grade']}")

    # **開催区分（競馬場 × 芝ダ）ごとにまとめて見せる**。馬場はこの単位の値で
    # あり、同じ競馬場でも芝とダで別。2026-09-12は馬場を4レース間違えたが、
    # 全部ダートだった（朝の値のまま日中の回復を拾えていなかった）
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in races:
        groups.setdefault((r["venue"], r["surface"][0]), []).append(r)
    print(f"\n開催区分ごとの馬場（この単位で確認する）")
    print(f"  {'開催区分':<12}{'R数':>4}  {'馬場':<14}{'距離'}")
    for key in sorted(groups):
        rs = sorted(groups[key], key=lambda r: r.get("post_time") or "")
        babas = " → ".join(dict.fromkeys(r["baba"] for r in rs))
        kyori = " ".join(f"{r['kyori']}" for r in rs)
        print(f"  {key[0] + key[1]:<12}{len(rs):>4}  {babas:<14}{kyori}")
    print("\n次に必ず検算する（芝ダ・距離を一覧ページと、馬場を開催区分ごとに照合）:")
    print(f"  python3 scripts/check_day_config.py --config {args.out}")


if __name__ == "__main__":
    main()
