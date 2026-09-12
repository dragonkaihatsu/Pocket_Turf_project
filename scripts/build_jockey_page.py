#!/usr/bin/env python3
"""騎手の得意条件をまとめた簡易HTML（騎手図鑑）を作る。

`scripts/jockey_stats.py` が作る `data/profiles/jra/jockey_stats.json`
（騎手×場／距離帯／馬場種別／脚質の単勝回収率）を、そのまま見て
判断できる一覧ページにする。レイアウトはnetkeiba/競馬ラボのリーディング
表を参考にした、印(◎○)付きのシンプルなテーブル。

引退騎手の扱い:
    JRA公式「引退騎手プロフィール」（jra.go.jp）を取得し、本データの
    各騎手の最終騎乗日が公式の引退日以前であることを確認できたものだけ
    「引退」と確定する。単純な前方一致だけだと、短い姓（例:「佐藤」
    「伊藤」）が何十年も前に引退した同姓の別人と誤って一致するため、
    「本データでの最終騎乗 ≦ 公式引退日」を必須条件にしている。

    python3 scripts/build_jockey_page.py \
        --jockey-stats data/profiles/jra/jockey_stats.json \
        --collected data/collected_jra \
        --out output/jockey_page.html
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
from collections import defaultdict
from pathlib import Path

import requests

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keiba.racefiles import DEFAULT_RACES, result_paths

USER_AGENT = "Mozilla/5.0 (compatible; keiba-personal-research)"
JRA_RETIRED_URL = "https://www.jra.go.jp/datafile/meikan/jretirement.html"
RETIRED_PATTERN = re.compile(
    r'aria-hidden="true"></i>([^<]+)<span class="opt opt-xs">（([^）]+)）</span>')
RETIRED_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日引退")

MIN_RIDES_SHOWN = 1  # 騎乗依頼が少ない騎手も母数注記つきで一覧に含める


def fetch_retired_list(cache_path: Path, refresh: bool = False) -> list[tuple[str, str]]:
    """JRA公式サイトの引退騎手一覧を (フルネーム, 引退日ISO) のリストで返す。"""
    if cache_path.exists() and not refresh:
        html = cache_path.read_text(encoding="utf-8")
    else:
        r = requests.get(JRA_RETIRED_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
        r.encoding = "cp932"
        html = r.text
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(html, encoding="utf-8")

    out = []
    for name, date_txt in RETIRED_PATTERN.findall(html):
        full = name.strip().replace("　", "").replace(" ", "")
        m = RETIRED_DATE_RE.match(date_txt)
        if not m:
            continue
        iso = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        out.append((full, iso))
    return out


def collect_ride_meta(collected_dir: Path, races: str | None = None) -> dict:
    """収集済み結果CSVから 騎手表記 → 騎乗数・勝利数・初/最終騎乗日 を作る。

    races で対象レース帯を絞る（既定は jockey_stats.json と同じ9-12R）。
    絞らないと1-8Rの収集の進み具合で騎乗数・引退判定の最終騎乗日が変わる。
    """
    ride_count: dict[str, int] = defaultdict(int)
    win_count: dict[str, int] = defaultdict(int)
    first_ride: dict[str, str] = {}
    last_ride: dict[str, str] = {}

    for f in result_paths(collected_dir, races if races is not None else DEFAULT_RACES):
        m = re.match(r".*/(\d{4}-\d{2}-\d{2})_", f)
        date = m.group(1) if m else None
        if not date:
            continue
        with open(f, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                j = (row.get("騎手") or "").strip()
                if not j:
                    continue
                ride_count[j] += 1
                if (row.get("着順") or "").isdigit() and int(row["着順"]) == 1:
                    win_count[j] += 1
                if j not in last_ride or date > last_ride[j]:
                    last_ride[j] = date
                if j not in first_ride or date < first_ride[j]:
                    first_ride[j] = date

    return {"ride_count": ride_count, "win_count": win_count,
            "first_ride": first_ride, "last_ride": last_ride}


def match_retired(ride_count: dict, last_ride: dict,
                   retired_full: list[tuple[str, str]]) -> dict[str, dict]:
    """表記ゆれ対策: 前方一致 かつ 本データの最終騎乗が公式引退日以前、のときだけ確定させる。"""
    out = {}
    for our in ride_count:
        if len(our) < 2:
            continue
        best = None
        for full, iso in retired_full:
            if full.startswith(our) and last_ride[our] <= iso:
                if best is None or iso < best[1]:
                    best = (full, iso)
        if best:
            out[our] = {"full": best[0], "date": best[1]}
    return out


def build_payload(jockey_stats_path: Path, collected_dir: Path,
                  retired_cache: Path, refresh_retired: bool,
                  races: str | None = None) -> dict:
    stats = json.loads(jockey_stats_path.read_text(encoding="utf-8"))
    meta = collect_ride_meta(collected_dir, races)
    retired_full = fetch_retired_list(retired_cache, refresh=refresh_retired)
    retired = match_retired(meta["ride_count"], meta["last_ride"], retired_full)

    badges: dict[str, list] = defaultdict(list)
    for r in stats["組み合わせ"]:
        if not r["信頼できる母数"] or r["単勝回収率"] < 1.0:
            continue
        badges[r["騎手"]].append({
            "粒度": r["粒度"], "条件": r["条件"], "n": r["n"],
            "勝利数": r["勝利数"], "勝率": r["勝率"], "複勝率": r["複勝率"],
            "回収率": r["単勝回収率"],
        })
    for j in badges:
        badges[j].sort(key=lambda x: -x["回収率"])

    jockeys = []
    for name, n in meta["ride_count"].items():
        if n < MIN_RIDES_SHOWN:
            continue
        entry = {
            "name": name, "rides": n,
            "wins": meta["win_count"].get(name, 0),
            "winRate": round(meta["win_count"].get(name, 0) / n, 4),
            "firstRide": meta["first_ride"].get(name),
            "lastRide": meta["last_ride"].get(name),
            "badges": badges.get(name, []),
            "bestRoi": max((b["回収率"] for b in badges.get(name, [])), default=0),
        }
        if name in retired:
            entry["retired"] = retired[name]["date"]
            entry["retiredFullName"] = retired[name]["full"]
        jockeys.append(entry)
    jockeys.sort(key=lambda j: (-j["bestRoi"], -j["rides"]))

    n_races = stats.get("レース数", 0)
    n_rides = stats.get("騎乗数", 0)
    return {
        "generated": f"中央9-12R中心・{n_races:,}レース・{n_rides:,}騎乗の実測",
        "totalJockeys": len(jockeys),
        "badgeHolders": sum(1 for j in jockeys if j["badges"]),
        "retiredCount": sum(1 for j in jockeys if "retired" in j),
        "raceCount": n_races,
        "jockeys": jockeys,
    }


HTML_TEMPLATE_PATH = Path(__file__).with_name("jockey_page_template.html")


def render_html(payload: dict) -> str:
    template = HTML_TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("__DATA_JSON__", json.dumps(payload, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jockey-stats", default="data/profiles/jra/jockey_stats.json")
    ap.add_argument("--collected", default="data/collected_jra")
    ap.add_argument("--retired-cache", default="data/raw/jra_retired_jockeys.html")
    ap.add_argument("--refresh-retired", action="store_true",
                    help="JRA公式の引退騎手一覧を再取得する（既定はキャッシュを使う）")
    ap.add_argument("--races", default=DEFAULT_RACES,
                    help="騎乗数を数える対象レース番号（既定9-12。"
                         "jockey_stats.json と同じ帯に揃える）")
    ap.add_argument("--out", default="output/jockey_page.html")
    args = ap.parse_args()

    payload = build_payload(Path(args.jockey_stats), Path(args.collected),
                            Path(args.retired_cache), args.refresh_retired,
                            args.races)
    html = render_html(payload)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"騎手{payload['totalJockeys']}人（得意条件あり{payload['badgeHolders']}人・"
          f"引退確認{payload['retiredCount']}人）→ {out}")


if __name__ == "__main__":
    main()
