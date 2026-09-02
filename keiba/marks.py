"""印（◎○▲△注）の割り振り。

スコア上位から ◎○▲△注 の順に割り振る（CLAUDE.md の目安通り）。
△は複数可、注は「人気を裏切りそうにない程度の注目馬」として数頭まで許容する。

既定は8頭（◎○▲＋△3頭＋注2頭）。波乱型の買い目が「軸2頭×相手6頭＝馬連12点」
を必要とするため、相手を6頭確保できる頭数にしてある。
"""
from __future__ import annotations

from dataclasses import dataclass

from .scoring import HorseScore

MARK_ORDER = ["◎", "○", "▲"]


@dataclass
class MarkedHorse:
    mark: str
    score: HorseScore


def assign_marks(
    scores: list[HorseScore],
    baba: str = "良",
    n_osae: int = 3,      # △ の頭数（△は複数可）
    n_chuui: int = 2,     # 注 の頭数
) -> list[MarkedHorse]:
    """baba: '良' なら良馬場スコア、それ以外（稍重/重/不良）なら重馬場スコアで並べる。"""
    key = (lambda s: s.total_yoi) if baba == "良" else (lambda s: s.total_omoi)
    ranked = sorted(scores, key=key, reverse=True)

    marked: list[MarkedHorse] = []
    for i, s in enumerate(ranked):
        if i < len(MARK_ORDER):
            mark = MARK_ORDER[i]
        elif i < len(MARK_ORDER) + n_osae:
            mark = "△"
        elif i < len(MARK_ORDER) + n_osae + n_chuui:
            mark = "注"
        else:
            break
        marked.append(MarkedHorse(mark=mark, score=s))
    return marked
