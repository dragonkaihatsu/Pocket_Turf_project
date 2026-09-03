"""馬ごとの全戦績を netkeiba の馬別成績ページから取得する。

    db.netkeiba.com/horse/result/<馬ID>/

収集済みの馬柱HTML(data/raw/*_past.html)に馬IDが埋まっているため、
新たに検索する必要はない。取得した戦績から

  * コース適性 … その馬自身の大井での成績
  * 距離適性   … その馬自身の当該距離での成績

を作る。どちらも「馬の能力を素直に見る」ための材料であり、
騎手・血統のような上乗せ要素とは別枠で扱う。

重要（後知恵の排除）:
    戦績には予想対象レースより後の結果も含まれる。スコアリングで使うときは
    必ずレース日より前の行だけに絞ること。`records_before()` がその役割を持つ。
"""
from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

RESULT_URL = "https://db.netkeiba.com/horse/result/{horse_id}/"
RECORDS_PATH = Path(__file__).resolve().parent.parent / "data" / "horse_records.csv"

FIELDS = ["馬ID", "馬名", "日付", "場", "R", "レース名", "頭数", "枠番", "馬番",
          "オッズ", "人気", "着順", "騎手", "斤量", "馬場種別", "距離", "馬場"]

_TAG = re.compile(r"<[^>]+>")
# 出走馬のリンクは <a href=".../horse/ID/"><span class="Icon_HorseMark"></span>馬名</a>
# のようにアイコン用のタグを挟むことがある。挟まっても馬名を拾えるようにする
HORSE_LINK_RE = re.compile(
    r'/horse/([0-9a-zA-Z]{8,12})/?"[^>]*>(?:\s*<[^>]*>\s*)*([^<]{2,20})<')
_KAISAI = re.compile(r"[0-9]")


def _text(cell: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub("", cell)).replace("&nbsp;", " ").strip()


def horse_ids_from_cache(cache_dir: Path) -> dict[str, str]:
    """馬柱HTMLのキャッシュから 馬ID→馬名 を集める。通信は発生しない。"""
    found: dict[str, str] = {}
    for p in sorted(Path(cache_dir).glob("*_past.html")):
        html = p.read_text(encoding="utf-8", errors="replace")
        for m in HORSE_LINK_RE.finditer(html):
            name = m.group(2).strip()
            if name and not name.startswith("&"):
                found.setdefault(m.group(1), name)
        for m in re.finditer(r"/horse/([0-9a-zA-Z]{8,12})", html):
            found.setdefault(m.group(1), "")
    return found


def horse_name_from_html(html: str) -> str:
    """ページのtitleから馬名を取り出す（「ヤサカスター (Yasaka Star)の競走成績…」）。"""
    if m := re.search(r"<title>([^<(|]+)", html):
        return m.group(1).strip()
    return ""


def parse_horse_results(html: str, horse_id: str, name: str = "") -> list[dict]:
    """馬別成績ページのテーブルを行の辞書に変換する。"""
    name = name or horse_name_from_html(html)
    if not (m := re.search(r"<table[^>]*>(.*?)</table>", html, re.S)):
        return []
    table = m.group(1)

    headers = [_text(t) for t in re.findall(r"<th[^>]*>.*?</th>", table, re.S)]
    # 「タイム指数」など複数行の見出しは先頭語だけ見る
    idx = {}
    for i, h in enumerate(headers):
        key = h.split()[0] if h.split() else ""
        idx.setdefault(key, i)
    needed = ("日付", "開催", "R", "レース名", "頭数", "枠番", "馬番",
              "オッズ", "人気", "着順", "騎手", "斤量", "距離", "馬場")
    if not all(k in idx for k in ("日付", "開催", "着順", "距離")):
        return []

    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
        cells = [_text(c) for c in re.findall(r"<td[^>]*>.*?</td>", row, re.S)]
        if len(cells) < max(idx[k] for k in needed if k in idx) + 1:
            continue
        g = {k: cells[idx[k]] if k in idx else "" for k in needed}
        if not re.match(r"\d{4}/\d{1,2}/\d{1,2}", g["日付"]):
            continue
        kyori = g["距離"]
        shubetsu = kyori[:1] if kyori[:1] in ("ダ", "芝", "障") else ""
        dist = re.sub(r"\D", "", kyori)
        out.append({
            "馬ID": horse_id, "馬名": name,
            "日付": g["日付"].replace("/", "-"),
            # 「2大井3」のような回次付き表記から場名だけ残す
            "場": _KAISAI.sub("", g["開催"]).strip(),
            "R": g["R"], "レース名": g["レース名"], "頭数": g["頭数"],
            "枠番": g["枠番"], "馬番": g["馬番"], "オッズ": g["オッズ"],
            "人気": g["人気"], "着順": g["着順"], "騎手": g["騎手"],
            "斤量": g["斤量"], "馬場種別": shubetsu, "距離": dist, "馬場": g["馬場"],
        })
    return out


