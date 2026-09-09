"""単勝・複勝1点買い。keiba/single.py（ワイド1点買い）を単勝・複勝向けに
コピーして作った。

ワイド1点買いは「2頭の組」を1点買うが、単勝・複勝は「1頭」を1点買う点だけが
違う。判断基準は同じ:

  * 実測の回収率が100%に届かない区分では**買わない**と表示する
  * 数字は必ず併記する（回収率・的中率・90%信頼区間・黒字確率・最大連敗）
  * 実測が無い区分は数字を作らず「データなし」と出す
  * 的中本数が10本未満の区分は、回収率が高くても「偶然の記録」として見送る

実測は scripts/tanpuku.py が作る data/profiles/*/tanpuku_stats.json。
**大井（地方）は対象外**として作っている（scripts/tanpuku.py 参照）。
中央9-12R 699レースで唯一3条件を満たしたのは「1倍台の単勝5位」（回収135%・
黒字確率80%・的中約20本）だが、単勝1〜13位×4帯＝52区分を同時に検定した
中の1つなので、**この的中数のまま過信しない**（多重比較。母数が増えたら
再検証する）。
"""
from __future__ import annotations

from dataclasses import dataclass

from . import profile
from .boxes import tier_of

# 1点買いを推奨する最低回収率。控除率を考えると100%が損益分岐
MIN_RETURN = 1.0
# この黒字確率を下回る区分は、回収率が100%を超えていても推奨しない
MIN_WIN_PROB = 0.40
# 実際に当たった本数の下限（keiba/single.py と同じ理由）
MIN_HITS = 10


@dataclass
class TanpukuPick:
    kind: str
    rank: int
    umaban: int
    stats: dict
    recommended: bool
    reason: str

    @property
    def label(self) -> str:
        return f"{self.kind} {self.rank}位"

    def stat_text(self) -> str:
        if not self.stats:
            return "実測データなし"
        s = self.stats
        return (f"回収{s['回収率']:.0%} 的中{s['的中率']:.0%} "
                f"90%区間{s['区間下']:.0%}〜{s['区間上']:.0%} "
                f"黒字{s['黒字確率']:.0%} 最大{s['最大連敗']}連敗 "
                f"最大DD{s['最大DD']:+,}円 ({s['n']}レース)")


def load_tanpuku_stats(prof: profile.Profile | None = None) -> dict:
    p = prof or profile.active()
    return p.load_json("tanpuku_stats.json")


def best_tanpuku(
    order: list[int],
    favorite_odds: float | None = None,
    stats: dict | None = None,
    kinds: tuple[str, ...] = ("単勝", "複勝"),
) -> TanpukuPick | None:
    """その帯で実測回収率がいちばん高い単勝・複勝の1点を返す。"""
    data = (stats if stats is not None else load_tanpuku_stats()).get("単複", {})
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
    rank = int(best_key[len(kind):])
    if len(order) < rank:
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

    return TanpukuPick(kind=kind, rank=rank, umaban=order[rank - 1],
                       stats=best_val, recommended=ok, reason=reason)
