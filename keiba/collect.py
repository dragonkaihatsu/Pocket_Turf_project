"""レース結果の自動収集（netkeiba 地方競馬版）。

日付と競馬場を指定して、その日の各レースの確定結果・払戻・コーナー通過順位を
取得し、本システムが読めるCSV形式で保存する。集めた結果は `stats` コマンドの
母数になる。

取得マナー:
    - リクエスト間隔を空ける（既定1.5秒）
    - 取得したHTMLはローカルにキャッシュし、同じレースを再取得しない
    - User-Agent を明示する
    個人の予想検証を目的とした低頻度アクセスを想定している。実行前に対象サイトの
    利用規約を確認すること。大量・高頻度の取得はしない。
"""
from __future__ import annotations

import csv
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import requests

USER_AGENT = "Mozilla/5.0 (compatible; keiba-personal-research)"
REQUEST_INTERVAL = 1.5  # 秒
TIMEOUT = 30

# netkeiba の場コード（地方競馬）
VENUE_CODES = {
    "門別": "30", "盛岡": "35", "水沢": "36", "浦和": "42", "船橋": "43",
    "大井": "44", "川崎": "45", "金沢": "46", "笠松": "47", "名古屋": "48",
    "園田": "50", "姫路": "51", "高知": "54", "佐賀": "55",
}

RESULT_URL = "https://nar.netkeiba.com/race/result.html?race_id={race_id}"

PAYOUT_KINDS = {
    "Tansho": "単勝", "Fukusho": "複勝", "Wakuren": "枠連", "Umaren": "馬連",
    "Wide": "ワイド", "Umatan": "馬単", "Fuku3": "3連複", "Tan3": "3連単",
}


def build_race_id(date: str, venue: str, race_no: int) -> str:
    """date='2026-09-02', venue='大井', race_no=11 → '202644090211'"""
    if venue not in VENUE_CODES:
        raise ValueError(f"未対応の競馬場: {venue}（対応: {'/'.join(VENUE_CODES)}）")
    y, m, d = date.split("-")
    return f"{y}{VENUE_CODES[venue]}{m}{d}{race_no:02d}"


# ---------------------------------------------------------------------------
# 取得
# ---------------------------------------------------------------------------

class Fetcher:
    def __init__(self, cache_dir: Path, interval: float = REQUEST_INTERVAL):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.interval = interval
        self._last_request = 0.0

    def get(self, url: str, cache_key: str, retries: int = 2) -> str | None:
        """取得してキャッシュに保存する。一時的な失敗は間隔を空けて再試行する。"""
        cached = self.cache_dir / f"{cache_key}.html"
        if cached.exists():
            return cached.read_text(encoding="utf-8")

        for attempt in range(retries + 1):
            wait = self.interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
                status = res.status_code
            except requests.RequestException as e:
                res, status = None, f"{type(e).__name__}"
            finally:
                self._last_request = time.monotonic()

            if res is not None and status == 200:
                res.encoding = res.apparent_encoding or "utf-8"
                cached.write_text(res.text, encoding="utf-8")
                return res.text

            if attempt < retries:
                backoff = self.interval * (attempt + 2)  # 3秒 → 4.5秒
                print(f"    {status} → {backoff:.1f}秒後に再試行", end=" ")
                time.sleep(backoff)
            else:
                print(f"    {status}（再試行しても失敗）", end=" ")
        return None


# ---------------------------------------------------------------------------
# パース
# ---------------------------------------------------------------------------

def _compact(s: str) -> str:
    """馬番の羅列や馬体重など、空白を含まないのが自然な値から空白を除く。"""
    return re.sub(r"\s+", "", s)


def _text(html: str) -> str:
    """タグを除いて空白を整えた文字列にする。"""
    t = re.sub(r"<br\s*/?>", "\n", html)
    t = re.sub(r"<[^>]+>", " ", t)
    t = unicodedata.normalize("NFKC", t.replace("&nbsp;", " "))
    return re.sub(r"[ \t]+", " ", t).strip()


@dataclass
class RaceInfo:
    race_id: str = ""
    date: str = ""
    venue: str = ""
    race_no: int = 0
    name: str = ""
    grade: str = ""
    post_time: str = ""
    surface: str = ""       # 例: ダ1200m（右）
    kyori: int | None = None
    weather: str = ""
    baba: str = ""
    head_count: int | None = None


@dataclass
class RaceData:
    info: RaceInfo
    horses: list[dict] = field(default_factory=list)
    payouts: list[dict] = field(default_factory=list)
    corners: list[dict] = field(default_factory=list)


RESULT_COLUMNS = ["着順", "枠番", "馬番", "馬名", "性齢", "斤量", "騎手", "タイム",
                  "着差", "人気", "単勝オッズ", "上がり3F", "厩舎", "馬体重"]


