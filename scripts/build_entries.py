#!/usr/bin/env python3
"""発走前のレースについて、馬柱から出走馬CSVと予想用の設定JSONを作る。

collect は「結果が出たレース」を対象にするが、予想では発走前の馬柱だけを
読む必要がある。取得するのは指定したレースぶんだけ（1レース1リクエスト）。

    python3 scripts/build_entries.py --date 2026-09-04 --venue 大井 --races 10-12
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date as _Date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.collect import (
    ENTRY_COLUMNS,
    JRA_SHUTUBA_PAST_URL,
    JRA_VENUE_CODES,
    SHUTUBA_PAST_URL,
    VENUE_CODES,
    Fetcher,
    _text,
    fetch_jra_odds,
    find_jra_race_ids,
    jra_venue_of,
    parse_shutuba_past,
)

SHUTUBA_URL = "https://nar.netkeiba.com/race/shutuba.html?race_id={race_id}"


def parse_race_header(html: str) -> dict:
    """馬柱ページからレース名・距離・発走時刻を取り出す。"""
    info = {"name": "", "grade": "", "post_time": "", "surface": "", "kyori": None}
    # 中央は <h1 class="RaceName">、地方は <div class="RaceName">
    if m := re.search(r'<(div|h1)[^>]*class="RaceName"[^>]*>.*?</\1>', html, re.S):
        raw = re.sub(r"\s+", " ", _text(m.group())).strip()
        for badge in (" 重賞", " OP", " Jpn1", " Jpn2", " Jpn3", " G1", " G2", " G3"):
            if raw.endswith(badge):
                raw, info["grade"] = raw[: -len(badge)].strip(), badge.strip()
        info["name"] = raw
    if not info["grade"] and (t := re.search(r"<title>([^<|]+)", html)):
        if g := re.search(r"\((G[123]|Jpn[123]|L|OP)\)", t.group(1)):
            info["grade"] = g.group(1)
    if m := re.search(r'<div[^>]*class="RaceData01"[^>]*>.*?</div>', html, re.S):
        line = _text(m.group())
        if t := re.search(r"(\d{1,2}:\d{2})発走", line):
            info["post_time"] = t.group(1)
        if s := re.search(r"([芝ダ障])\s*(\d+)m\s*(\([^)]*\))?", line):
            info["surface"] = f"{s.group(1)}{s.group(2)}m{s.group(3) or ''}"
            info["kyori"] = int(s.group(2))
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="開催日 (YYYY-MM-DD)")
    ap.add_argument("--venue", required=True,
                    choices=sorted(VENUE_CODES) + sorted(JRA_VENUE_CODES) + ["中央"])
    ap.add_argument("--races", default="10-12")
    ap.add_argument("--outdir", default="data")
    ap.add_argument("--config", help="設定JSONの出力先（既定は config/YYYYMMDD_場.json）")
    ap.add_argument("--cache-dir", default="data/raw")
    ap.add_argument("--baba", default="良")
    ap.add_argument("--interval", type=float, default=1.5)
    ap.add_argument("--refresh", action="store_true",
                    help="キャッシュを無視して取り直す（オッズ更新の反映に使う）")
    args = ap.parse_args()

    lo, hi = (args.races.split("-") + [None])[:2]
    numbers = list(range(int(lo), int(hi) + 1)) if hi else [int(x) for x in args.races.split(",")]

    y, mo, d = (int(x) for x in args.date.split("-"))
    race_date = _Date(y, mo, d)
    fetcher = Fetcher(Path(args.cache_dir), interval=args.interval)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 中央は race_id が開催回・日目で決まるため、その日のレース一覧から引く
    is_jra = args.venue in JRA_VENUE_CODES or args.venue == "中央"
    if is_jra:
        venue = None if args.venue == "中央" else args.venue
        targets = [(int(rid[-2:]), rid, jra_venue_of(rid))
                   for rid in find_jra_race_ids(args.date, fetcher, venue)
                   if int(rid[-2:]) in numbers]
    else:
        targets = [(no, f"{y}{VENUE_CODES[args.venue]}{mo:02d}{d:02d}{no:02d}", args.venue)
                   for no in numbers]

    races = []
    for no, race_id, venue_name in targets:
        url = (JRA_SHUTUBA_PAST_URL if is_jra else SHUTUBA_PAST_URL).format(race_id=race_id)
        html = fetcher.get(url, f"{race_id}_past", refresh=args.refresh)
        if html is None:
            print(f"  {no}R 取得失敗")
            continue
        entries = parse_shutuba_past(html, race_date)
        # 馬柱のオッズ欄はJSで埋まるためHTMLからは取れない。発走前はAPIから取る
        if is_jra and entries:
            odds = fetch_jra_odds(race_id, fetcher)
            for e in entries:
                if (v := odds.get(e.get("馬番"))):
                    e["単勝オッズ"], e["人気"] = v
        if not entries:
            print(f"  {no}R 出走馬が読めません（まだ確定していない可能性）")
            continue
        info = parse_race_header(html)
        safe = re.sub(r'[\\/:*?"<>|\s]+', "", info["name"]) or f"{no:02d}R"
        path = outdir / f"{args.date}_{venue_name}{no:02d}R_{safe}_出走馬.csv"
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=ENTRY_COLUMNS)
            w.writeheader()
            w.writerows(entries)
        races.append({
            "race_no": f"{no}R", "venue": venue_name, "name": info["name"], "grade": info["grade"],
            "post_time": info["post_time"], "surface": info["surface"],
            "kyori": info["kyori"], "baba": args.baba, "entries": str(path),
        })
        print(f"  {venue_name}{no}R {info['name']} ({info['surface']}) "
              f"{len(entries)}頭 → {path.name}")

    if not races:
        print("出走表を取得できませんでした")
        return
    cfg = Path(args.config) if args.config else Path("config") / f"{args.date.replace('-','')}_{args.venue}.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(
        {"title": f"{args.date} {args.venue}", "heading": f"{args.date} {args.venue}",
         "races": races}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n設定JSON: {cfg}")


if __name__ == "__main__":
    main()
