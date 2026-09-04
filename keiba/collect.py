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
from datetime import date as _Date
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
CALENDAR_URL = "https://nar.netkeiba.com/top/calendar.html?year={year}&month={month}"
SHUTUBA_PAST_URL = "https://nar.netkeiba.com/race/shutuba_past.html?race_id={race_id}"

# 中央（JRA）の開催場。前走がここなら地方への転入初戦とみなす
# 中央（JRA）。race_idは日付ではなく「開催回・日目」で決まるため日付から
# 組み立てられない。開催日→race_id はカレンダーとレース一覧から引く
JRA_VENUE_CODES = {
    "札幌": "01", "函館": "02", "福島": "03", "新潟": "04", "東京": "05",
    "中山": "06", "中京": "07", "京都": "08", "阪神": "09", "小倉": "10",
}
JRA_VENUES = set(JRA_VENUE_CODES)

JRA_RESULT_URL = "https://race.netkeiba.com/race/result.html?race_id={race_id}"
JRA_SHUTUBA_PAST_URL = "https://race.netkeiba.com/race/shutuba_past.html?race_id={race_id}"
JRA_CALENDAR_URL = "https://race.netkeiba.com/top/calendar.html?year={year}&month={month}"
JRA_RACE_LIST_URL = "https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date}"


def jra_venue_of(race_id: str) -> str:
    """race_id の3〜4桁目から競馬場名を返す（'202601020211' → '札幌'）。"""
    code = race_id[4:6]
    for name, c in JRA_VENUE_CODES.items():
        if c == code:
            return name
    return ""
LONG_LAYOFF_DAYS = 180  # これを超える間隔を長期休養明けとする

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

    def get(self, url: str, cache_key: str, retries: int = 2,
            refresh: bool = False) -> str | None:
        """取得してキャッシュに保存する。一時的な失敗は間隔を空けて再試行する。

        refresh=True ならキャッシュを無視して取り直す。発走前に取得した
        「結果が空のページ」がキャッシュに残っている場合に必要になる。
        """
        cached = self.cache_dir / f"{cache_key}.html"
        if cached.exists() and not refresh:
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


def find_race_days(year: int, month: int, venue: str, fetcher: "Fetcher") -> list[str]:
    """指定した月に、その競馬場が開催した日を返す（'YYYY-MM-DD' のリスト）。

    netkeiba のカレンダーには開催ごとに kaisai_id=YYYY<場コード><MMDD> のリンクが
    並んでいるので、場コードで絞り込めば開催日が分かる。総当たりで各日を叩くより
    リクエスト数がはるかに少なくて済む。
    """
    code = VENUE_CODES[venue]
    html = fetcher.get(
        CALENDAR_URL.format(year=year, month=month), f"calendar_{year}{month:02d}"
    )
    if html is None:
        return []
    days = {
        f"{kid[:4]}-{kid[6:8]}-{kid[8:10]}"
        for kid in re.findall(r"kaisai_id=(\d{10})", html)
        if kid[4:6] == code
    }
    return sorted(days)


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
    entries: list[dict] = field(default_factory=list)


RESULT_COLUMNS = ["着順", "枠番", "馬番", "馬名", "性齢", "斤量", "騎手", "タイム",
                  "着差", "人気", "単勝オッズ", "上がり3F", "厩舎", "馬体重"]

# 着順テーブルの見出し → 保存する列名。中央と地方で列数が違う（中央には
# 「コーナー通過順」が入る）ため、位置ではなく見出しで対応付ける
RESULT_HEADER_ALIASES = {
    "着順": ("着順",), "枠番": ("枠",), "馬番": ("馬番",), "馬名": ("馬名",),
    "性齢": ("性齢",), "斤量": ("斤量",), "騎手": ("騎手",), "タイム": ("タイム",),
    "着差": ("着差",), "人気": ("人気",), "単勝オッズ": ("単勝オッズ", "オッズ"),
    "上がり3F": ("後3F", "上り", "上がり"), "厩舎": ("厩舎",), "馬体重": ("馬体重",),
}


