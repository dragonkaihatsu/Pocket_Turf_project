"""単勝オッズから馬連・ワイドのオッズを推定する。

合成オッズを設計するには、買う組み合わせすべての事前オッズが要る。しかし
収集できるのは的中した組の確定配当だけなので、単勝オッズから推定する。

方法は Harville モデル:
    * 単勝オッズ → 勝率 p_i（控除率を割り戻して合計1に正規化）
    * 2着以下は「勝った馬を除いた中での勝率」で近似する
      P(i,j の馬連) = p_i·p_j/(1-p_i) + p_j·p_i/(1-p_j)
    * 払戻 = (1 - 控除率) / P × 100円

Harville は人気馬の連対をやや過大に見積もる（強い馬ほど2着になりにくい）
既知の癖があるため、**推定値は必ず実配当と突き合わせて誤差を確認すること**。
scripts/validate_odds.py がその検証を行う。
"""
from __future__ import annotations

from itertools import permutations

# 控除率。地方競馬の標準的な値
TAKEOUT_TANSHO = 0.20
TAKEOUT_UMAREN = 0.25
TAKEOUT_WIDE = 0.25


def win_probabilities(odds: dict[int, float]) -> dict[int, float]:
    """単勝オッズ → 勝率。控除率を割り戻して合計1に正規化する。"""
    raw = {u: 1.0 / o for u, o in odds.items() if o and o > 0}
    total = sum(raw.values())
    if total <= 0:
        return {}
    return {u: v / total for u, v in raw.items()}


def quinella_prob(p: dict[int, float], a: int, b: int) -> float:
    """馬連（順不同で1・2着）の確率。"""
    pa, pb = p.get(a, 0.0), p.get(b, 0.0)
    out = 0.0
    if pa < 1.0:
        out += pa * pb / (1.0 - pa)
    if pb < 1.0:
        out += pb * pa / (1.0 - pb)
    return out


def wide_prob(p: dict[int, float], a: int, b: int) -> float:
    """ワイド（2頭とも3着以内）の確率。

    3着までの並びを全通り数えると重いので、a・b が上位3着に入る
    並び（a,b,x / a,x,b / x,a,b とその入れ替え）を直接足し上げる。
    """
    pa, pb = p.get(a, 0.0), p.get(b, 0.0)
    if pa <= 0 or pb <= 0:
        return 0.0
    others = [(u, q) for u, q in p.items() if u not in (a, b)]
    total = 0.0
    # a と b の順序2通り × 3人目の位置3通り
    for first, second in permutations((a, b)):
        pf, ps = p[first], p[second]
        if pf >= 1.0:
            continue
        # 2頭が1・2着 → 3着は誰でもよい
        r1 = 1.0 - pf
        if r1 <= 0:
            continue
        total += pf * (ps / r1)
        # 2頭が1・3着、間に別の馬
        for u, q in others:
            r2 = r1 - q
            if r2 <= 0:
                continue
            total += pf * (q / r1) * (ps / r2)
        # 2頭が2・3着、先頭に別の馬
        for u, q in others:
            if q >= 1.0:
                continue
            r2 = 1.0 - q
            r3 = r2 - pf
            if r2 <= 0 or r3 <= 0:
                continue
            total += q * (pf / r2) * (ps / r3)
    # first/second の入れ替えで「1・2着」を二重に数えているので補正はしない
    # （permutations が順序付きの並びを列挙しているため重複はない）
    return min(total, 1.0)


def estimate_umaren(odds: dict[int, float], a: int, b: int,
                    takeout: float = TAKEOUT_UMAREN) -> float | None:
    """馬連オッズの推定値（倍）。"""
    p = win_probabilities(odds)
    q = quinella_prob(p, a, b)
    return (1.0 - takeout) / q if q > 0 else None


def estimate_wide(odds: dict[int, float], a: int, b: int,
                  takeout: float = TAKEOUT_WIDE) -> float | None:
    """ワイドオッズの推定値（倍）。"""
    p = win_probabilities(odds)
    q = wide_prob(p, a, b)
    return (1.0 - takeout) / q if q > 0 else None
