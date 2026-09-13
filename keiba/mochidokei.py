"""持ち時計指数。走破タイムを「競馬場×芝ダ×距離」の基準と比べて、
レースをまたいで比較できる速さの尺度にする。

現行スコアの基礎能力25点は**前走の上がり3Fだけ**で作られており、動いている
45点はすべて前走1走に由来する（前走着順20点＋前走の上がり3F25点）。
上がり3Fは終いの脚しか測らないので、前半が緩いレースを走った馬が高く出る。

時計は距離と馬場で正規化しないと比べられないが、**正規化すれば全走が使える**。
場や距離の一致を要求しないので、コース適性15点が死んだ原因（場一致27.8%と
いう母数不足）が原理的に起きない。実測でも2026年9-12Rの出走のうち
直近365日にタイムのある過去走が1走以上ある割合は98.6%、中央値6走ある。

    指数 = (基準タイム − 自分のタイム) / 基準のばらつき        （速いほど大）
    馬場補正 = 同じ(場×芝ダ×馬場)における指数の平均を引く

## 読むときの留保（3つとも外せない）

1. **外部の市販スピード指数とは別物**。基準は手元のコーパスから作る
2. **時計は馬柱に載っている**。CLAUDE.mdの設計原則では「載っているものは
   織り込み済み」の側なので、妙味の発見は期待できない。入れる根拠は
   「能力評価が前走1走しか見ていない穴を埋める」ことである
3. **距離だけで正規化するので、指数はクラスを部分的に含む**（未勝利の勝ち馬は
   同じコースのOP馬より時計が遅い）。クラスは市場が織り込んでいるため、
   この指数の優位は同一人気帯内で測らないと確認できない
"""
from __future__ import annotations

import json
import math
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

SEP = "|"

# 基準を作るのに要求する最低行数（延べ出走）。下回る区分は「基準なし」にして
# 推定値を作らない（CLAUDE.md「数字を作らない」）
MIN_CELL_ROWS = 100
# 馬場補正を効かせる最低行数
MIN_BABA_ROWS = 100

_TIME_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}(?:\.\d+)?)$")

# netkeiba は馬場を「稍」「不」と略す。**表のキーは予想時に引く側（設定JSONの
# 稍重/不良）に合わせる**。略記のまま保存すると、発走前の馬場が「稍重」で
# 渡ってきたときに静かに引けず、馬場補正だけ落ちる（CLAUDE.mdが繰り返し
# 記録している「エラーは出ないが値が違う」型の事故）
BABA_CANON = {"稍": "稍重", "不": "不良", "稍重": "稍重", "不良": "不良",
              "良": "良", "重": "重"}
BABA_ORDER = ["良", "稍重", "重", "不良"]


def canon_baba(s: str | None) -> str | None:
    """馬場の表記を 良/稍重/重/不良 に揃える。知らない表記は None。"""
    if not s:
        return None
    return BABA_CANON.get(s.strip())


def parse_time(s: str | None) -> float | None:
    """「2:14.6」「59.9」を秒に直す。読めなければ None。"""
    if not s:
        return None
    m = _TIME_RE.match(s.strip())
    if not m:
        return None
    mins = int(m.group(1)) if m.group(1) else 0
    return mins * 60 + float(m.group(2))


def cell_key(ba: str, shubetsu: str, kyori: int | str) -> str:
    return SEP.join((ba, shubetsu, str(kyori)))


def baba_key(ba: str, shubetsu: str, baba: str) -> str:
    return SEP.join((ba, shubetsu, canon_baba(baba) or baba))


