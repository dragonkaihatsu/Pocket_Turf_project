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
from .hensachi import by_umaban, spread_note
from .marks import MarkedHorse
from .scoring import HorseScore
from .single import best_single
from .tanpuku import best_tanpuku
from .tekisei import trait_records

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


def _horse_line(rank: int, m: MarkedHorse, exp: Expectation,
                devs: dict[int, float] | None = None) -> str:
    """CLAUDE.mdの「良馬場スコア・重馬場スコアを2軸で併記する」に合わせ、
    どちらか一方（レース当日の baba による並び順の軸）だけを大きく出さず
    両方の数字を出す。良馬場scoreだけを表示すると、稍重・重・不良の
    レースでは印の並び（total_omoiでソート済み）と表示スコアの大小が
    食い違って見える（例: 1位の良65.1 < 2位の良68.2、実際は重で逆転）

    偏差値を併記する理由: 絶対点数だけでは「その点差が大きいのか小さいのか」
    が読めない。1位と2位の差は実測で中央値2.6点しかなく、混戦なのか
    抜けているのかは点差の散らばり次第で変わる（keiba/hensachi.py）。"""
    h = m.score.horse
    ninki = f"{h.ninki}人気" if h.ninki else "—"
    odds = f"{h.tansho_odds:.1f}倍" if h.tansho_odds else "—"
    win, place = exp.format(rank)
    score = f"良{m.score.total_yoi:.1f}/重{m.score.total_omoi:.1f}"
    dev = (devs or {}).get(h.umaban)
    dev_txt = f"偏差{dev:>4.1f}" if dev is not None else "偏差   —"
    return (f"{rank:>2} {m.mark} {h.umaban:>2} {h.name:<14}"
            f"{ninki:>6}{odds:>8}  {score:>12} {dev_txt}  "
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
    baba: str = "良",
    records: dict[str, list[dict]] | None = None,
    venue: str | None = None,
    as_of: str | None = None,
) -> str:
    """1レース分をテキストにする。

    baba は偏差値をどちらのスコア軸で出すかに使う（印の並びを決める
    assign_marks と同じ軸に揃える。良馬場なら良スコア、それ以外は重スコア）。
    """
    exp = exp if exp is not None else Expectation()
    # 偏差値は印が付かなかった馬も含めた全頭で計算する（母集団を変えないため）
    devs = by_umaban(scores, baba=baba)
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
    out.append(f"レース内{spread_note(devs)}")

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

    # 単複1点。単勝・複勝だけを見て1頭を指名する
    tp = best_tanpuku(order, favorite_odds=fav)
    if tp is None:
        out.append("【単複1点】実測データなし → 判断材料なし")
    elif tp.recommended:
        out.append(f"【単複1点】★ {tp.umaban}番  （{tp.label}）")
        out.append(f"    {tp.stat_text()}")
    else:
        out.append(f"【単複1点】見送り推奨  参考: {tp.umaban}番（{tp.label}）")
        out.append(f"    {tp.reason}")
        out.append(f"    {tp.stat_text()}")

    out.append("")
    out.append("【スコア順】")
    for i, m in enumerate(marked[:n_show], start=1):
        out.append(_horse_line(i, m, exp, devs))

    marked_umaban = {m.score.horse.umaban for m in marked}
    rest = [s for s in sorted(scores, key=lambda s: s.total_yoi, reverse=True)
            if s.horse.umaban not in marked_umaban]
    if rest:
        out.append("  参考(印なし): " + " ".join(
            f"{s.horse.umaban}{s.horse.name}(偏差{devs.get(s.horse.umaban, 50):.0f})"
            for s in rest[:5]))

    if records and venue:
        # コース特性ごとの適性。**点数には入れていない**（scripts/course_traits.py
        # の独立検証で判別力が確認できなかったため）。母数と対比を出して
        # 買う人が判断できる形にする第1段階
        lines = []
        for i, m in enumerate(marked[:n_show], start=1):
            h = m.score.horse
            recs = trait_records(records.get(h.name, []), venue,
                                 "芝" if surface.startswith("芝") else "ダート",
                                 as_of)
            notable = [r for r in recs if r.tag in ("得意", "苦手")]
            if not notable:
                continue
            lines.append(f"  {i:>2} {m.mark} {h.umaban:>2} {h.name:<14}" +
                         "  ".join(f"{r.axis}={r.tag}({r.diff:+.0%} "
                                   f"{r.n_match}走複{r.rate_match:.0%}"
                                   f"→他{r.n_other}走複{r.rate_other:.0%})"
                                   for r in notable[:2]))
        if lines:
            out.append("")
            out.append("【コース特性】全キャリアから。その馬の中での対比（点数には未反映）")
            out.extend(lines)

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
