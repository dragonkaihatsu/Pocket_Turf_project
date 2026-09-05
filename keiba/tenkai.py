"""馬ごとに「4角で何番手にいそうか」を推定する。

netkeiba の脚質ラベル（逃げ/先行/差し/追込）は事前に分かる唯一の位置情報
だが、実測すると当たりが悪い。中央では「逃げ」の馬が4角1-2番手を取れるのは
41.7%しかなく、複勝率も差し馬とほぼ同じ（21.5%対21.9%）で、ラベルとしての
価値が無い。

そこで**その馬自身が過去に4角で何番手にいたか**を併せて使う。
頭数が違うと同じ「3番手」の意味が変わるため、相対位置
(順位-1)/(頭数-1) で持つ（0=先頭、1=最後方）。

実測（脚質と過去4角の両方がある馬）:

    予測 → 実際の4角相対位置の相関
                        中央      地方
    脚質ラベルのみ       +0.325   +0.415
    過去4角のみ         +0.334   +0.532
    両方の平均          +0.380   +0.530

地方は過去4角だけで足り、中央は混ぜた方が良い。どちらでも混ぜて損は
無いので、**両方あるときは平均を取る**。

複勝率の分離もラベルより素直:

    推定位置          中央 複勝率   地方 複勝率
    最前(0.00-0.15)    30.4%      41.4%
    前(0.15-0.30)      23.6%      30.7%
    中前(0.30-0.50)    19.5%      20.0%
    中後(0.50-0.70)    14.4%      15.2%
    後(0.70-1.00)        —        10.3%

ラベルは中央で「逃げ24.8% < 先行27.4%」と順序が壊れているが、
推定位置は単調に落ちる。順序尺度として使えるのはこちら。
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from . import profile

# 脚質ラベルを相対位置に読み替える事前分布。実測の平均位置に寄せてある
LABEL_PRIOR = {"逃げ": 0.10, "先行": 0.30, "差し": 0.60, "追込": 0.85}

# 推定した相対位置をまとめる区分。境界は実測の複勝率が単調に落ちる位置
BANDS: tuple[tuple[float, float, str], ...] = (
    (0.00, 0.15, "最前"),
    (0.15, 0.30, "前"),
    (0.30, 0.50, "中前"),
    (0.50, 0.70, "中後"),
    (0.70, 1.01, "後"),
)

WINDOW = 5          # 直近何走を見るか
MIN_RUNS = 1        # 過去何走あれば実測を使うか


def band_of(rel: float | None) -> str:
    """相対位置 → 区分名。推定できないときは空文字。"""
    if rel is None:
        return ""
    for lo, hi, name in BANDS:
        if lo <= rel < hi:
            return name
    return BANDS[-1][2]


def load_corner_records(path: str | Path | None = None) -> dict[str, list[dict]]:
    """馬名 → 4角履歴（日付順）。無ければ空。"""
    p = Path(path) if path else profile.active().path("corner_records.csv")
    if not p.exists():
        return {}
    out: dict[str, list[dict]] = {}
    with open(p, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                rel = float(row["相対"])
            except (ValueError, KeyError, TypeError):
                continue
            out.setdefault(row["馬名"], []).append({"日付": row["日付"], "相対": rel})
    for rows in out.values():
        rows.sort(key=lambda r: r["日付"])
    return out


def records_before(rows: list[dict], as_of: date | str | None) -> list[dict]:
    """as_of より前の行だけ返す。後知恵を排除するための関門。"""
    if as_of is None:
        return rows
    key = as_of.isoformat() if isinstance(as_of, date) else str(as_of)
    return [r for r in rows if r["日付"] < key]


def estimate(past: list[dict] | None, kyakushitsu: str = "") -> tuple[float | None, str]:
    """(推定相対位置, 根拠コメント) を返す。推定できなければ (None, 理由)。

    過去の4角位置と脚質ラベルの**両方があれば平均**を取る。片方しか
    無ければそれを使う。どちらも無ければ推定しない（数字を作らない）。
    """
    label = (kyakushitsu or "").strip()
    prior = LABEL_PRIOR.get(label)
    recent = (past or [])[-WINDOW:]

    if len(recent) >= MIN_RUNS:
        measured = sum(r["相対"] for r in recent) / len(recent)
        note = f"過去{len(recent)}走の4角平均{measured:.2f}"
        if prior is None:
            return measured, note
        return (measured + prior) / 2, f"{note}＋脚質「{label}」"
    if prior is not None:
        return prior, f"脚質「{label}」のみ（4角履歴なし）"
    return None, "脚質・4角履歴ともになし"