def load_records(path: Path | str | None = None) -> dict[str, list[dict]]:
    """馬ID → 戦績（日付昇順）を読み込む。"""
    p = Path(path) if path else RECORDS_PATH
    if not p.exists():
        return {}
    by_horse: dict[str, list[dict]] = {}
    with open(p, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_horse.setdefault(row["馬ID"], []).append(row)
    for rows in by_horse.values():
        rows.sort(key=lambda r: r["日付"])
    return by_horse


def records_before(rows: list[dict], as_of: date | str | None) -> list[dict]:
    """as_of より前の行だけ返す。後知恵を排除するための関門。

    as_of が None（当日の予想）なら全行を返す。
    """
    if as_of is None:
        return rows
    key = as_of.isoformat() if isinstance(as_of, date) else str(as_of)
    return [r for r in rows if r["日付"] < key]


def summarize(rows: list[dict], ba: str | None = None,
              kyori: int | None = None) -> dict:
    """戦績を (出走数, 勝数, 複勝数, 平均着順) にまとめる。

    ba を指定すると当該競馬場、kyori を指定すると当該距離に絞る。
    """
    sel = rows
    if ba:
        sel = [r for r in sel if r["場"] == ba]
    if kyori:
        sel = [r for r in sel if r["距離"] == str(kyori)]
    chaku = [int(r["着順"]) for r in sel if r["着順"].isdigit()]
    return {
        "出走": len(sel),
        "着順あり": len(chaku),
        "勝": sum(1 for c in chaku if c == 1),
        "複": sum(1 for c in chaku if c <= 3),
        "平均着順": (sum(chaku) / len(chaku)) if chaku else None,
    }


def rebuild_from_cache(cache_dir: Path, outpath: Path) -> int:
    """通信せず、キャッシュ済みHTMLだけから戦績CSVを作り直す。"""
    rows: list[dict] = []
    files = sorted(Path(cache_dir).glob("horse_*.html"))
    for p in files:
        hid = p.stem.replace("horse_", "")
        rows.extend(parse_horse_results(
            p.read_text(encoding="utf-8", errors="replace"), hid))
    outpath.parent.mkdir(parents=True, exist_ok=True)
    with open(outpath, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"キャッシュ{len(files)}件 → {len(rows)}行 を {outpath} に書き出し")
    return len(rows)


def collect_horses(
    ids: dict[str, str],
    outpath: Path,
    cache_dir: Path,
    interval: float = 1.5,
    limit: int | None = None,
    progress_every: int = 50,
) -> int:
    """馬別成績を取得してキャッシュし、まとめてCSVに書き出す。

    キャッシュ済みの馬は通信しない（再開可能）。CSVは毎回キャッシュ全体から
    作り直すため、途中で止めても壊れない。
    """
    from .collect import Fetcher   # 循環importを避けるため関数内で読む

    fetcher = Fetcher(cache_dir, interval=interval)
    targets = list(ids.items())[:limit] if limit else list(ids.items())

    rows: list[dict] = []
    fetched = failed = 0
    for i, (hid, name) in enumerate(targets, start=1):
        html = fetcher.get(RESULT_URL.format(horse_id=hid), f"horse_{hid}")
        if html is None:
            failed += 1
            print(f"  [{i}/{len(targets)}] {hid} 取得失敗")
            continue
        fetched += 1
        parsed = parse_horse_results(html, hid, name)
        if not parsed:
            print(f"  [{i}/{len(targets)}] {hid} {name} 戦績なし")
        rows.extend(parsed)
        if i % progress_every == 0:
            print(f"  [{i}/{len(targets)}] 累計{len(rows)}行"
                  f"（取得{fetched} / 失敗{failed}）", flush=True)

    outpath.parent.mkdir(parents=True, exist_ok=True)
    with open(outpath, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"\n{len(targets)}頭 → {len(rows)}行 を {outpath} に書き出し"
          f"（取得{fetched} / 失敗{failed}）")
    return len(rows)
