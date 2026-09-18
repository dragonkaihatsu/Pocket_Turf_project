"""「荒れそう／堅そう」をレースごとに一言で言う（本人の指示・2026-09-15）。

「見送り判定ではなく、総合的判断で荒れそう・堅そう判定を出すこと」。

## 2軸だけで作る（残ったものしか使わない）
`scripts/arare.py` で、発走前に分かる7つの特徴を**1番人気オッズ帯で統制して**
測った。統制しないと、オッズを言い換えただけの指標が効いたように見える。

帯の中でも両期間で残ったのは **上位3人気の支持集中度** だけだった:

    支持集中度 = Σ(1/単勝オッズ)   1〜3番人気の3頭ぶん

頭数・先行勢の比率・スコア1位2位の差・◎と1番人気の一致は、いずれも
帯の中では判定不能だった（頭数は4頭BOXの的中に対してのみ2倍台で効くが、
支持集中度と重なるので軸には足さない）。

## 実測（中央9-12R 1,979レース）
| 帯 | 集中度 | 1番人気が着外 | 上位4頭BOX的中 |
|---|---|---|---|
| 1倍台 | 高い | 12.1% | **44.8%** |
| 1倍台 | ふつう | 14.7% | 37.1% |
| 1倍台 | 低い | 21.6% | 24.1% |
| 2倍台 | 高い | 26.1% | 41.2% |
| 2倍台 | ふつう | 36.4% | 26.5% |
| 2倍台 | 低い | 40.1% | 22.1% |
| 3倍以上 | 高い | 45.8% | 22.9% |
| 3倍以上 | ふつう | 51.8% | 19.5% |
| 3倍以上 | 低い | 59.6% | **14.7%** |

**どちらの軸でも単調**で、9区分の端から端で的中率が3倍違う。

## 表示は一言だけ
CLAUDE.md「説明しすぎない」に従い、**率は出さない**。率は順位や区分に付いた
in-sample の一般値で、「今日のこのレースの確率」ではないため（一覧の最下段から
実測を外したのと同じ理由）。

**これは見送り判定ではない。** 買うかどうかは買う人が決める。
"""
from __future__ import annotations

import json
from pathlib import Path

from .profile import active, for_venue

# 上位4頭BOXの実測的中率で言い換える。境目は9区分の並びから取った
# （35%以上と22%未満のあいだに、はっきりした切れ目がある）
CLEAR = 0.35      # これ以上なら堅そう
ROUGH = 0.22      # これ未満なら荒れそう
LABELS = ("堅そう", "標準", "荒れそう")
FILENAME = "arare.json"


def share3(horses) -> float | None:
    """上位3人気の支持集中度 Σ(1/単勝オッズ)。3頭そろわなければ None。"""
    ranked = sorted((h for h in horses if h.ninki and h.tansho_odds),
                    key=lambda h: h.ninki)[:3]
    if len(ranked) < 3 or any(h.tansho_odds <= 0 for h in ranked):
        return None
    return sum(1 / h.tansho_odds for h in ranked)


def odds_band(o: float | None) -> str | None:
    if o is None or o <= 0:
        return None
    return "1倍台" if o < 2.0 else "2倍台" if o < 3.0 else "3倍以上"


def load_table(path: str | Path | None = None,
               venue: str | None = None) -> dict:
    """判定表を読む。**競馬場から引く**（既定プロファイル任せにしない）。

    CLAUDE.mdが繰り返し記録している事故（中央のレースに地方の実測表を
    当てる）は、どれも「今のプロファイル」に頼ったことで起きている。
    ここでは venue が分かればそこから決め、分からなければ既定に落ちる。
    """
    if path:
        p = Path(path)
    else:
        prof = for_venue(venue) if venue else active()
        p = prof.path(FILENAME)
    if not Path(p).exists():
        return {}
    with open(p, encoding="utf-8-sig") as f:
        return json.load(f).get("表", {})


def judge(fav_odds: float | None, horses, table: dict | None = None,
          venue: str | None = None) -> str | None:
    """「堅そう／標準／荒れそう」。判定できなければ None（作らない）。"""
    band = odds_band(fav_odds)
    if band is None:
        return None
    table = load_table(venue=venue) if table is None else table
    cell = table.get(band)
    if not cell:
        return None
    s = share3(horses)
    if s is None:
        return None
    name = ("低い" if s <= cell["下限"]
            else "高い" if s >= cell["上限"] else "ふつう")
    got = cell.get("区分", {}).get(name)
    if not got:
        return None
    hit = got["4頭BOX的中"]
    return LABELS[0] if hit >= CLEAR else LABELS[2] if hit < ROUGH else LABELS[1]
