"""JRA公式の馬場情報（芝のクッション値・含水率）を取る。

    python3 -m keiba.cli baba-info --date 2026-09-26

JRAの馬場情報ページ（https://www.jra.go.jp/keiba/baba/）は、中身を
次の2つの静的HTMLから JavaScript で読み込んでいる。どちらも全場ぶんを
1ファイルに持ち、場ごとに `<div id="rcA" title="中山">` で区切られる:

    /keiba/baba/_data_cushion.html   芝のクッション値（測定時刻ごと）
    /keiba/baba/_data_moist.html     含水率（芝・ダ × ゴール前・4コーナー）

robots.txt は `Disallow:` が空（2026-09-25に確認）。1回の取得は2ファイルだけ。

## スコアには入れない（表示のみ）
クッション値を採点に使う根拠は、まだ測っていない。JRAは過去の値も
公開している（/keiba/baba/archive/）ので、貯めれば「クッション値×脚質」
などを同一人気帯内リフトで測れるが、それまでは**表示と記録だけ**にする
（CLAUDE.mdの2段階の第1段階）。

JRAの参考区分（クッション値と表層のクッション性）:
    12以上=硬め / 10〜12=やや硬め / 8〜10=標準 / 7〜8=やや軟らかめ / 7以下=軟らかめ
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

from .collect import REQUEST_INTERVAL, USER_AGENT

BASE = "https://www.jra.go.jp/keiba/baba/"
FILES = {"cushion": "_data_cushion.html", "moist": "_data_moist.html"}
TIMEOUT = 20


def cushion_label(v: float) -> str:
    """JRAの参考区分。境目はJRAの表どおり（10から12=やや硬め など）。"""
    if v >= 12:
        return "硬め"
    if v >= 10:
        return "やや硬め"
    if v >= 8:
        return "標準"
    if v > 7:
        return "やや軟らかめ"
    return "軟らかめ"


def _venue_blocks(html: str) -> dict[str, str]:
    """`<div id="rcX" title="場名">` ごとに中身を切り出す。"""
    out: dict[str, str] = {}
    marks = list(re.finditer(r'<div id="rc\w+" title="([^"]+)">', html))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(html)
        out[m.group(1)] = html[m.end():end]
    return out


def _units(block: str) -> list[str]:
    return re.split(r'<div class="unit">', block)[1:]


def _text(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def parse_cushion(html: str) -> dict[str, list[dict]]:
    """{場: [{"時刻": "9月25日（金曜）10時30分", "クッション値": 9.5, "区分": "標準"}, ...]}
    新しい順（JRAの並びのまま）。値が読めない行は捨てる（数字を作らない）。"""
    out: dict[str, list[dict]] = {}
    for venue, block in _venue_blocks(html).items():
        rows = []
        for u in _units(block):
            t = re.search(r'<div class="time">(.*?)</div>', u, re.S)
            c = re.search(r'<div class="cushion">(.*?)</div>', u, re.S)
            if not (t and c):
                continue
            try:
                v = float(_text(c.group(1)))
            except ValueError:
                continue
            rows.append({"時刻": _text(t.group(1)), "クッション値": v, "区分": cushion_label(v)})
        if rows:
            out[venue] = rows
    return out


def parse_moist(html: str) -> dict[str, list[dict]]:
    """{場: [{"時刻", "芝": {"ゴール前", "4コーナー"}, "ダ": {...}, "注記"}, ...]}（%）。"""
    out: dict[str, list[dict]] = {}
    for venue, block in _venue_blocks(html).items():
        rows = []
        for u in _units(block):
            t = re.search(r'<div class="time">(.*?)</div>', u, re.S)
            if not t:
                continue
            row: dict = {"時刻": _text(t.group(1))}
            for key, cls in (("芝", "turf"), ("ダ", "dirt")):
                d = re.search(rf'<div class="{cls}">(.*?)</div>', u, re.S)
                if not d:
                    continue
                vals = {}
                for label, span in (("ゴール前", "mg"), ("4コーナー", "m4c")):
                    s = re.search(rf'<span class="{span}"[^>]*>(.*?)</span>', d.group(1), re.S)
                    try:
                        vals[label] = float(_text(s.group(1))) if s else None
                    except ValueError:
                        vals[label] = None
                row[key] = vals
            n = re.search(r"<li>(注記：.*?)</li>", u, re.S)
            if n:
                row["注記"] = _text(n.group(1))
            rows.append(row)
        if rows:
            out[venue] = rows
    return out


def fetch() -> dict:
    """2ファイルを取って読む。JRAのページは Shift_JIS。"""
    got = {}
    for i, (key, name) in enumerate(FILES.items()):
        if i:
            time.sleep(REQUEST_INTERVAL)   # 続けて取ると2つ目が403になる（2026-09-25に踏んだ）
        for attempt in range(2):
            res = requests.get(BASE + name, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            if res.status_code != 403 or attempt:
                break
            time.sleep(REQUEST_INTERVAL * 2)
        res.raise_for_status()
        got[key] = res.content.decode("shift_jis", errors="replace")
    return {"クッション値": parse_cushion(got["cushion"]), "含水率": parse_moist(got["moist"])}


def summary_lines(info: dict, venues: list[str] | None = None) -> list[str]:
    """場ごとに最新の値を1〜2行で。予想テキストの頭に置く想定。"""
    lines = []
    names = venues or sorted(set(info["クッション値"]) | set(info["含水率"]))
    for v in names:
        parts = []
        c = info["クッション値"].get(v)
        if c:
            parts.append(f"芝クッション値 {c[0]['クッション値']:.1f}（{c[0]['区分']}・{c[0]['時刻']}）")
        m = info["含水率"].get(v)
        if m:
            w = m[0]
            fmt = lambda d: "/".join("—" if x is None else f"{x:.1f}" for x in (d.get("ゴール前"), d.get("4コーナー")))
            s = []
            if "芝" in w:
                s.append(f"芝 {fmt(w['芝'])}%")
            if "ダ" in w:
                s.append(f"ダ {fmt(w['ダ'])}%")
            parts.append(f"含水率（ゴール前/4角）{' '.join(s)}（{w['時刻']}）")
        if parts:
            lines.append(f"{v}: " + " ／ ".join(parts))
    return lines


def save(info: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def latest_for(date: str, directory: Path | str = "data/baba") -> tuple[Path, dict] | None:
    """その日付のファイルのうちいちばん新しい取得分を返す（無ければ None）。
    ファイル名は `YYYY-MM-DD_HHMM_馬場情報.json` なので名前順＝時刻順。"""
    files = sorted(Path(directory).glob(f"{date}_*_馬場情報.json"))
    if not files:
        return None
    return files[-1], json.loads(files[-1].read_text(encoding="utf-8"))


def heading_lines(date: str | None, venues: list[str],
                  directory: Path | str = "data/baba") -> list[str]:
    """予想テキストの見出しの下に置く行。取得していなければ何も出さない
    （無いことを「標準」などと書かない）。"""
    if not date:
        return []
    got = latest_for(date, directory)
    if not got:
        return []
    _, info = got
    lines = summary_lines(info, venues)
    if not lines:
        return []
    return [f"【馬場】JRA公式（{info.get('取得時刻', '')}取得・スコアには入れていない）"] + \
           [f"  {l}" for l in lines]