def parse_result(html: str, race_id: str) -> RaceData | None:
    info = RaceInfo(race_id=race_id, race_no=int(race_id[-2:]))

    # レース名。中央は <h1 class="RaceName">、地方は <div class="RaceName">
    if m := re.search(r'<(div|h1)[^>]*class="RaceName"[^>]*>.*?</\1>', html, re.S):
        raw_name = re.sub(r"\s+", " ", _text(m.group())).strip()
        for badge in (" 重賞", " OP", " Jpn1", " Jpn2", " Jpn3", " G1", " G2", " G3"):
            if raw_name.endswith(badge):
                raw_name = raw_name[: -len(badge)].strip()
                info.grade = badge.strip()
        info.name = raw_name

    # 中央は等級が名前ではなくアイコンのクラスにしか出ないため、titleから拾う
    # 例: 「キーンランドＣ(G3) 結果・払戻 | 2026年8月23日 札幌11R …」
    if not info.grade and (t := re.search(r"<title>([^<|]+)", html)):
        if g := re.search(r"\((G[123]|Jpn[123]|L|OP)\)", t.group(1)):
            info.grade = g.group(1)
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
        for v in list(VENUE_CODES) + sorted(JRA_VENUE_CODES):
            if v in line:
                info.venue = v
                break
        if h := re.search(r"(\d+)頭", line):
            info.head_count = int(h.group(1))

    if m := re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", html):
        info.date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # 着順テーブル。中央と地方でクラス名が違う（地方だけ ResultMain が付く）ため、
    # 両方に共通する id="All_Result_Table" で拾う
    table = re.search(r'<table[^>]*id="All_Result_Table".*?</table>', html, re.S)
    if not table:
        return None

    # 列は見出し名で対応付ける。中央には「コーナー通過順」が余分に入るため、
    # 位置で切ると厩舎・馬体重が1つずつずれる
    rows = re.findall(r"<tr[^>]*>.*?</tr>", table.group(), re.S)
    header = [_compact(_text(c))
              for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rows[0], re.S)] if rows else []
    index = {}
    for i, col in enumerate(header):
        for want, keys in RESULT_HEADER_ALIASES.items():
            if want not in index and any(k in col for k in keys):
                index[want] = i

    horses = []
    for row in rows:
        if 'class="Header"' in row:
            continue
        cells = [_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) < len(RESULT_COLUMNS) - 1:
            continue
        if index:
            row_data = {col: (cells[i] if i < len(cells) else "")
                        for col, i in index.items()}
            row_data = {col: row_data.get(col, "") for col in RESULT_COLUMNS}
        else:
            row_data = dict(zip(RESULT_COLUMNS, cells[: len(RESULT_COLUMNS)]))
        # 見出し行（馬番セルが「馬 番」等）を確実に落とす
        if not (row_data.get("馬番") or "").strip().isdigit():
            continue
        # 中央の厩舎欄などに改行が入るため、全セルを1行に潰す
        row_data = {k: _compact(v) for k, v in row_data.items()}
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
# 馬柱（出馬表）のパース
# ---------------------------------------------------------------------------

ENTRY_COLUMNS = [
    "馬番", "枠番", "馬名", "性齢", "騎手", "厩舎", "脚質", "単勝オッズ", "人気",
    "前走着順", "前走レース名", "上がり3F", "馬体重",
    "前走開催場", "前走間隔日数", "間隔表記", "転入初戦", "長期休養明け", "直近3走JRA数",
    "血統父", "血統母父", "調教評価",
]

KYAKUSHITSU = {"逃": "逃げ", "先": "先行", "差": "差し", "追": "追込"}


def _parse_past_cell(body: str) -> dict:
    """馬柱の過去走セル1つを辞書にする。"""
    t = _text(body)
    out: dict = {}
    if m := re.match(r"(\d{4})\.(\d{2})\.(\d{2})\s+(\S+)", t):
        out["日付"] = _Date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        out["開催場"] = m.group(4)
    if m := re.search(r"\d{4}\.\d{2}\.\d{2}\s+\S+\s+(\d+)\s", t):
        out["着順"] = int(m.group(1))
    if m := re.search(r"\d{4}\.\d{2}\.\d{2}\s+\S+\s+\d+\s+(\S.*?)\s+[芝ダ障]", t):
        out["レース名"] = m.group(1).strip()
    if m := re.search(r"\(([\d.]+)\)\s+\d+\(", t):
        out["上がり3F"] = float(m.group(1))
    return out


