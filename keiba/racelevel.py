"""レース水準（走破タイムから測ったレースのレベル）と、持ち時計の分解。

## なぜ時計でレースのレベルを測るのか

CLAUDE.mdは「前走内容のレース格割引」を長く宿題に残していたが、理由は
**等級データが `race_info.csv` の1〜4%しか埋まらない**（結果ページの
アイコンからしか読めず、キャッシュが運用の途中で縮む）ことだった。
レース名からも切り出せない——固有名のレースが2,401本あり、2勝クラスの
特別からG1までが同じ箱に入る。

一方 `keiba/mochidokei.py` の留保3は「距離だけで正規化するので、指数は
クラスを部分的に含む」と書いている。**それは欠点として書かれていたが、
裏返せばレース水準そのものが時計から測れるという意味**である。

    レース水準 = そのレースの出走馬の持ち時計指数の中央値

中央値にするのは、1頭の逃げ切りや大差負けで評価が動かないため。

## 検算（取得経路の違う3つ・`scripts/race_level.py`）

| 突き合わせた相手 | 結果 |
|---|---|
| レース名のクラス表記（文字列なので100%確実） | **完全に単調**（下の CLASS_MEDIANS） |
| `race_info.csv` の等級列（アイコン由来） | **一致しない**（OP+0.93 / L+0.82 / G3+0.89 / G2+0.85 / G1+0.99） |
| メンバー質（出走馬の過去勝率の平均・時計を使わない） | r=+0.491・4分位で単調 |

→ **時計は条件クラスの段階をきれいに測るが、オープン以上の格
（L/G3/G2/G1）は測らない。** 物理的に筋が通る（オープン以上はどれも速く、
格は賞金と相手の質であって時計ではない）。等級が埋まっている295レースを
まとめると +0.880（n=295・SE0.035）で2勝クラス +0.580 とは離れるので、
`class_label()` は**オープン級までは言い、その先は言い分けない**。

## 持ち時計はこの2成分の和である（恒等式）

水準を「レース内の中央値」と定義したので、

    馬の絶対指数 = 走ったレースの水準 ＋ そのレース内での相対（着差）

に厳密に分かれる。`scripts/race_level.py` で同一人気帯内の複勝リフトを
測ると（メンバー平均との差・上位1/3・30,985出走）:

| 成分 | 1-3人気 | 4-5人気 | 6-9人気 | 10人気以下 |
|---|---|---|---|---|
| **絶対差（現行のスコア）** | **+6.6p** | +4.4p 反転 | **+3.6p** | **+3.4p** |
| 水準差 | +1.7p 差なし | **+5.1p** | **+2.4p** | **+0.9p** |
| 相対差 | **+5.4p** | −1.9p 差なし | +3.2p 反転 | **+3.0p** |

太字は 差あり＋期間再現（2024/2025/2026）。**絶対差と水準差が3帯ずつで
並び、成分ごとに得意な帯が違う**:

  人気馬（1-3番人気）は **相対**（同じ相手をどれだけ離すか）が効き、
  水準は差なし。中穴（4-5番人気）は **水準**（どのクラスで戦ってきたか）が
  効き、相対は逆を向く。

2×2の交差（対照＝どちらも中位）で、差あり＋期間再現を通ったのは4つ:

| 区分 | n | リフト | 読み |
|---|---|---|---|
| 1-3番人気 × 両方↑ | 1,270 | **+14.1p** | 水準も着差も上位なら強い |
| 4-5番人気 × 水準↓×相対↑ | 920 | **−4.6p** | 弱い相手を離してきただけ |
| 6-9番人気 × 両方↓ | 711 | **−5.4p** | どちらも下位 |
| 10番人気以下 × 両方↓ | 1,796 | **−2.4p** | 同 |

**採点は現行のまま**（絶対＝2成分の和をメンバー相対で使う）。成分ごとに
重みを変える根拠は無い（帯によって得意が入れ替わるだけで、和より良い
組み方は見つかっていない）。ここは第1段階＝表示のみで、上の4つの形に
当たる馬にだけ一言を出す。

## 留保

- 基準表（`base_times.json`）を作り直すと値が動く。`前走水準×前走着順` の
  「4-5番人気 前走二桁×高水準」は +4.4p 判定不能 → +6.9p 差あり[再現] と
  変わった。**この検証の数字は基準表とセットで読む**
- 順位→率と同じく in-sample。3分位の境目もコーパス全体から取っている
- 回収率は測っていない（正解率の4〜9倍の母数を要するため、この母数では
  判定できない）
"""
from __future__ import annotations

