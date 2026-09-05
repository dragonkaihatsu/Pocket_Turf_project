"""ワイド1点買い。「これだけ押さえればよい」1点を実測から選ぶ。

点数を増やすほど的中率は上がるが回収率は下がる、という関係は
data/profiles/*/box_stats.json で確認済み。その延長線の端が1点買いになる。

この機能の目的は**当てにいくことではなく、損を小さく保ったまま回収率を取る**
こと。したがって:

  * 実測の回収率が100%に届かない区分では**買わない**と表示する。
    「一応これ」を出すと、当たらない1点を買い続けることになる
  * 数字は必ず併記する（回収率・的中率・90%信頼区間・黒字確率・最大連敗）
  * 実測が無い区分は数字を作らず「データなし」と出す

実測（大井9-12R 244レース／中央9-12R 690レース）では、100%を超えるのは
大井の2倍台だけだった。中央はどの帯でも100%に届かない。
"""
from __future__ import annotations

from dataclasses import dataclass

from . import profile
from .boxes import tier_of

# 1点買いを推奨する最低回収率。控除率を考えると100%が損益分岐
MIN_RETURN = 1.0
# この黒字確率を下回る区分は、回収率が100%を超えていても推奨しない
MIN_WIN_PROB = 0.40
# 実際に当たった本数の下限。1点買いは的中率が低いため、母数レース数が
# 多くても実際の的中が数本しかないことがある。3本の的中から
# 「回収率296%」と言っても、それは推定ではなく偶然の記録でしかない
MIN_HITS = 10


@dataclass
class SinglePick:
    kind: str
    rank_a: int
    rank_b: int
    umaban: tuple[int, int]
    stats: dict
    recommended: bool
    reason: str

    @property
    def label(self) -> str:
        return f"{self.kind} {self.rank_a}位-{self.rank_b}位"

    @property
    def combo(self) -> str:
        return f"{self.umaban[0]}-{self.umaban[1]}"

    def stat_text(self) -> str:
        if not self.stats:
            return "実測データなし"
        s = self.stats
        return (f"回収{s['回収率']:.0%} 的中{s['的中率']:.0%} "
                f"90%区間{s['区間下']:.0%}〜{s['区間上']:.0%} "
                f"黒字{s['黒字確率']:.0%} 最大{s['最大連敗']}連敗 "
                f"最大DD{s['最大DD']:+,}円 ({s['n']}レース)")


def load_single_stats(prof: profile.Profile | None = None) -> dict:
    p = prof or profile.active()
    return p.load_json("single_stats.json")


def best_single(
    order: list[int],
    favorite_odds: float | None = None,
    stats: dict | None = None,
    kinds: tuple[str, ...] = ("ワイド",),
) -> SinglePick | None:
    """その帯で実測回収率がいちばん高い1点を返す。

    kinds を絞れる（既定はワイドのみ）。馬連の1点は当たれば大きいが、
    実測では90連敗級の並びが出ており「欠損の少ない買い方」にはならない。
    """
    data = (stats if stats is not None else load_single_stats()).get("1点買い", {})
    tier = tier_of(favorite_odds)
    table = data.get(tier) or data.get("全体") or {}
    if not table:
        return None

    best_key = best_val = None
    for key, val in table.items():
        kind = next((k for k in kinds if key.startswith(k)), None)
        if kind is None:
            continue
        if best_val is None or val["回収率"] > best_val["回収率"]:
            best_key, best_val = key, val
    if best_key is None:
        return None

    kind = next(k for k in kinds if best_key.startswith(k))
    a, b = (int(x) for x in best_key[len(kind):].split("-"))
    if len(order) < max(a, b):
        return None

    hits = round(best_val["n"] * best_val["的中率"])
    ok = (best_val["回収率"] >= MIN_RETURN
          and best_val["黒字確率"] >= MIN_WIN_PROB
          and hits >= MIN_HITS)
    if ok:
        reason = (f"{tier}の実測で回収率が損益分岐を超えている"
                  f"（的中{hits}本）")
    elif hits < MIN_HITS:
        reason = (f"的中が{hits}本しかなく、回収率{best_val['回収率']:.0%}は"
                  "推定ではなく偶然の記録に近い → 見送り")
    elif best_val["回収率"] < MIN_RETURN:
        reason = (f"{tier}では最良の1点でも回収率{best_val['回収率']:.0%}で"
                  "損益分岐に届かない → 見送り")
    else:
        reason = (f"回収率は{best_val['回収率']:.0%}だが黒字確率"
                  f"{best_val['黒字確率']:.0%}が低く、当たり外れが大きい → 見送り")

    return SinglePick(kind=kind, rank_a=a, rank_b=b,
                      umaban=(order[a - 1], order[b - 1]),
                      stats=best_val, recommended=ok, reason=reason)
