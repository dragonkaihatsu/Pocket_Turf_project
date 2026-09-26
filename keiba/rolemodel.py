"""1日1万円のロールモデル（馬連 上位4頭BOX・人気の組に厚く）。

    python3 scripts/role_model.py --config config/2026-09-27_中央.json \
        --published data/2026-09-27_中央_公表印.json

2026-09-26 に本人が実際にやった買い方を、毎回同じ形で出せるようにしたもの:

- 対象は **10-12R**（2場なら6レース）。9Rは見送り
- 各レース **スコア上位4頭の馬連BOX（6点）**
- 1レース **1,600円** を、推定オッズの短い組から
  **500 / 300 / 300 / 200 / 200 / 100円** に配る
  （9/26の実際の配分の平均比率 31/20/18/12/11/8% を100円単位にしたもの）
- 1日 6レース × 1,600円 ＝ **9,600円**

## 何本当たれば戻るか（中央10-12R・6レースの日652日ぶんの実測）
    的中0本 17%（黒字0%） / 1本 33%（6%） / 2本 32%（31%）
    3本 13%（**68%**） / 4本 4%（**96%**） / 5本 1%（100%）
    3本以上の日 18% ・ 黒字の日 25% ・ 回収率 75% ・ 最大連続赤字 18日

**3本当たれば7割、4本ならほぼ確実に黒字**。ただし3本以上当たる日は
5〜6日に1日しかなく、長く続ければ回収率75%で削れる。ロールモデルは
「当たった日に取り切る形」を毎回そろえるためのもので、勝てる保証ではない。

推定オッズは単勝オッズからの Harville 推定（`keiba/oddsmodel.py`）。
**買う直前のオッズで出し直す**（朝と最終で人気の組が入れ替わることがある）。
単勝オッズが読めない馬がいるレースは人気順位の積で並べる。
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

from .models import load_horses
from .oddsmodel import estimate_umaren

STAKES = (500, 300, 300, 200, 200, 100)   # 人気の組から順に
RACE_BUDGET = sum(STAKES)                 # 1,600円
RACES = range(10, 13)                     # 10-12R
BOX = 4

# 6レースの日の実測（中央10-12R・2024-01〜2026-09・場の組652日。9/26の配分の平均比率で計算）
HIT_TABLE = (
    (0, "17%", "0%"), (1, "33%", "6%"), (2, "32%", "31%"),
    (3, "13%", "68%"), (4, "4%", "96%"), (5, "1%", "100%"),
)


@dataclass
class Ticket:
    pair: tuple[int, int]
    stake: int
    odds: float | None      # 推定馬連オッズ（倍）


@dataclass
class RacePlan:
    key: str                # "中山10R"
    name: str
    top: list[int]
    tickets: list[Ticket]

    @property
    def total(self) -> int:
        return sum(t.stake for t in self.tickets)


def race_number(r: dict) -> int | None:
    digits = "".join(ch for ch in str(r.get("race_no", "")) if ch.isdigit())
    return int(digits) if digits else None


def order_pairs(top: list[int], odds: dict[int, float],
                ninki: dict[int, int]) -> list[tuple[tuple[int, int], float | None]]:
    """4頭の6組を、推定オッズの短い順（＝人気の組から）に並べる。"""
    pairs = list(itertools.combinations(sorted(top), 2))
    if all(u in odds and odds[u] > 0 for u in top):
        est = {p: estimate_umaren(odds, *p) for p in pairs}
        if all(v for v in est.values()):
            return sorted(((p, est[p]) for p in pairs), key=lambda x: x[1])
    # オッズが読めないときは人気順位の積（数字は作らない＝推定オッズは空）
    big = 99
    return [(p, None) for p in sorted(
        pairs, key=lambda p: (ninki.get(p[0], big) * ninki.get(p[1], big),
                              ninki.get(p[0], big) + ninki.get(p[1], big)))]


def plan_race(r: dict, top: list[int]) -> RacePlan:
    horses = load_horses(r["entries"])
    odds = {h.umaban: h.tansho_odds for h in horses if h.tansho_odds}
    ninki = {h.umaban: h.ninki for h in horses if h.ninki}
    ordered = order_pairs(top[:BOX], odds, ninki)
    tickets = [Ticket(p, s, o) for (p, o), s in zip(ordered, STAKES)]
    return RacePlan(key=f"{r.get('venue', '')}{r.get('race_no', '')}",
                    name=r.get("name", ""), top=list(top[:BOX]), tickets=tickets)


def plan_day(config: dict, tops: dict[str, list[int]]) -> list[RacePlan]:
    """tops は {"中山10R": [スコア順の馬番...]}。載っていないレースは飛ばす。"""
    out = []
    for r in config["races"]:
        if race_number(r) not in RACES:
            continue
        key = f"{r.get('venue', '')}{r.get('race_no', '')}"
        if len(tops.get(key, [])) >= BOX:
            out.append(plan_race(r, tops[key]))
    return out


def format_day(plans: list[RacePlan], heading: str = "") -> str:
    lines = [f"【ロールモデル】馬連 上位4頭BOX・1レース{RACE_BUDGET:,}円・人気の組に厚く"]
    if heading:
        lines.append(heading)
    for p in plans:
        lines.append("")
        lines.append(f"{p.key} {p.name}  上位4頭 {'-'.join(map(str, p.top))}  計{p.total:,}円")
        for t in p.tickets:
            o = f"推定{t.odds:5.1f}倍" if t.odds else "推定  —  "
            back = f"当たれば約{t.stake * t.odds:,.0f}円" if t.odds else ""
            lines.append(f"  {t.pair[0]:>2}-{t.pair[1]:<2}  {t.stake:>4}円  {o}  {back}")
    total = sum(p.total for p in plans)
    lines += ["", f"合計 {len(plans)}レース {total:,}円",
              "",
              "何本当たれば戻るか（中央10-12R・6レースの日652日の実測）",
              "  的中本数  その日の割合  うち黒字"]
    lines += [f"  {h}本       {share:>4}        {black}" for h, share, black in HIT_TABLE]
    lines += ["  → 3本で約7割・4本でほぼ確実に黒字。3本以上の日は5〜6日に1日",
              "  ※推定オッズは単勝からの推定。買う直前のオッズで並びを確かめる"]
    return "\n".join(lines) + "\n"
