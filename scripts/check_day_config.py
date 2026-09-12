#!/usr/bin/env python3
"""設定JSONを「開催区分ごと」に検算する。予想を出す前に必ず通す。

## なぜ開催区分ごとなのか（2026-09-12の反省）

`scripts/build_day_config.py` で手書きをやめたあと、なお馬場が4レース間違って
いた。**間違いは全部ダートだった**:

| レース | 確定（結果ページ） | 生成した設定 |
|---|---|---|
| 中山11R ダ | 重 | 不良 |
| 中山12R ダ | 重 | 不良 |
| 阪神10R ダ | 良 | 稍重 |
| 阪神12R ダ | 良 | 稍重 |

芝4レースは全部合っていた。距離と芝ダも8レース全部合っていた。つまり

  **馬場状態は「競馬場 × 芝ダ」という開催区分ごとの値で、しかも日中に変わる。**
  ダートは芝より乾きやすいので、朝に取った馬柱の値はダートだけ系統的に古くなる。

馬場は印の並び順を決める（良なら良馬場スコア、それ以外なら重馬場スコア）。
稍重→良 の見落としは並び順の軸ごと変える。

## 何と突き合わせるか

レース一覧ページ（`data/raw/jra_list_YYYYMMDD.html`）は馬柱とは別系統で、

    <p class="RaceList_DataTitle"><small>4回</small> 中山 <small>3日目</small></p>
    <span class="Shiba">芝(B)：重</span>
    <span class="Da">ダ：不</span>

と**開催区分ごとの馬場をそのまま持っている**。レースごとの `芝1600m` もある。
結果ページ（`data/raw/<race_id>.html`）があれば確定値とも突き合わせる。

    python3 scripts/check_day_config.py --config config/2026-09-12_中央.json

不一致があれば終了コード1を返すので、予想フローの手前に置ける。
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

VENUES = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
          "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}
BABA = {"稍": "稍重", "不": "不良", "稍重": "稍重", "重": "重", "不良": "不良", "良": "良"}
# 乾いていく向き。日中の変化はこの順に沿うのが普通で、逆行は読み間違いを疑う
DRYING = ["不良", "重", "稍重", "良"]


def axis(baba: str) -> str:
    """印の並び順に使うスコアの軸。`keiba/marks.py` は良か否かだけを見る。"""
    return "良馬場スコア" if baba == "良" else "重馬場スコア"


def severity(cfg_cond: str, cfg_baba: str, ref_cond: str, ref_baba: str) -> str:
    """不一致の重大度。印が動くものと、表示だけのものを分ける。

    馬場は稍重/重/不良のどれでも重馬場スコアで並ぶので、**危ないのは
    良↔非良をまたぐ取り違えだけ**。2026-09-12は中山の 不良→重 が2件あったが
    どちらも非良のままで印は動かなかった（阪神の 稍重→良 2件は軸が変わった）。
    """
    if cfg_cond != ref_cond:
        return "重大: 芝ダ・距離が違う（コース特性の軸ごと変わる）"
    if cfg_baba == ref_baba:
        return "OK"
    if axis(cfg_baba) != axis(ref_baba):
        return f"重大: {axis(cfg_baba)}→{axis(ref_baba)} で印の並び順が変わる"
    return "軽微: どちらも非良なので印は動かない（表示のみ）"


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_list_page(path: Path) -> tuple[dict[tuple[str, str], str], dict[str, str]]:
    """一覧ページから (競馬場,芝ダ)→馬場 と race_id→条件 を読む。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    baba: dict[tuple[str, str], str] = {}
    for block in re.findall(r'<dt class="RaceList_DataHeader">(.*?)</dt>', text, re.S):
        m = re.search(r'<p class="RaceList_DataTitle">(.*?)</p>', block, re.S)
        if not m:
            continue
        title = strip_tags(m.group(1))
        venue = next((v for v in VENUES.values() if v in title), None)
        if not venue:
            continue
        if s := re.search(r'<span class="Shiba">芝[^：]*：\s*([^<\s]+)', block):
            baba[(venue, "芝")] = BABA.get(s.group(1), s.group(1))
        if d := re.search(r'<span class="Da">ダ[^：]*：\s*([^<\s]+)', block):
            baba[(venue, "ダ")] = BABA.get(d.group(1), d.group(1))
    cond: dict[str, str] = {}
    for li in re.split(r"<li\b", text):
        if m := re.search(r"race_id=(\d{12})", li):
            if c := re.search(r"(芝|ダ|障)\s*(\d{3,4})m", strip_tags(li)):
                cond.setdefault(m.group(1), f"{c.group(1)}{c.group(2)}m")
    return baba, cond


def result_condition(cache: Path, race_id: str) -> tuple[str, str] | None:
    """結果ページから確定の (条件, 馬場) を読む。無ければ None。"""
    p = cache / f"{race_id}.html"
    if not p.exists():
        return None
    m = re.search(r'<div class="RaceData01">(.*?)</div>',
                  p.read_text(encoding="utf-8", errors="replace"), re.S)
    if not m:
        return None
    txt = strip_tags(m.group(1))
    c = re.search(r"(芝|ダ|障)\s*(\d{3,4})m", txt)
    b = re.search(r"馬場:\s*(\S+)", txt)
    if not (c and b):
        return None
    return f"{c.group(1)}{c.group(2)}m", BABA.get(b.group(1), b.group(1))


