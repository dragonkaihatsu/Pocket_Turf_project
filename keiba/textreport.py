"""買い目をそのまま書き写せる、テキストの予想様式。

HTMLは内訳を追うのには向くが、馬券を買う場では長い。ここでは
**スコア順に並べた上位馬と、5頭・6頭の候補**だけを短くまとめる。

大井などでは4頭・5頭を並べた買い目がよく使われるため、幅ごとの馬番を
そのまま出し、実測の的中率・回収率を添えて選べるようにする。
"""
from __future__ import annotations

from .betting import BettingPlan
from .boxes import build_options
from .expectation import Expectation
from .marks import MarkedHorse
from .scoring import HorseScore
from .single import best_single

RULE = "━" * 46

# cp932（Shift_JIS）に無い文字の置き換え。古いWindows環境向けに
# 出力するとき、1文字のせいで書き出しごと失敗するのを防ぐ
CP932_SUBSTITUTES = {"—": "－"}


def to_encoding(text: str, encoding: str) -> str:
    """指定の文字コードで表現できない文字を、近い形の文字に置き換える。"""
    if encoding.lower().replace("_", "-") not in ("cp932", "shift-jis", "shift-jis"):
        return text
    for src, dst in CP932_SUBSTITUTES.items():
        text = text.replace(src, dst)
    return text


def _horse_line(rank: int, m: MarkedHorse, exp: Expectation) -> str:
    h = m.score.horse
    ninki = f"{h.ninki}人気" if h.ninki else "—"
    odds = f"{h.tansho_odds:.1f}倍" if h.tansho_odds else "—"
    win, place = exp.format(rank)
    return (f"{rank:>2} {m.mark} {h.umaban:>2} {h.name:<14}"
            f"{ninki:>6}{odds:>8}  {m.score.total_yoi:>5.1f}  "
            f"{h.kyakushitsu or '—':<3} 1着{win}/着内{place}")


def format_race(
    title: str,
    surface: str,
    post_time: str,
    marked: list[MarkedHorse],
    scores: list[HorseScore],
    plan: BettingPlan,
    exp: Expectation | None = None,
    n_show: int = 8,
) -> str:
    """1レース分をテキストにする。"""
    exp = exp if exp is not None else Expectation()
    out: list[str] = [RULE, f"{title}  {surface}  発走{post_time}"]

    fav = plan.favorite_odds
    order = [m.score.horse.umaban for m in marked]
    fav_umaban = next((m.score.horse.umaban for m in marked
                       if m.score.horse.ninki == 1), None)
    if fav_umaban is None:
        fav_umaban = next((s.horse.umaban for s in scores if s.horse.ninki == 1), None)
    agree = fav_umaban is not None and order and order[0] == fav_umaban
    fav_txt = f"1番人気 {fav:.1f}倍" if fav else "1番人気 オッズ不明"
    out.append(f"{fav_txt} → 【{plan.strategy}型】"
               f"  ◎と1番人気: {'一致' if agree else '不一致'}")

    if marked and (skipped := marked[0].score.skipped_items):
        out.append(f"※ {'・'.join(skipped)}は採点対象外（満点{marked[0].score.max_base:.0f}点）")

    # 目玉: ワイド1点。当てにいくのではなく、損を小さく保って回収率を取る
    pick = best_single(order, favorite_odds=fav)
    out.append("")
    if pick is None:
        out.append("【ワイド1点】実測データなし → 判断材料なし")
    elif pick.recommended:
        out.append(f"【ワイド1点】★ {pick.combo}  （{pick.label}）")
        out.append(f"    {pick.stat_text()}")
    else:
        out.append(f"【ワイド1点】見送り推奨  参考: {pick.combo}（{pick.label}）")
        out.append(f"    {pick.reason}")
        out.append(f"    {pick.stat_text()}")

    out.append("")
    out.append("【スコア順】")
    for i, m in enumerate(marked[:n_show], start=1):
        out.append(_horse_line(i, m, exp))

    marked_umaban = {m.score.horse.umaban for m in marked}
    rest = [s for s in sorted(scores, key=lambda s: s.total_yoi, reverse=True)
            if s.horse.umaban not in marked_umaban]
    if rest:
        out.append("  参考(印なし): " + " ".join(
            f"{s.horse.umaban}{s.horse.name}" for s in rest[:5]))

    out.append("")
    out.append("【候補】スコア順に並べた馬番")
    for w in (3, 4, 5, 6):
        if len(order) >= w:
            out.append(f"  {w}頭  " + "-".join(str(u) for u in order[:w]))

    out.append("")
    out.append("【買い目】★=推奨")
    rec = ("ワイド", 3) if plan.wide else ("馬連", 4)
    for o in build_options(order, favorite_odds=fav, recommended=rec):
        if o.width not in (3, 4, 5, 6):
            continue
        head = "★" if o.recommended else "  "
        st = o.stats
        stat = (f"的中{st['的中率']:.0%} 回収{st['回収率']:.0%} 黒字{st['黒字確率']:.0%}"
                if st else "実測データなし")
        out.append(f"{head}{o.kind} {o.width}頭BOX {o.points:>2}点  {stat}")
        out.append(f"    " + " ".join(f"{a}-{b}" for a, b in o.combos))
    return "\n".join(out)


def format_day(blocks: list[str], heading: str) -> str:
    body = "\n\n".join(blocks)
    return f"{heading}\n\n{body}\n{RULE}\n"
