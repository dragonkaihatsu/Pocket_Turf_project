"""1着期待度・着内期待度（CLAUDE.md「2026年8月以降」の要求項目）。

スコアから確率を直接計算することはできない。ここでは
「スコア順位が何位だった馬が、実際に何%勝ったか」を収集済みレースから
実測し、その対応表（data/calibration.json）を引いてパーセントを出す。

対応表が無い場合は数字を出さない（None を返す）。推定値を捏造しないため。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

CALIBRATION_PATH = Path(__file__).resolve().parent.parent / "data" / "calibration.json"

# この母数を下回る区分は数字を出さない（率が偶然に振られるため）
MIN_SAMPLE = 30

# 順位別テーブルはここまでを個別に持ち、それ以降はまとめて扱う
MAX_RANK = 8


def wilson(k: int, n: int) -> tuple[float, float]:
    """二項比率の95%信頼区間（Wilson score interval）。母数の少なさを可視化する。"""
    if n == 0:
        return (0.0, 0.0)
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def rank_key(rank: int) -> str:
    """スコア順位を対応表のキーに変換する。"""
    return str(rank) if rank <= MAX_RANK else f"{MAX_RANK + 1}位以下"


def load_calibration(path: Path | str | None = None) -> dict:
    p = Path(path) if path else CALIBRATION_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


class Expectation:
    """スコア順位 → (1着期待度, 着内期待度) の変換器。

    対応表が無い・母数が足りない場合は None を返し、呼び出し側が
    「データ不足」と表示できるようにする。
    """

    def __init__(self, calibration: dict | None = None):
        self.cal = calibration if calibration is not None else load_calibration()
        self.table: dict = self.cal.get("順位別", {})

    @property
    def available(self) -> bool:
        return bool(self.table)

    @property
    def source_note(self) -> str:
        if not self.available:
            return ("期待度: 対応表(data/calibration.json)が無いため未算出。"
                    "scripts/calibrate.py を実行すると出力される")
        return (f"期待度: {self.cal.get('対象', '収集済みレース')} "
                f"{self.cal.get('レース数', 0)}レースの実測値。"
                f"{self.cal.get('注意', '')}")

    def lookup(self, rank: int) -> tuple[float, float] | None:
        """スコア順位から (1着期待度, 着内期待度) を返す。0.0-1.0。"""
        rec = self.table.get(rank_key(rank))
        if not rec or rec.get("n", 0) < MIN_SAMPLE:
            return None
        return (rec["勝率"], rec["複勝率"])

    def interval(self, rank: int) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """(1着期待度の95%CI, 着内期待度の95%CI) を返す。"""
        rec = self.table.get(rank_key(rank))
        if not rec or rec.get("n", 0) < MIN_SAMPLE:
            return None
        return (tuple(rec["勝率CI"]), tuple(rec["複勝率CI"]))

    def sample_size(self, rank: int) -> int:
        rec = self.table.get(rank_key(rank))
        return rec.get("n", 0) if rec else 0

    def format(self, rank: int) -> tuple[str, str]:
        """表示用の文字列。データ不足なら「—」。"""
        v = self.lookup(rank)
        if v is None:
            return ("—", "—")
        return (f"{v[0]:.0%}", f"{v[1]:.0%}")