def race_ids_for(cache: Path, date: str) -> dict[tuple[str, int], str]:
    """その日の馬柱キャッシュから (競馬場, R) → race_id を作る。"""
    out: dict[tuple[str, int], str] = {}
    for p in cache.glob("*_past.html"):
        rid = p.name.split("_")[0]
        if len(rid) == 12 and rid.startswith(date[:4]):
            if venue := VENUES.get(rid[4:6]):
                out[(venue, int(rid[10:12]))] = rid
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--cache-dir", default="data/raw")
    ap.add_argument("--date", help="省略時は設定JSONの heading/title から拾う")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    races = cfg["races"]
    date = args.date
    if not date:
        for key in ("heading", "title"):
            if m := re.search(r"(\d{4}-\d{2}-\d{2})", cfg.get(key, "")):
                date = m.group(1)
                break
    if not date:
        print("! 日付が分からない。--date を指定する")
        return 1

    cache = Path(args.cache_dir)
    list_path = cache / f"jra_list_{date.replace('-', '')}.html"
    list_baba: dict[tuple[str, str], str] = {}
    list_cond: dict[str, str] = {}
    if list_path.exists():
        list_baba, list_cond = parse_list_page(list_path)
        stamp = datetime.fromtimestamp(list_path.stat().st_mtime).strftime("%m/%d %H:%M")
        print(f"照合元: {list_path.name}（取得 {stamp}）")
    else:
        print(f"! {list_path.name} が無い。一覧ページとの突き合わせは省略")
    ids = race_ids_for(cache, date)
    print()

    problems = 0
    minor = 0

    # 1) 開催区分（競馬場 × 芝ダ）ごとにまとめる
    print("■ 開催区分（競馬場 × 芝ダ）ごとの馬場")
    print(f"  {'開催区分':<12}{'R数':>4}  {'設定の馬場':<14}{'一覧ページ':<12}{'判定'}")
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in races:
        groups[(r["venue"], r["surface"][0])].append(r)
    for key in sorted(groups):
        rs = sorted(groups[key], key=lambda r: r.get("post_time") or "")
        seen = list(dict.fromkeys(r["baba"] for r in rs))
        shown = " → ".join(seen)
        ref = list_baba.get(key, "—")
        notes = []
        if len(seen) > 1:
            # 日中の変化なら乾く向き（または濡れる向き）に単調であるはず
            idx = [DRYING.index(b) for b in seen if b in DRYING]
            if not (idx == sorted(idx) or idx == sorted(idx, reverse=True)):
                notes.append("変化が単調でない→読み間違いを疑う")
                problems += 1
            else:
                notes.append("日中に変化（時刻順）")
        if ref != "—" and ref not in seen:
            notes.append(f"一覧ページは{ref}")
        print(f"  {key[0] + key[1]:<12}{len(rs):>4}  {shown:<14}{ref:<12}"
              f"{'・'.join(notes) or 'OK'}")
    print()

    # 2) レースごとに、芝ダ・距離を一覧ページと突き合わせる
    if list_cond:
        print("■ 芝ダ・距離の突き合わせ（設定 vs 一覧ページ）")
        bad = []
        for r in races:
            rid = ids.get((r["venue"], int(r["race_no"][:-1])))
            ref = list_cond.get(rid or "")
            if ref and ref != r["surface"]:
                bad.append((r, ref))
        for r, ref in bad:
            print(f"  ✗ {r['venue']}{r['race_no']} {r['name']}: "
                  f"設定 {r['surface']} / 一覧 {ref}")
            problems += 1
        print(f"  {len(races) - len(bad)}/{len(races)}レース一致" if races else "  —")
        print()

    # 3) 結果ページがあれば確定値と突き合わせる（レース後の検証）
    finals = []
    for r in races:
        rid = ids.get((r["venue"], int(r["race_no"][:-1])))
        got = result_condition(cache, rid) if rid else None
        if got:
            finals.append((r, got))
    if finals:
        print("■ 確定値との突き合わせ（結果ページ・発走後にしか無い）")
        print(f"  {'レース':<10}{'設定':<18}{'確定':<18}{'判定'}")
        for r, (cond, baba) in finals:
            tag = severity(r["surface"], r["baba"], cond, baba)
            if tag.startswith("重大"):
                problems += 1
            elif tag.startswith("軽微"):
                minor += 1
            print(f"  {r['venue'] + r['race_no']:<10}{r['surface'] + ' ' + r['baba']:<18}"
                  f"{cond + ' ' + baba:<18}{tag}")
        print()

    if problems:
        print(f"! 重大な不一致 {problems}件。設定を直すまで予想を出さない")
    if minor:
        print(f"  軽微な不一致 {minor}件（非良どうしの取り違え）。印は動かないが直す")
    if not problems and not minor:
        print("開催区分・芝ダ・距離はすべて整合している")
    print("※ 馬場は発走までに変わる。ダートは芝より乾きやすく、朝の値は"
          "ダートだけ系統的に古くなる")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
