"""買い目プラン生成（CLAUDE.md の標準形式）。

標準形式:
    単勝: 推奨2頭（合成3倍前後目安）
    ワイド: 3点（合成5倍前後目安）
    馬連: 10点（合成5〜7倍前後目安）

軸馬（◎の信頼度が特に高い場合、◎と○のスコア差が閾値以上）は
ワイド2点・馬連5〜7点に絞る。
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from .marks import MarkedHorse


@dataclass
class Ticket:
    label: str  # 表示用（例: "1-3"）
    horses: tuple[MarkedHorse, ...]


@dataclass
class BettingPlan:
    is_axis_mode: bool
    tansho: list[MarkedHorse]
    wide: list[Ticket]
    umaren: list[Ticket]
    note: str


def _label(*mhs: MarkedHorse) -> str:
    return "-".join(f"{m.score.horse.umaban}{m.mark}{m.score.horse.name}" for m in mhs)


def make_betting_plan(
    marked: list[MarkedHorse],
    baba: str = "良",
    axis_gap_threshold: float = 8.0,
) -> BettingPlan:
    if len(marked) < 2:
        return BettingPlan(False, marked, [], [], "出走頭数が少なく買い目プランを生成できません")

    key = (lambda m: m.score.total_yoi) if baba == "良" else (lambda m: m.score.total_omoi)
    gap = key(marked[0]) - key(marked[1])
    is_axis = gap >= axis_gap_threshold

    tansho = marked[:2]

    if is_axis:
        wide_pairs = [(marked[0], marked[1]), (marked[0], marked[2])] if len(marked) >= 3 else [(marked[0], marked[1])]
        n_partners = min(7, len(marked) - 1)  # 出走頭数が十分なら5〜7点相当になる
        umaren_pairs = [(marked[0], p) for p in marked[1:1 + n_partners]]
        note = (
            f"◎の信頼度が高いと判定（{key(marked[0]):.1f}点 vs 2位{key(marked[1]):.1f}点、"
            f"差{gap:.1f}点 ≥ 閾値{axis_gap_threshold}点）→ 軸流しに絞った買い目"
        )
    else:
        top5 = marked[:5]
        wide_pairs = list(combinations(top5[:3], 2))  # ◎-○, ◎-▲, ○-▲ の3点
        umaren_pairs = list(combinations(top5, 2))  # 上位5頭ボックス（最大10点）
        note = f"標準形式（◎-2位差{gap:.1f}点 < 閾値{axis_gap_threshold}点のため上位5頭ボックス）"

    wide = [Ticket(_label(a, b), (a, b)) for a, b in wide_pairs]
    umaren = [Ticket(_label(a, b), (a, b)) for a, b in umaren_pairs]

    return BettingPlan(is_axis, tansho, wide, umaren, note)
