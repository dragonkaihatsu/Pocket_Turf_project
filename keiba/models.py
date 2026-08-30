"""データモデルとCSV読み込み。

CLAUDE.md が定義する出走馬CSVの想定カラムに加え、補正項目の計算に必要な
任意の拡張カラムを扱う。拡張カラムは存在しなくても動作し、その場合は
中立値（補正なし）にフォールバックする。README.md の「入力CSV仕様」を参照。
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    f = _to_float(value)
    return int(f) if f is not None else None


def _to_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip() in {"Y", "y", "1", "TRUE", "true", "はい", "○", "済"}


AGE_RE = re.compile(r"(\d+)")


@dataclass
class Horse:
    """出走馬1頭分のデータ（出走馬CSVの1行）。"""

    umaban: int  # 馬番
    wakuban: int  # 枠番
    name: str  # 馬名
    sex_age: str  # 性齢（例: 牡5）
    kinryo: float  # 斤量
    jockey: str  # 騎手
    zenso_chakujun: int | None  # 前走着順
    zenso_race: str  # 前走レース名
    agari_3f: float | None  # 上がり3F
    chokyo_hyoka: str  # 調教評価
    ketto_chichi: str = ""  # 血統・父
    ketto_hahachichi: str = ""  # 血統・母父

    # --- 拡張カラム（任意。無ければ中立値/Falseにフォールバック） ---
    kishu_norikae: bool = False  # 乗り替わり（Y/N）
    zenso_furi: bool = False  # 前走不利（展開・コース適性等の外的要因）
    kyusoku_days: int | None = None  # 休養日数（長期休養明け判定用）
    zenso_handicap: bool = False  # 前走がハンデ戦の好走だったか
    kyakushitsu: str = ""  # 脚質（逃げ/先行/差し/追込）
    michiwaru_koumono: bool = False  # 道悪巧者（Y/N）
    kiso_nouryoku_override: float | None = None  # 基礎能力の手動評価（0-25点）

    @property
    def age(self) -> int | None:
        m = AGE_RE.search(self.sex_age)
        return int(m.group(1)) if m else None

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "Horse":
        def g(*keys: str, default: str = "") -> str:
            for k in keys:
                if k in row and row[k] is not None and row[k].strip() != "":
                    return row[k].strip()
            return default

        return cls(
            umaban=_to_int(g("馬番")) or 0,
            wakuban=_to_int(g("枠番")) or 0,
            name=g("馬名"),
            sex_age=g("性齢"),
            kinryo=_to_float(g("斤量")) or 0.0,
            jockey=g("騎手"),
            zenso_chakujun=_to_int(g("前走着順")),
            zenso_race=g("前走レース名"),
            agari_3f=_to_float(g("上がり3F", "上がり3f")),
            chokyo_hyoka=g("調教評価"),
            ketto_chichi=g("血統父", "父"),
            ketto_hahachichi=g("血統母父", "母父"),
            kishu_norikae=_to_bool(g("乗り替わり")),
            zenso_furi=_to_bool(g("前走不利")),
            kyusoku_days=_to_int(g("休養日数")),
            zenso_handicap=_to_bool(g("前走ハンデ戦")),
            kyakushitsu=g("脚質"),
            michiwaru_koumono=_to_bool(g("道悪巧者")),
            kiso_nouryoku_override=_to_float(g("基礎能力評価")),
        )


@dataclass
class HistoryRecord:
    """過去10年データCSVの1行（同一レースの過去実施分）。"""

    year: str
    race_name: str
    umaban: int | None
    wakuban: int | None
    name: str
    chakujun: int | None
    kyori: int | None  # 距離(m)
    baba: str  # 馬場状態（良/稍重/重/不良）
    agari_3f: float | None = None

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "HistoryRecord":
        def g(*keys: str, default: str = "") -> str:
            for k in keys:
                if k in row and row[k] is not None and row[k].strip() != "":
                    return row[k].strip()
            return default

        return cls(
            year=g("年"),
            race_name=g("レース名"),
            umaban=_to_int(g("馬番")),
            wakuban=_to_int(g("枠番")),
            name=g("馬名"),
            chakujun=_to_int(g("着順")),
            kyori=_to_int(g("距離")),
            baba=g("馬場状態"),
            agari_3f=_to_float(g("上がり3F", "上がり3f")),
        )


def load_horses(path: str | Path) -> list[Horse]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [Horse.from_row(row) for row in csv.DictReader(f)]


def load_history(path: str | Path) -> list[HistoryRecord]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [HistoryRecord.from_row(row) for row in csv.DictReader(f)]