def parse_result(html: str, race_id: str) -> RaceData | None:
    info = RaceInfo(race_id=race_id, race_no=int(race_id[-2:]))

    if m := re.search(r'<div[^>]*class="RaceName"[^>]*>.*?</div>', html, re.S):
        info.name = _text(m.group()).replace(" 重賞", "").strip()
    if m := re.search(r'<div[^>]*class="RaceData01"[^>]*>.*?</div>', html, re.S):
        pass

    if m := re.search(r'<div[^>]*class="RaceData01"[^>]*>.*?</div>', html, re.S):
        line = _text(m.group())
        if t := re.search(r"(\d{1,2}:\d{2})発走", line):
            info.post_time = t.group(1)
        if s := re.search(r"([芝ダ障])\s*(\d+)m\s*(\([^)]*\))?", line):
            info.surface = f"{s.group(1)}{s.group(2)}m{s.group(3) or ''}"
            info.kyori = int(s.group(2))
        if w := re.search(r"天候\s*:\s*(\S+)", line):
            info.weather = w.group(1)
        if b := re.search(r"馬場\s*:\s*(\S+)", line):
            info.baba = b.group(1)

    if m := re.search(r'<div[^>]*class="RaceData02"[^>]*>.*?</div>', html, re.S):
        line = _text(m.group())
        for v in VENUE_CODES:
            if v in line:
                info.venue = v
                break
        if h := re.search(r"(\d+)頭", line):
            info.head_count = int(h.group(1))

    if m := re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", html):
        info.date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    table = re.search(r'<table[^>]*ResultMain.*?</table>', html, re.S)
    if not table:
        return None

    horses = []
    for row in re.findall(r"<tr[^>]*>.*?</tr>", table.group(), re.S):
        if 'class="Header"' in row:
            continue
        cells = [_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) < len(RESULT_COLUMNS):
            continue
        row_data = dict(zip(RESULT_COLUMNS, cells[: len(RESULT_COLUMNS)]))
        row_data["馬体重"] = _compact(row_data.get("馬体重", ""))
        horses.append(row_data)
    if not horses:
        return None

    payouts = []
    for cls, kind in PAYOUT_KINDS.items():
        row = re.search(rf'<tr[^>]*class="{cls}"[^>]*>.*?</tr>', html, re.S)
        if not row:
            continue
        body = row.group()
        result_td = re.search(r'<td[^>]*class="Result"[^>]*>.*?</td>', body, re.S)
        payout_td = re.search(r'<td[^>]*class="Payout"[^>]*>.*?</td>', body, re.S)
        ninki_td = re.search(r'<td[^>]*class="Ninki"[^>]*>.*?</td>', body, re.S)
        if not (result_td and payout_td):
            continue

        if "<ul" in result_td.group():
            combos = [
                [n for n in re.findall(r"<span>(\d+)</span>", ul)]
                for ul in re.findall(r"<ul>.*?</ul>", result_td.group(), re.S)
            ]
        else:
            combos = [[n] for n in re.findall(r"<span>(\d+)</span>", result_td.group())]

        amounts = [a.replace(",", "") for a in re.findall(r"([\d,]+)円", payout_td.group())]
        ninki = re.findall(r"(\d+)人気", ninki_td.group()) if ninki_td else []

        for i, combo in enumerate(combos):
            if i >= len(amounts) or not combo:
                continue
            payouts.append({
                "券種": kind,
                "組み合わせ": "-".join(combo),
                "配当": amounts[i],
                "人気": ninki[i] if i < len(ninki) else "",
            })

    corners = []
    if m := re.search(r'<table[^>]*Corner_Num.*?</table>', html, re.S):
        for row in re.findall(r"<tr>.*?</tr>", m.group(), re.S):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
            if len(cells) >= 2:
                corners.append({
                    "コーナー": _compact(_text(cells[0])),
                    "通過順": _compact(_text(cells[1])),
                })

    return RaceData(info=info, horses=horses, payouts=payouts, corners=corners)


# ---------------------------------------------------------------------------
# 保存
# ---------------------------------------------------------------------------

def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def save_race(data: RaceData, outdir: Path) -> dict[str, Path]:
    """既存フォーマット（結果CSV・配当CSV）＋通過順・出走馬CSVを書き出す。"""
    i = data.info
    prefix = f"{i.date}_{i.venue}{i.race_no:02d}R_{i.name}".replace("/", "_")
    out: dict[str, Path] = {}

    p = outdir / f"{prefix}_結果.csv"
    _write_csv(p, RESULT_COLUMNS, data.horses)
    out["結果"] = p

    if data.payouts:
        p = outdir / f"{prefix}_配当.csv"
        _write_csv(p, ["券種", "組み合わせ", "配当", "人気"], data.payouts)
        out["配当"] = p

    if data.corners:
        p = outdir / f"{prefix}_通過順.csv"
        _write_csv(p, ["コーナー", "通過順"], data.corners)
        out["通過順"] = p

    # 確定結果から出走馬CSVを復元する（前走情報は含まれないため、
    # スコアリングに使うときは前走着順などを別途補う必要がある）
    entries = [
        {"馬番": h["馬番"], "枠番": h["枠番"], "馬名": h["馬名"], "性齢": h["性齢"],
         "斤量": h["斤量"], "騎手": h["騎手"], "上がり3F": h["上がり3F"],
         "前走着順": "", "前走レース名": "", "調教評価": "", "脚質": ""}
        for h in data.horses
    ]
    p = outdir / f"{prefix}_出走馬.csv"
    _write_csv(p, ["馬番", "枠番", "馬名", "性齢", "斤量", "騎手", "前走着順",
                   "前走レース名", "上がり3F", "調教評価", "脚質"], entries)
    out["出走馬"] = p

    return out


def collect_day(
    date: str,
    venue: str,
    race_numbers: list[int],
    outdir: Path,
    cache_dir: Path,
    interval: float = REQUEST_INTERVAL,
) -> list[RaceData]:
    fetcher = Fetcher(cache_dir, interval)
    collected = []

    for no in race_numbers:
        race_id = build_race_id(date, venue, no)
        print(f"  {venue}{no:>2}R (race_id={race_id})", end=" ")
        html = fetcher.get(RESULT_URL.format(race_id=race_id), race_id)
        if html is None:
            print("→ 取得できず")
            continue
        data = parse_result(html, race_id)
        if data is None or not data.horses:
            print("→ 結果未確定またはレースなし")
            continue
        data.info.date = data.info.date or date
        data.info.venue = data.info.venue or venue
        paths = save_race(data, outdir)
        print(f"→ {data.info.name} ({len(data.horses)}頭, 払戻{len(data.payouts)}件)")
        collected.append(data)

    return collected
