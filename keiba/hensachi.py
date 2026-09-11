"""レース内偏差値。絶対点数では「その差が大きいのか小さいのか」が分からない。

CLAUDE.mdの実測では、能力スコアの1位と2位の差は**中央値2.6点**しかない。
同じ2.6点差でも、全馬が数点内に固まったレースなら明確な優位だが、
点差が20点に散らばったレースならほぼ互角である。絶対点数のままでは
この区別がつかない。偏差値にすればメンバー内の位置がそのまま読める。

    偏差値 = 50 + 10 × (スコア - レース平均) / 標準偏差

**これはレース内の相対位置であって、レースをまたいだ絶対的な強さではない。**
どのレースにも偏差値65前後の馬と35前後の馬が出る。横断的な能力値を作って
オッズに無い強さを取り出す試みは2度失敗した（上がり3F偏差値・前走で負けた
相手の質。どちらも新聞に載っている素材なので市場に織り込まれていた。
CLAUDE.md「横断偏差値は市場に勝てなかった」参照）。偏差値化の価値は
**読みやすさ**であって、それ自体が妙味を生むわけではない。
"""
from __future__ import annotations

import statistics

# 1位の偏差値でレースの見え方を言い換える閾値
CLEAR = 65.0      # これ以上なら抜けている
SLIGHT = 57.0     # これ以上ならやや優位


def deviations(values: list[float]) -> list[float]:
    """値の並びを偏差値の並びに変換する。散らばりが無い場合は全員50。"""
    if not values:
        return []
    if len(values) == 1:
        return [50.0]
    mu = statistics.mean(values)
    sd = statistics.pstdev(values)
    if sd == 0:
        return [50.0] * len(values)
    return [50.0 + 10.0 * (v - mu) / sd for v in values]


def by_umaban(scores, baba: str = "良") -> dict[int, float]:
    """馬番 → 偏差値。baba が良以外なら重馬場スコアを基準にする。

    scores は HorseScore の並び（印が付かなかった馬も含めた全頭を渡すこと。
    一部だけで計算すると母集団が変わって偏差値の意味が壊れる）。
    """
    key = (lambda s: s.total_yoi) if baba == "良" else (lambda s: s.total_omoi)
    vals = [key(s) for s in scores]
    devs = deviations(vals)
    return {s.horse.umaban: d for s, d in zip(scores, devs)}


def spread_note(devs: dict[int, float]) -> str:
    """1位の偏差値から、そのレースが抜けているか混戦かを一言で言う。"""
    if not devs:
        return "偏差値: 算出不能"
    top = max(devs.values())
    if top >= CLEAR:
        label = "抜けている"
    elif top >= SLIGHT:
        label = "やや優位"
    else:
        label = "混戦（点差が団子）"
    return f"1位の偏差値{top:.1f} → {label}"