def parse_shutuba_past(html: str, race_date: _Date) -> list[dict]:
    """馬柱ページから、脚質・間隔・血統・オッズ・前走情報を取り出す。

    確定結果には含まれない事前情報（脚質、前走からの間隔、前走の開催場、血統）が
    取れる。前走が中央の開催場なら転入初戦、間隔が180日超なら長期休養明けとする。
    """
    # 馬名などのセルは、地方が <dt class="Horse01">、中央が <div class="Horse01">
    # と囲みタグが違う。後方参照で開始タグと閉じタグを揃えて両方拾う
    horses = []
    for row in re.findall(r'<tr[^>]*class="HorseList".*?</tr>', html, re.S):
        row = row.replace("&nbsp;", " ")  # オッズ欄などに実体参照が混ざる
        h: dict = {}
        if m := re.search(r'<td class="Waku(\d+)"', row):
            h["枠番"] = int(m.group(1))
        if m := re.search(r'<td class="Waku"[^>]*>\s*(\d+)\s*</td>', row):
            h["馬番"] = int(m.group(1))
        for key, cls in (("血統父", "Horse01"), ("馬名", "Horse02"),
                         ("血統母父", "Horse04"), ("厩舎", "Horse05")):
            if m := re.search(rf'<(dt|div) class="{cls}[^"]*">(.*?)</\1>', row, re.S):
                h[key] = _text(m.group(2)).strip("()")
        if m := re.search(r'<(dt|div) class="Horse06[^"]*">(.*?)</\1>', row, re.S):
            body = m.group(2)
            k = (re.search(r'<div class="Type[^"]*"><span>(.*?)</span>', body)
                 or re.search(r'<span class="kyakusitu">(.*?)</span>', body))
            if k:
                h["脚質"] = KYAKUSHITSU.get(_text(k.group(1)), "")
            rest = re.sub(r'<div class="Type.*?</div>', "", body, flags=re.S)
            rest = re.sub(r'<span class="kyakusitu">.*?</span>', "", rest, flags=re.S)
            h["間隔表記"] = _text(rest)
        if m := re.search(r'<(dt|div) class="Horse07[^"]*">(.*?)</\1>', row, re.S):
            body = m.group(2)
            if w := re.search(r'<div class="Weight[^"]*">(\d+)kg<span>\(([-+]?\d+)\)', body):
                h["馬体重"] = f"{w.group(1)}({w.group(2)})"
            # 上位人気は <span class="Odds_Ninki"> で囲まれ、それ以外は素の数値で入る
            if pop := re.search(r'<div class="Popular">(.*?)</div>', body, re.S):
                ptxt = _text(pop.group(1))
                if o := re.search(r"([\d.]+)\s*\((\d+)人気\)", ptxt):
                    h["単勝オッズ"], h["人気"] = float(o.group(1)), int(o.group(2))
        if m := re.search(r'<span class="Barei">(.*?)</span>', row):
            h["性齢"] = _text(m.group(1))[:2]
        if m := re.search(r'<td class="Jockey".*?</td>', row, re.S):
            names = re.findall(r">([^<>]{2,10})</a>", m.group())
            if names:
                h["騎手"] = names[-1].strip()

        pasts = [_parse_past_cell(b) for _, b in
                 re.findall(r'<td class="(Past[^"]*)"[^>]*>(.*?)</td>', row, re.S)]
        pasts = [p for p in pasts if p.get("日付")]
        if pasts:
            p0 = pasts[0]
            interval = (race_date - p0["日付"]).days
            h["前走着順"] = p0.get("着順")
            h["前走レース名"] = p0.get("レース名", "")
            h["前走開催場"] = p0.get("開催場")
            h["上がり3F"] = p0.get("上がり3F")
            h["前走間隔日数"] = interval
            h["長期休養明け"] = "Y" if interval > LONG_LAYOFF_DAYS else ""
            h["転入初戦"] = "Y" if p0.get("開催場") in JRA_VENUES else ""
            h["直近3走JRA数"] = sum(1 for p in pasts[:3] if p.get("開催場") in JRA_VENUES)
        # 馬番と馬名の両方が取れた行だけ採用する。中央の馬柱には
        # 「[馬記号] 馬名 [ブリンカー]」という凡例行が混ざるため
        if h.get("馬名") and isinstance(h.get("馬番"), int):
            horses.append(h)
    return horses


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
    safe_name = re.sub(r'[\\/:*?"<>|\s]+', "", i.name) or f"{i.race_no:02d}R"
    prefix = f"{i.date}_{i.venue}{i.race_no:02d}R_{safe_name}"
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

    if data.entries:
        # 馬柱から取れた事前情報（脚質・間隔・血統・転入初戦など）
        p = outdir / f"{prefix}_出走馬.csv"
        _write_csv(p, ENTRY_COLUMNS, data.entries)
        out["出走馬"] = p

    return out