import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from . import mochidokei as mk
from . import profile

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})_")

# 水準を作るのに要求する、指数が計算できた頭数。下回るレースは水準なし
MIN_FIELD_FOR_LEVEL = 5

# レース名から読めるクラス。**この4つは文字列なので100%確実**。
# 3勝クラスは必ず固有名（特別）が付くためレース名からは読めない
NAME_CLASSES = (("新馬", "新馬"), ("未勝利", "未勝利"),
                ("1勝クラス", "1勝"), ("2勝クラス", "2勝"))
CLASS_ORDER = ["新馬", "未勝利", "1勝", "2勝", "固有名"]
GRADE_ORDER = ["OP", "L", "G3", "G2", "G1"]

# `scripts/race_level.py` の実測（中央1-12R・8,947レース）。
# クラスの順序と完全に単調に並ぶ
CLASS_MEDIANS = {"新馬": -0.911, "未勝利": -0.319, "1勝": 0.358,
                 "2勝": 0.580, "固有名": 0.681}
# 等級が埋まっている295レース（OP/L/G3/G2/G1）の水準の中央値。
# 2勝クラス(+0.580)と +0.880(n=295・SE0.035) は明確に離れるので、
# 「オープン級」はここで線を引ける。**その上の格（L/G3/G2/G1）は
# 互いに離れないので言い分けない**
OPEN_MEDIAN = 0.880

# 帯の境目は隣り合う区分の中央値の中点
CLASS_BOUNDS = ((-0.615, "新馬級"), (0.020, "未勝利級"),
                (0.469, "1勝クラス級"), (0.730, "2〜3勝クラス級"))
TOP_LABEL = "オープン級"


def name_class(name: str) -> str:
    """レース名からクラスを読む。障害は除外（時計の性質が違う）。"""
    if "障害" in name:
        return "障害"
    for token, label in NAME_CLASSES:
        if token in name:
            return label
    return "固有名"


def class_label(level: float) -> str:
    """水準を「〜級」に言い換える。上限は 2勝クラス以上でひとまとめ。"""
    for bound, label in CLASS_BOUNDS:
        if level < bound:
            return label
    return TOP_LABEL


# ---------------------------------------------------------------------------
# 表を作る／読む
# ---------------------------------------------------------------------------

def build_levels(dir_: str, races: str, months: str | None,
                 race_info: str, base_times: str,
                 ) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """(stem → レース, 馬名 → 出走の並び) を返す。通信ゼロ。

    `scripts/race_level.py`（測る）と `scripts/build_race_level.py`（表を作る）
    の共通の入口。**同じ計算を2か所に書くと静かにずれる**ので必ずここを通す。
    """
    from .racefiles import race_number, race_venue, result_paths

    info: dict[str, dict] = {}
    if Path(race_info).exists():
        for row in csv.DictReader(open(race_info, encoding="utf-8-sig")):
            info[row["stem"]] = row
    base = mk.BaseTimes.load(base_times)

    out: dict[str, dict] = {}
    runs: dict[str, list[dict]] = defaultdict(list)
    miss: Counter = Counter()

    for fp in result_paths(dir_, races, months):
        f = Path(fp)
        stem = f.name[: -len("_結果.csv")]
        m = DATE_RE.match(stem)
        ri = info.get(stem)
        ba = race_venue(f.name)
        if not (m and ba and ri and ri.get("距離") and ri.get("馬場種別")
                and ri.get("馬場")):
            miss["レース条件なし"] += 1
            continue
        if ri["馬場種別"] not in ("芝", "ダ"):
            miss["障害など"] += 1
            continue
        baba = mk.canon_baba(ri["馬場"])
        rows = [r for r in csv.DictReader(open(f, encoding="utf-8-sig"))
                if (r.get("着順") or "").isdigit()]
        if not rows:
            miss["着順なし"] += 1
            continue

        # 前走の特定に使う間隔日数（9-12R以外に挟まれた本当の前走を
        # 取りこぼしたペアを除くため）
        interval: dict[str, int | None] = {}
        ent = f.with_name(stem + "_出走馬.csv")
        if ent.exists():
            for e in csv.DictReader(open(ent, encoding="utf-8-sig")):
                nm = (e.get("馬名") or "").strip()
                iv = (e.get("前走間隔日数") or "").strip()
                if nm:
                    interval[nm] = int(iv) if iv.isdigit() else None

        idx: dict[str, float] = {}
        for r in rows:
            nm = (r.get("馬名") or "").strip()
            v = base.index(mk.parse_time(r.get("タイム")), ba,
                           ri["馬場種別"], ri["距離"], baba)
            if nm and v is not None:
                idx[nm] = v
        if len(idx) < MIN_FIELD_FOR_LEVEL:
            miss["指数が足りない"] += 1
            continue

        chaku = {(r.get("馬名") or "").strip(): int(r["着順"]) for r in rows}
        ninki = {(r.get("馬名") or "").strip():
                 (int(nk) if (nk := (r.get("人気") or "").strip()).isdigit()
                  else None) for r in rows}
        win = min(idx, key=lambda n: chaku.get(n, 99))
        level = statistics.median(idx.values())
        rno = race_number(f.name)
        out[stem] = {
            "stem": stem, "日付": m.group(1), "場": ba, "R": rno,
            "芝ダ": ri["馬場種別"], "距離": int(ri["距離"]), "馬場": baba or "",
            "レース名": ri.get("レース名", ""),
            "等級": (ri.get("等級") or "").strip(),
            "クラス": name_class(ri.get("レース名", "")),
            "頭数": len(rows), "指数頭数": len(idx),
            "水準": level, "勝ち馬指数": idx[win],
        }
        for nm, v in idx.items():
            runs[nm].append({
                "馬名": nm, "stem": stem, "日付": m.group(1), "R": rno,
                "着順": chaku.get(nm), "人気": ninki.get(nm),
                "頭数": len(rows), "指数": v, "水準": level, "相対": v - level,
                "interval": interval.get(nm),
            })
        miss["採用"] += 1

    for v in runs.values():
        v.sort(key=lambda r: r["日付"])
    return out, dict(runs)


