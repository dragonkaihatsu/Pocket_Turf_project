"""点数別（上位n頭BOX）の買い目候補と、その実測成績。

システムの推奨は1つに絞るが、**買うかどうかを決めるのは買う人**なので、
「4頭なら」「5頭なら」「6頭なら」を実測値つきで並べて出す。

大井では4頭・5頭を並べた買い目がよく使われる。9/4の12Rのように
1着がスコア4位・2着が6位というケースは、幅を広げれば拾えていた。
広げると回収率が下がることも同時に示し、判断材料を揃える。

数字は scripts/boxstats.py が作る data/box_stats.json（実測）。
無い場合は数字を出さず「—」にする。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

BOX_STATS_PATH = Path(__file__).resolve().parent.parent / "data" / "box_stats.json"
WIDTHS = (3, 4, 5, 6)


def load_box_stats(path: Path | str | None = None) -> dict:
    p = Path(path) if path else BOX_STATS_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


@dataclass
class BoxOption:
    """ある券種・ある頭数での買い目候補。"""
    kind: str
    width: int
    umaban: list[int]
    points: int
    recommended: bool = False
    stats: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.kind} 上位{self.width}頭BOX({self.points}点)"

    @property
    def combos(self) -> list[tuple[int, int]]:
        return list(combinations(self.umaban, 2))

    def stat_text(self) -> str:
        if not self.stats:
            return "実測データなし"
        s = self.stats
        return (f"的中率{s['的中率']:.0%} / 回収率{s['回収率']:.0%}"
                f"（90%区間 {s['区間下']:.0%}〜{s['区間上']:.0%}・"
                f"黒字確率{s['黒字確率']:.0%}・{s['n']}レース）")


def tier_of(favorite_odds: float | None) -> str:
    if favorite_odds is None:
        return "全体"
    if favorite_odds < 2.0:
        return "1倍台"
    if favorite_odds < 3.0:
        return "2倍台"
    return "3倍以上"


def build_options(
    order: list[int],
    favorite_odds: float | None = None,
    recommended: tuple[str, int] | None = None,
    stats: dict | None = None,
) -> list[BoxOption]:
    """スコア順の馬番から、券種×頭数の候補を作る。

    recommended に (券種, 頭数) を渡すと、その候補に印を付ける。
    """
    stats = stats if stats is not None else load_box_stats()
    table = stats.get("点数別", {})
    tier = tier_of(favorite_odds)
    out: list[BoxOption] = []
    for kind in ("ワイド", "馬連"):
        for w in WIDTHS:
            if len(order) < w:
                continue
            rec = table.get(kind, {}).get(str(w), {})
            out.append(BoxOption(
                kind=kind, width=w, umaban=order[:w],
                points=len(list(combinations(range(w), 2))),
                recommended=(recommended == (kind, w)),
                stats=rec.get(tier) or rec.get("全体") or {},
            ))
    return out


def best_by_return(options: list[BoxOption]) -> BoxOption | None:
    """実測回収率がいちばん高い候補。データが無ければ None。"""
    scored = [o for o in options if o.stats]
    return max(scored, key=lambda o: o.stats["回収率"]) if scored else None