def collect_month(
    year: int,
    month: int,
    venue: str,
    race_numbers: list[int],
    outdir: Path,
    cache_dir: Path,
    interval: float = REQUEST_INTERVAL,
    force: bool = False,
) -> list[RaceData]:
    """その月の開催日をカレンダーから調べ、全開催日分をまとめて取得する。"""
    fetcher = Fetcher(cache_dir, interval)
    days = find_race_days(year, month, venue, fetcher)
    if not days:
        print(f"  {year}年{month}月に{venue}の開催は見つかりませんでした")
        return []

    print(f"  {year}年{month}月の{venue}開催: {len(days)}日 ({', '.join(d[5:] for d in days)})")
    collected = []
    for day in days:
        print(f"\n  [{day}]")
        collected += collect_day(day, venue, race_numbers, outdir, cache_dir,
                                 interval, fetcher, force)
    return collected


def _already_collected(outdir: Path, date: str, venue: str, race_no: int) -> bool:
    """そのレースの結果CSVと出走馬CSVが両方そろっているか。"""
    prefix = f"{date}_{venue}{race_no:02d}R_"
    has_result = any(outdir.glob(f"{prefix}*_結果.csv"))
    has_entries = any(outdir.glob(f"{prefix}*_出走馬.csv"))
    return has_result and has_entries


def backfill_odds(data: "RaceData") -> int:
    """馬柱にオッズが無い場合、結果ページの確定オッズ・人気を出走馬に補う。

    中央の馬柱は発走後にオッズの配信を止めるため（`---.-` になる）、
    過去レースを集めると単勝オッズ・人気が空になる。結果ページには
    確定オッズと人気が載っているので、馬番で突き合わせて補う。

    注意: これは**確定オッズ**であって朝のオッズではない。買い目の型は
    最終オッズで判定するのが正しい（CLAUDE.md）ので検証用途には適するが、
    「朝の時点で分かった情報」として扱ってはいけない。
    """
    by_umaban = {}
    for row in data.horses:
        if (u := row.get("馬番", "")).isdigit():
            by_umaban[int(u)] = row
    filled = 0
    for e in data.entries:
        if e.get("単勝オッズ") is not None:
            continue
        r = by_umaban.get(e.get("馬番"))
        if not r:
            continue
        try:
            e["単勝オッズ"] = float(r.get("単勝オッズ", ""))
            e["人気"] = int(r.get("人気", ""))
            filled += 1
        except (TypeError, ValueError):
            continue
    return filled


def collect_day(
    date: str,
    venue: str,
    race_numbers: list[int],
    outdir: Path,
    cache_dir: Path,
    interval: float = REQUEST_INTERVAL,
    fetcher: "Fetcher | None" = None,
    force: bool = False,
) -> list[RaceData]:
    fetcher = fetcher or Fetcher(cache_dir, interval)
    collected = []
    outdir = Path(outdir)

    for no in race_numbers:
        race_id = build_race_id(date, venue, no)
        # 既に保存済みなら通信しない（中断したところから再開できるようにする）
        if not force and _already_collected(outdir, date, venue, no):
            print(f"  {venue}{no:>2}R → 取得済みのためスキップ")
            continue
        print(f"  {venue}{no:>2}R (race_id={race_id})", end=" ")
        html = fetcher.get(RESULT_URL.format(race_id=race_id), race_id, refresh=force)
        if html is None:
            print("→ 取得できず")
            continue
        data = parse_result(html, race_id)
        if data is None or not data.horses:
            print("→ 結果未確定またはレースなし")
            continue
        data.info.date = data.info.date or date
        data.info.venue = data.info.venue or venue
        # 馬柱（事前情報）も取得する。結果だけでは脚質・間隔・血統が分からないため
        past_html = fetcher.get(
            SHUTUBA_PAST_URL.format(race_id=race_id), f"{race_id}_past", refresh=force
        )
        if past_html:
            y, mo, d = (int(x) for x in data.info.date.split("-"))
            data.entries = parse_shutuba_past(past_html, _Date(y, mo, d))
            backfill_odds(data)

        paths = save_race(data, outdir)
        print(f"→ {data.info.name} ({len(data.horses)}頭, 払戻{len(data.payouts)}件"
              f", 馬柱{len(data.entries)}頭)")
        collected.append(data)

    return collected


