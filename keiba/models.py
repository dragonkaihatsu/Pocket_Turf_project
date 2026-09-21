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


# 上がり3F（ラスト600m）として成立する範囲。外れた値は**欠損として扱う**。
#
# ## なぜ要るのか（2026-09-19・本人の指摘で判明）
#
# **障害レースの馬柱・結果ページは、この列に3Fではない値を入れる**
# （12.8〜15.2秒。障害は上がり3Fを計測しないので、おそらく最後の平地部分）。
# 3F＝600mなので、その区間を13秒で走ることは物理的にあり得ない。
#
# 実害は該当馬1頭では止まらない。基礎能力は**レース内で最小〜最大に正規化**
# するので、13.4秒が1頭混ざるとそれが「最速」の基準になり、
# **同じレースで上がり3Fに落ちている他の馬が不当に低く評価される**。
# 収集済みデータでは 5,490レースのうち **316レース（5.8%）** がこの状態だった。
#
#   出走馬CSV  30秒未満 1,941件（前走が障害 1,335 ＋ 前走名が空 606）／0.0 が 402件
#   結果CSV    30秒未満 2,272件
#
# ## 閾値の根拠
#
# 観測値は **15.2秒と30.0秒のあいだが完全に空**（74,148件で25〜30秒が0件）。
# 障害由来の塊と平地の塊がはっきり分かれているので、下限30.0は安全に切れる。
# 上限は48.0（45〜48秒が162件で不良馬場の長距離としてあり得る一方、
# 48秒超の55件は94.3秒・75.7秒など明らかなゴミ）。
#
# **0.0 は「前走が無い」の意味**（新馬・転入初戦）で、速さゼロではない。
# 下限で自動的に弾かれる。
AGARI_3F_MIN = 30.0
AGARI_3F_MAX = 48.0


def parse_agari_3f(value: str | float | None) -> float | None:
    """上がり3Fを読む。成立しない値は None（欠損）にする。

    **数値として読めることと、上がり3Fであることは別**である。
    CSVを直接読む集計スクリプトも `float()` ではなくこれを通すこと
    （障害の13秒台は「上がり3F上位3位」に必ず入ってしまう）。
    """
    x = value if isinstance(value, (int, float)) else _to_float(value)
    if x is None:
        return None
    return float(x) if AGARI_3F_MIN <= x <= AGARI_3F_MAX else None


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
    # 休養日数（長期休養明け判定用）。**収集CSVの列名は `前走間隔日数`**で、
    # `休養日数` という列は存在しない。`休養日数` だけを読んでいたため
    # `correction_hatsu_course` の −3点が延べ2,736頭で0%発火だった
    # （2026-09-21に発見。枠順補正が0%発火だったのと同型の列名取り違え）
    kyusoku_days: int | None = None
    zenso_handicap: bool = False  # 前走がハンデ戦の好走だったか
    kyakushitsu: str = ""  # 脚質（逃げ/先行/差し/追込）
    michiwaru_koumono: bool = False  # 道悪巧者（Y/N）
    kiso_nouryoku_override: float | None = None  # 基礎能力の手動評価（0-25点）
    tansho_odds: float | None = None  # 単勝オッズ（買い目戦略の判定に使う）
    ninki: int | None = None  # 単勝人気順
    # netkeibaの馬柱が持つ間隔ラベル（「連闘」「中1週」…）。日数で切ると
    # 順延・変則開催がずれるので、開催の数え方に忠実なこちらを使う
    kankaku: str = ""

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
            agari_3f=parse_agari_3f(g("上がり3F", "上がり3f")),
            chokyo_hyoka=g("調教評価"),
            ketto_chichi=g("血統父", "父"),
            ketto_hahachichi=g("血統母父", "母父"),
            kishu_norikae=_to_bool(g("乗り替わり")),
            zenso_furi=_to_bool(g("前走不利")),
            kyusoku_days=_to_int(g("休養日数", "前走間隔日数")),
            zenso_handicap=_to_bool(g("前走ハンデ戦")),
            kyakushitsu=g("脚質"),
            michiwaru_koumono=_to_bool(g("道悪巧者")),
            kiso_nouryoku_override=_to_float(g("基礎能力評価")),
            tansho_odds=_to_float(g("単勝オッズ")),
            ninki=_to_int(g("人気")),
            kankaku=g("間隔表記"),
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
            agari_3f=parse_agari_3f(g("上がり3F", "上がり3f")),
        )


def load_horses(path: str | Path) -> list[Horse]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [Horse.from_row(row) for row in csv.DictReader(f)]


def load_history(path: str | Path) -> list[HistoryRecord]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [HistoryRecord.from_row(row) for row in csv.DictReader(f)]
