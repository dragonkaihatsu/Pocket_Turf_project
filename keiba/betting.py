"""買い目プラン生成。

「点数が多いほど損をする」という前提のもと、レースの荒れやすさに応じて
3つの型を使い分ける。荒れやすさは **1番人気の単勝オッズ** で判定する。

判定基準は大井83レース（2026年8月〜9月）の実測に基づく:

    1番人気オッズ   1人気勝率  1人気複勝率  馬連中央値
    1倍台            62.9%      94.3%       720円   → 鉄板
    2倍台            36.7%      76.7%     1,210円   → 標準
    3倍台以上        31.2%      50.0%     2,790円   → 波乱

1倍台なら1番人気はほぼ確実に馬券圏内に来るが配当は安い。よって点数を絞って
的中率を取りにいく。3倍台になると1番人気は半分飛び、配当は約4倍に跳ねる。
よって1番人気を軸から外し、2・3番人気を軸にした馬連フォーメーションで臨む。

なお同じ集計で頭数はほとんど効かなかった（15頭以上でも1番人気の勝率60%）ため、
頭数は荒れやすさの判定に使わない。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from . import profile
from .marks import MarkedHorse

# 荒れやすさの境界（1番人気の単勝オッズ）
# 買い目の型を切り替える1番人気オッズの閾値。既定は地方（大井）の実測値だが、
# 中央は1番人気の複勝率が一段低い（1倍台86%/2倍台68%/3倍台52%）ため、
# プロファイルの thresholds.json で上書きできるようにしてある
TEPPAN_MAX_ODDS = 2.0   # これ未満なら鉄板
HARAN_MIN_ODDS = 3.0    # これ以上なら波乱


def _thresholds() -> tuple[float, float]:
    t = profile.active().thresholds
    return (float(t.get("鉄板_上限オッズ", TEPPAN_MAX_ODDS)),
            float(t.get("波乱_下限オッズ", HARAN_MIN_ODDS)))

TEPPAN = "鉄板"
HYOJUN = "標準"
HARAN = "波乱"

MAX_POINTS = {TEPPAN: 3, HYOJUN: 10, HARAN: 6}


@dataclass
class Ticket:
    label: str
    horses: tuple[MarkedHorse, ...]


@dataclass
class BettingPlan:
    strategy: str = HYOJUN
    tansho: list[MarkedHorse] = field(default_factory=list)
    wide: list[Ticket] = field(default_factory=list)
    umaren: list[Ticket] = field(default_factory=list)
    note: str = ""
    favorite_odds: float | None = None

    @property
    def total_points(self) -> int:
        return len(self.tansho) + len(self.wide) + len(self.umaren)

    # 旧APIとの互換（軸流し型かどうか）
    @property
    def is_axis_mode(self) -> bool:
        return self.strategy in (HYOJUN, HARAN)


def _label(*mhs: MarkedHorse) -> str:
    return "-".join(str(m.score.horse.umaban) for m in mhs)


def _ticket(a: MarkedHorse, b: MarkedHorse) -> Ticket:
    return Ticket(_label(a, b), (a, b))


def favorite_odds_of(marked: list[MarkedHorse]) -> float | None:
    """1番人気の単勝オッズを取り出す。人気列が無ければ最小オッズで代用する。"""
    for m in marked:
        if m.score.horse.ninki == 1:
            return m.score.horse.tansho_odds
    odds = [m.score.horse.tansho_odds for m in marked if m.score.horse.tansho_odds]
    return min(odds) if odds else None


def select_strategy(favorite_odds: float | None) -> str:
    """1番人気の単勝オッズから買い目の型を選ぶ。オッズ不明なら標準。"""
    if favorite_odds is None:
        return HYOJUN
    teppan_max, haran_min = _thresholds()
    if favorite_odds < teppan_max:
        return TEPPAN
    if favorite_odds >= haran_min:
        return HARAN
    return HYOJUN


def _by_ninki(marked: list[MarkedHorse], wanted: tuple[int, ...]) -> list[MarkedHorse]:
    """指定した人気順の馬を返す。人気データが無ければ空リスト。"""
    found = [m for w in wanted for m in marked if m.score.horse.ninki == w]
    return found


def make_betting_plan(
    marked: list[MarkedHorse],
    baba: str = "良",
    favorite_odds: float | None = None,
    strategy: str | None = None,
    n_partners: int = 6,
) -> BettingPlan:
    """印の並び（スコア順）と1番人気のオッズから買い目を組む。

    strategy を明示すればオッズ判定を上書きできる。
    """
    if len(marked) < 2:
        return BettingPlan(note="出走頭数が少なく買い目プランを生成できません")

    if favorite_odds is None:
        favorite_odds = favorite_odds_of(marked)
    strategy = strategy or select_strategy(favorite_odds)

    odds_text = f"1番人気 {favorite_odds:.1f}倍" if favorite_odds else "1番人気オッズ不明"

    if strategy == TEPPAN:
        # 固いレース。点数を絞り、ワイドで確実に取りにいく
        top3 = marked[:3]
        wide = [_ticket(a, b) for a, b in combinations(top3, 2)]
        note = (
            f"{odds_text} → 鉄板型。1倍台の1番人気は実測で複勝率94%（35レース）。"
            f"配当は安いので点数を絞って的中率を取る（ワイド{len(wide)}点）"
        )
        return BettingPlan(TEPPAN, [], wide, [], note, favorite_odds)

    if strategy == HARAN:
        # 荒れる帯こそ、軸を決め打たずスコア上位4頭を総当たりにする。
        # 大井9-12R 43レースの実測（ブートストラップ1万回）:
        #   馬連 上位4頭BOX(6点) 回収率300% / 90%区間 66-671% / 100%超84% / 最大DD -4,690円
        #   旧・波乱型(12点)     回収率 60% / 90%区間 36- 86% / 100%超 1% / 最大DD -22,200円
        # 旧型は軸を2・3番人気に固定するため、1番人気と4番人気で決まると買えない。
        # 高配当は外れ値ではなく荒れる帯の本体なので、除かずに評価してこの結論。
        box = marked[:4]
        umaren = [_ticket(a, b) for a, b in combinations(box, 2)]
        note = (
            f"{odds_text} → 波乱型。3倍台以上の1番人気は実測で複勝率50%まで落ちるが、"
            f"軸を決め打つと取り逃す。スコア上位4頭のBOXで受ける"
            f"（馬連{len(umaren)}点・実測回収率300%／90%区間66-671%／43レース）"
        )
        return BettingPlan(HARAN, [], [], umaren, note, favorite_odds)

    # 標準: 1番人気を軸として使えるが、盤石ではない。◎軸で最大10点
    axis = marked[0]
    partners = marked[1 : 1 + min(n_partners, MAX_POINTS[HYOJUN])]
    umaren = [_ticket(axis, p) for p in partners]
    note = (
        f"{odds_text} → 標準型。2倍台の1番人気は実測で複勝率77%（30レース）。"
        f"◎{axis.score.horse.umaban}{axis.score.horse.name}を軸に"
        f"相手{len(partners)}頭へ流す（馬連{len(umaren)}点）"
    )
    return BettingPlan(HYOJUN, [], [], umaren, note, favorite_odds)