@dataclass
class BaseTimes:
    """基準タイム表。距離区分ごとの平均・ばらつきと、馬場ごとのずれ。"""

    cells: dict[str, dict] = field(default_factory=dict)
    baba: dict[str, dict] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    # -- 作る ---------------------------------------------------------------
    @classmethod
    def build(cls, rows: list[dict], min_rows: int = MIN_CELL_ROWS,
              min_baba_rows: int = MIN_BABA_ROWS) -> "BaseTimes":
        """rows は {場, 馬場種別, 距離, 馬場, 秒} の並び。

        2段階で作る。まず距離区分の平均・ばらつき、次にその指数を馬場ごとに
        平均して馬場のずれを出す。**馬場を距離に掛けない**のは、掛けると
        n>=20 の区分が全レースの96%→77%に落ちて母数を割るため。
        """
        by_cell: dict[str, list[float]] = {}
        for r in rows:
            by_cell.setdefault(cell_key(r["場"], r["馬場種別"], r["距離"]), []).append(r["秒"])

        cells = {}
        for k, vals in by_cell.items():
            if len(vals) < min_rows:
                continue
            sd = statistics.pstdev(vals)
            if sd <= 0:
                continue
            cells[k] = {"n": len(vals), "mean": statistics.fmean(vals), "sd": sd}

        self = cls(cells=cells)

        by_baba: dict[str, list[float]] = {}
        for r in rows:
            idx = self._raw_index(r["秒"], r["場"], r["馬場種別"], r["距離"])
            if idx is not None:
                by_baba.setdefault(baba_key(r["場"], r["馬場種別"], r["馬場"]), []).append(idx)

        self.baba = {k: {"n": len(v), "delta": statistics.fmean(v)}
                     for k, v in by_baba.items() if len(v) >= min_baba_rows}
        self.meta = {"行数": len(rows), "距離区分": len(cells), "馬場区分": len(self.baba),
                     "min_cell_rows": min_rows, "min_baba_rows": min_baba_rows}
        return self

    # -- 使う ---------------------------------------------------------------
    def _raw_index(self, sec: float, ba: str, shubetsu: str, kyori) -> float | None:
        c = self.cells.get(cell_key(ba, shubetsu, kyori))
        if not c:
            return None
        return (c["mean"] - sec) / c["sd"]

    def index(self, sec: float | None, ba: str, shubetsu: str, kyori,
              baba: str | None = None) -> float | None:
        """指数を返す。基準が無い区分・タイム不明は None（0 にしない）。"""
        if sec is None or not math.isfinite(sec):
            return None
        raw = self._raw_index(sec, ba, shubetsu, kyori)
        if raw is None:
            return None
        if baba:
            b = self.baba.get(baba_key(ba, shubetsu, baba))
            if b:
                raw -= b["delta"]
        return raw

    # -- 保存 ---------------------------------------------------------------
    def save(self, path: Path | str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(
            {"距離基準": self.cells, "馬場補正": self.baba, "メタ": self.meta},
            ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str) -> "BaseTimes":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(cells=d.get("距離基準", {}), baba=d.get("馬場補正", {}),
                   meta=d.get("メタ", {}))


# ---------------------------------------------------------------------------
# 馬ごとの持ち時計（直近365日）
# ---------------------------------------------------------------------------

WINDOW_DAYS = 365
# 「近走」として平均する本数
RECENT_RUNS = 3


@dataclass
class Mochidokei:
    """1頭の持ち時計。母数（何走から作ったか）を必ず持ち歩く。"""

    n: int
    best: float
    recent: float

    def as_dict(self) -> dict:
        return {"n": self.n, "最高": round(self.best, 3), "近走": round(self.recent, 3)}


def summarize(indices: list[float], recent_runs: int = RECENT_RUNS) -> Mochidokei | None:
    """新しい順に並べた指数の列から、最高値と近走平均を出す。

    表の #6「近3走の最高時計指数」と #1/#2「近走時計指数」に対応する。
    空なら None を返す（0 を返すと「遅い馬」と区別できなくなる）。
    """
    if not indices:
        return None
    return Mochidokei(n=len(indices), best=max(indices),
                      recent=statistics.fmean(indices[:recent_runs]))


def member_deltas(values: dict[int, float]) -> dict[int, tuple[float, float]]:
    """馬番→指数 を、馬番→(メンバートップとの差, メンバー平均との差) にする。

    重要度上位2つ（トップとの差20.74%・平均との差14.53%）がこの形。
    絶対値ではなくメンバー内の相対差にするのは、レース内偏差値と同じ理由
    （その差が大きいのか小さいのかは、メンバーを見ないと決まらない）。
    """
    if not values:
        return {}
    top = max(values.values())
    avg = statistics.fmean(values.values())
    return {u: (v - top, v - avg) for u, v in values.items()}


# ---------------------------------------------------------------------------
# 馬別戦績から持ち時計を作る（予想時・バックテスト共通の入口）
# ---------------------------------------------------------------------------

# 採点に使うのに要求する窓内の走り。実測はこの本数以上で測ったので、
# 下回る馬に指数を与えると測っていない条件に点を付けることになる
MIN_RUNS_FOR_SCORE = 3


def from_records(rows: list[dict], as_of, base: BaseTimes,
                 window: int = WINDOW_DAYS,
                 recent_runs: int = RECENT_RUNS,
                 min_runs: int = MIN_RUNS_FOR_SCORE) -> Mochidokei | None:
    """馬別戦績の行（horse_records.csv の形）から持ち時計を作る。

    **as_of より前・window 日以内の走りだけ**を使う（後知恵の排除）。
    as_of が None なら当日の予想なので全行の末尾から窓を取る。
    走りが min_runs 未満なら None を返す。0 で埋めない。
    """
    from datetime import date as _date, timedelta

    if as_of is None:
        latest = max((r.get("日付", "") for r in rows), default="")
        as_of = latest or None
    key = as_of.isoformat() if isinstance(as_of, _date) else (str(as_of) if as_of else None)
    if not key:
        return None
    try:
        y, m, d = (int(x) for x in key.split("-")[:3])
        lo = (_date(y, m, d) - timedelta(days=window)).isoformat()
    except (ValueError, TypeError):
        return None

    sel = [r for r in rows if lo <= r.get("日付", "") < key]
    sel.sort(key=lambda r: r.get("日付", ""), reverse=True)   # 新しい順

    idxs = []
    for r in sel:
        v = index_of_record(r, base)
        if v is not None:
            idxs.append(v)
    if len(idxs) < min_runs:
        return None
    return summarize(idxs, recent_runs)


def index_of_record(r: dict, base: BaseTimes) -> float | None:
    """戦績1行を指数にする。障害は対象外（芝ダと時計の性質が違う）。"""
    shubetsu = (r.get("馬場種別") or "").strip()
    if shubetsu not in ("芝", "ダ"):
        return None
    return base.index(parse_time(r.get("タイム")), (r.get("場") or "").strip(),
                      shubetsu, (r.get("距離") or "").strip(),
                      canon_baba(r.get("馬場")))


def field_indices(records: dict[str, list[dict]] | None,
                  names: list[str], as_of, base: BaseTimes | None,
                  **kw) -> dict[str, float]:
    """出走馬名 → 持ち時計（近走平均）。作れない馬は入れない。

    **メンバー内の相対位置で読む**のが実測で再現した形なので、
    採点側はこの辞書を出走馬全体で最小〜最大に正規化して使う
    （絶対値のまま帯に切ると期間再現しなかった。1-3番人気の複勝リフトが
    2025年 −0.5p → 2026年 +3.4p と符号ごと変わる）。
    """
    if not records or base is None:
        return {}
    out = {}
    for n in names:
        m = from_records(records.get(n, []), as_of, base, **kw)
        if m is not None:
            out[n] = m.recent
    return out