def table_key(d: str, ba: str, r) -> str:
    return f"{d}{mk.SEP}{ba}{mk.SEP}{r}"


def save_table(races: dict[str, dict], path: Path | str) -> None:
    """予想時に引くための小さな表。stem ではなく (日付|場|R) で引く
    （戦績CSVは stem を持たないため）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tbl = {table_key(r["日付"], r["場"], r["R"]): round(r["水準"], 4)
           for r in races.values()}
    p.write_text(json.dumps({
        "水準": tbl,
        "クラス中央値": CLASS_MEDIANS,
        "メタ": {"レース数": len(tbl),
                 "説明": "出走馬の持ち時計指数の中央値。"
                         "オープン以上の格は測れない（等級との検算が不一致）"},
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def load_table(path: Path | str | None = None,
               venue: str | None = None) -> dict[str, float]:
    """(日付|場|R) → 水準。無ければ空（数字を作らない）。

    **プロファイルは競馬場から決める**（`active()` に頼らない）。
    地方の実測値を中央に当てる事故を4回踏んでいるため（CLAUDE.md
    「同じプロファイル取り違えを1日に3か所で踏んだ」）。
    """
    p = (Path(path) if path
         else profile.for_venue(venue).path("race_levels.json"))
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("水準", {})
    except (ValueError, OSError):
        return {}


# ---------------------------------------------------------------------------
# 馬ごとの分解
# ---------------------------------------------------------------------------

@dataclass
class Split:
    """1頭の持ち時計を「走ってきた水準」と「レース内相対」に分けたもの。"""

    n: int
    level: float      # 走ってきたレースの水準（平均）
    margin: float     # そのレース内での相対（平均）

    @property
    def total(self) -> float:
        """絶対指数。水準＋相対（恒等式）。"""
        return self.level + self.margin

    def label(self) -> str:
        return class_label(self.level)


def level_of_record(r: dict, table: dict[str, float]) -> float | None:
    """戦績1行の走ったレースの水準。表に無ければ None。"""
    d = (r.get("日付") or "").strip()
    ba = (r.get("場") or "").strip()
    rno = str(r.get("R") or "").strip()
    if not (d and ba and rno):
        return None
    return table.get(table_key(d, ba, rno))


def split_of(rows: list[dict], table: dict[str, float], as_of,
             base: mk.BaseTimes | None,
             window: int = mk.WINDOW_DAYS,
             recent_runs: int = mk.RECENT_RUNS,
             min_runs: int = mk.MIN_RUNS_FOR_SCORE) -> Split | None:
    """馬別戦績から持ち時計を2成分に分ける。

    **as_of より前・window 日以内**の走りだけを使う（後知恵の排除）。
    指数と水準の両方が取れた走りが min_runs 未満なら None（0で埋めない）。
    """
    from datetime import date as _date, timedelta

    if not rows or base is None or not table:
        return None
    if as_of is None:
        as_of = max((r.get("日付", "") for r in rows), default="") or None
    key = as_of.isoformat() if isinstance(as_of, _date) else (
        str(as_of) if as_of else None)
    if not key:
        return None
    try:
        y, m, d = (int(x) for x in key.split("-")[:3])
        lo = (_date(y, m, d) - timedelta(days=window)).isoformat()
    except (ValueError, TypeError):
        return None

    sel = sorted((r for r in rows if lo <= r.get("日付", "") < key),
                 key=lambda r: r.get("日付", ""), reverse=True)
    pairs: list[tuple[float, float]] = []
    for r in sel:
        v = mk.index_of_record(r, base)
        lv = level_of_record(r, table)
        if v is not None and lv is not None:
            pairs.append((lv, v - lv))
    if len(pairs) < min_runs:
        return None
    w = pairs[:recent_runs]
    return Split(n=len(pairs), level=statistics.fmean(a for a, _ in w),
                 margin=statistics.fmean(b for _, b in w))


def field_splits(records: dict[str, list[dict]] | None, names: list[str],
                 table: dict[str, float], as_of,
                 base: mk.BaseTimes | None, **kw) -> dict[str, Split]:
    if not records or base is None or not table:
        return {}
    out = {}
    for n in names:
        s = split_of(records.get(n, []), table, as_of, base, **kw)
        if s is not None:
            out[n] = s
    return out


# ---------------------------------------------------------------------------
# 表示（第1段階＝表示のみ）
# ---------------------------------------------------------------------------

def race_note(splits: dict[str, Split]) -> str | None:
    """レースの水準を、出走馬が走ってきた水準から読む（発走前に分かる）。

    今走の水準そのものは走らないと分からないので、**出走馬が走ってきた
    水準の中央値**で代える。等級ラベルが1〜4%しか埋まっていない中で、
    レース格のレベルを言える唯一の経路。
    """
    if len(splits) < 4:
        return None
    med = statistics.median(s.level for s in splits.values())
    return (f"出走馬が走ってきた水準の中央値 {med:+.2f}"
            f"（{class_label(med)}相当・{len(splits)}頭から）")


def _tertile_marks(splits: dict[str, Split]) -> dict[str, tuple[bool, bool, bool, bool]]:
    """メンバー内で (水準上位, 水準下位, 相対上位, 相対下位) を返す。

    上位1/3・下位1/3を**ちょうど k 頭**にする。`lv[-1 - k]` と書くと
    6頭のとき上位が3頭になり、1/3ではなく半分になる。
    """
    if len(splits) < 6:
        return {}
    lv = sorted(s.level for s in splits.values())
    mg = sorted(s.margin for s in splits.values())
    k = len(lv) // 3
    lv_lo, lv_hi = lv[k - 1], lv[len(lv) - k]
    mg_lo, mg_hi = mg[k - 1], mg[len(mg) - k]
    return {n: (s.level >= lv_hi, s.level <= lv_lo,
                s.margin >= mg_hi, s.margin <= mg_lo)
            for n, s in splits.items()}


def horse_notes(splits: dict[str, Split],
                ninki: dict[str, int | None]) -> dict[str, str]:
    """交差で 差あり＋期間再現 を通った4つの形だけを一言にする。

    人気帯で言い方が変わるのは、実測がその形でしか再現しなかったため
    （**点数は人気で変えない**。`tests/test_norikae.py` が固定しているのは
    点数の話で、表示は別）。
    """
    marks = _tertile_marks(splits)
    out: dict[str, str] = {}
    for n, (lv_top, lv_bot, mg_top, mg_bot) in marks.items():
        nk = ninki.get(n)
        if nk is None:
            continue
        s = splits[n]
        body = (f"走ってきた水準 {s.level:+.2f}（{s.label()}）"
                f"／相手との差 {s.margin:+.2f}・{s.n}走")
        if nk <= 3 and lv_top and mg_top:
            tail = "水準も着差もメンバー上位（1-3番人気で+14.1p）"
        elif 4 <= nk <= 5 and lv_bot and mg_top:
            tail = "弱い相手を離してきただけ（4-5番人気で−4.6p）"
        elif nk >= 6 and lv_bot and mg_bot:
            tail = "水準も着差もメンバー下位（人気薄で−2.4〜5.4p）"
        else:
            continue
        out[n] = f"{body} → {tail}"
    return out