# ---------------------------------------------------------------------------
# 中央（JRA）の収集
# ---------------------------------------------------------------------------

def find_jra_race_days(year: int, month: int, fetcher: "Fetcher") -> list[str]:
    """その月の中央開催日を返す（'YYYY-MM-DD' のリスト）。"""
    html = fetcher.get(
        JRA_CALENDAR_URL.format(year=year, month=month), f"jra_calendar_{year}{month:02d}"
    )
    if html is None:
        return []
    days = sorted({f"{d[:4]}-{d[4:6]}-{d[6:]}"
                   for d in re.findall(r"kaisai_date=(\d{8})", html)})
    return [d for d in days if d.startswith(f"{year}-{month:02d}")]


def find_jra_race_ids(date: str, fetcher: "Fetcher", venue: str | None = None) -> list[str]:
    """開催日のrace_idを返す。中央のrace_idは開催回・日目で決まり日付から
    組み立てられないため、その日のレース一覧から引く。"""
    key = date.replace("-", "")
    html = fetcher.get(JRA_RACE_LIST_URL.format(date=key), f"jra_list_{key}")
    if html is None:
        return []
    ids = sorted({r for r in re.findall(r"race_id=(\d{12})", html)})
    if venue:
        code = JRA_VENUE_CODES.get(venue)
        ids = [r for r in ids if r[4:6] == code]
    return ids


def collect_jra_day(
    date: str,
    outdir: Path,
    cache_dir: Path,
    venue: str | None = None,
    race_numbers: list[int] | None = None,
    interval: float = REQUEST_INTERVAL,
    fetcher: "Fetcher | None" = None,
    force: bool = False,
) -> list[RaceData]:
    """中央のある開催日を収集する。venue省略時はその日の全場。"""
    fetcher = fetcher or Fetcher(cache_dir, interval)
    outdir = Path(outdir)
    collected = []

    for race_id in find_jra_race_ids(date, fetcher, venue):
        no = int(race_id[-2:])
        if race_numbers and no not in race_numbers:
            continue
        v = jra_venue_of(race_id)
        if not force and _already_collected(outdir, date, v, no):
            print(f"  {v}{no:>2}R → 取得済みのためスキップ")
            continue
        print(f"  {v}{no:>2}R (race_id={race_id})", end=" ")
        html = fetcher.get(JRA_RESULT_URL.format(race_id=race_id), race_id, refresh=force)
        if html is None:
            print("→ 取得できず")
            continue
        data = parse_result(html, race_id)
        if data is None or not data.horses:
            print("→ 結果未確定またはレースなし")
            continue
        data.info.date = data.info.date or date
        data.info.venue = data.info.venue or v

        past_html = fetcher.get(
            JRA_SHUTUBA_PAST_URL.format(race_id=race_id), f"{race_id}_past", refresh=force
        )
        if past_html:
            y, mo, d = (int(x) for x in data.info.date.split("-"))
            data.entries = parse_shutuba_past(past_html, _Date(y, mo, d))
            n = backfill_odds(data)
        else:
            n = 0

        save_race(data, outdir)
        print(f"→ {data.info.name}{'(' + data.info.grade + ')' if data.info.grade else ''} "
              f"({len(data.horses)}頭, 払戻{len(data.payouts)}件, 馬柱{len(data.entries)}頭"
              f"{f', オッズ補完{n}頭' if n else ''})")
        collected.append(data)
    return collected


def collect_jra_month(
    year: int,
    month: int,
    outdir: Path,
    cache_dir: Path,
    venue: str | None = None,
    race_numbers: list[int] | None = None,
    interval: float = REQUEST_INTERVAL,
    force: bool = False,
) -> list[RaceData]:
    fetcher = Fetcher(cache_dir, interval)
    days = find_jra_race_days(year, month, fetcher)
    if not days:
        print(f"{year}-{month:02d} の中央開催日が見つかりませんでした")
        return []
    print(f"{year}-{month:02d} の中央開催日: {len(days)}日")
    out = []
    for d in days:
        print(f"\n  [{d}]")
        out.extend(collect_jra_day(d, outdir, cache_dir, venue, race_numbers,
                                   interval, fetcher, force))
    return out
