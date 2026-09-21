"""買い目をそのまま書き写せる、テキストの予想様式。

HTMLは内訳を追うのには向くが、馬券を買う場では長い。ここでは
**スコア順に並べた上位馬と、5頭・6頭の候補**だけを短くまとめる。

大井などでは4頭・5頭を並べた買い目がよく使われるため、幅ごとの馬番を
そのまま出し、実測の的中率・回収率を添えて選べるようにする。
"""
from __future__ import annotations

import re

from .betting import BettingPlan
from .boxes import build_options
from .expectation import Expectation
from .aite import note as aite_note
from .hensachi import by_umaban, spread_note
from .sanko import (course_note, jockey_note, load_jockey_stats,
                    rento_note, surface_kind)
from .marks import MarkedHorse, assign_marks, split_for_total
from .arare import judge as arare_judge
from .notice import MARK_NOTICE
from .scoring import HorseScore
from .single import best_single
from .tanpuku import best_tanpuku
from .tekisei import trait_records

RULE = "━" * 46

# cp932（Shift_JIS）に無い文字の置き換え。古いWindows環境向けに
# 出力するとき、1文字のせいで書き出しごと失敗するのを防ぐ
CP932_SUBSTITUTES = {"—": "－"}


NAME_CHARS = 3      # 買い目に添える馬名の文字数
MAX_BOX_NAMES = 5   # 顔ぶれを書く上限（6頭ぶん並べると行が横に広がる）


def umaban_label(umaban: int, name: str | None, chars: int = NAME_CHARS) -> str:
    """馬番に馬名の頭を付ける。収支計算のとき番号だけだと照合できないため。

    「2-11」では、どの馬を買ったのか馬柱を開き直さないと分からない。
    「2テラメ-11ヨウシ」なら投票履歴や結果画面とそのまま突き合わせられる。
    名前が無い・短いときは在るぶんだけ付ける（`?` などを作らない）。
    """
    return f"{umaban}{(name or '')[:chars]}"


def ticket_label(combo, names: dict[int, str], chars: int = NAME_CHARS) -> str:
    """買い目1点を「2テラメ-11ヨウシ」の形にする。馬番の昇順で並べる。"""
    return "-".join(umaban_label(u, names.get(u), chars) for u in sorted(combo))


def ticket_lines(combos, names: dict[int, str], per_line: int = 4,
                 indent: str = "    ") -> list[str]:
    """買い目を「1イベン-2ブルー」の形で、折り返しながら並べる。

    馬番だけの「1-2」は、投票画面や投票履歴と突き合わせるときに
    馬柱を開き直すことになる（CLAUDE.md 9/13の精算で決めた方針）。
    名前を付けると1点が長くなるので、15点のような幅では行を折る。
    """
    items = [ticket_label(c, names) for c in combos]
    return [indent + "  ".join(items[i:i + per_line])
            for i in range(0, len(items), per_line)]


# 内訳を短く出すための道具。**長い注記をそのまま全頭ぶん並べると、
# 根拠が読まれなくなる**（本人の指示・2026-09-14「根拠の部分は縮めてください」）。
# 点の付いた項目だけを1行にまとめ、全馬に共通する事情はレースごとに1回書く
_SHORT = 14          # 補正の理由に添える文字数（騎手名・産駒名で足りる長さ）
_ABBR = {"基礎能力": "能力", "前走内容": "前走", "コース適性": "コース",
         "距離・展開・脚質": "距離脚質", "騎手補正": "騎手",
         "乗り替わり補正": "乗替", "血統補正": "血統", "枠順補正": "枠順",
         "前走不利補正": "前走不利", "高齢馬補正": "高齢",
         "初コース・ぶっつけペナルティ": "初コース"}


def _why(note: str) -> str:
    """注記から、誰・何による補正かだけを取り出す（「松山」「◯◯産駒」）。"""
    head = re.split(r"[:：（(]", note, maxsplit=1)[0].strip()
    return head[:_SHORT]


def _zenso(note: str) -> str:
    """「前走1着（3歳1勝クラス）」→「1着/3歳1勝クラス」。格は昇級の手がかり。"""
    m = re.match(r"前走(\d+着)(?:（(.+?)）)?", note)
    if not m:
        return _why(note)
    race = m.group(2) or ""
    return m.group(1) + (f"/{race}" if race and "不明" not in race else "")


def _ground_line(sc: HorseScore) -> str:
    """点の付いた項目だけを1行に畳む。載っていない項目は0点という約束。"""
    parts = []
    for it in sc.all_items():
        if not it.scored or not it.points:
            continue
        lbl = _ABBR.get(it.label, it.label)
        if it.label == "前走内容":
            parts.append(f"{lbl}{it.points:.1f}({_zenso(it.note)})")
        elif it.label in ("基礎能力", "コース適性", "距離・展開・脚質"):
            parts.append(f"{lbl}{it.points:.1f}")
        else:
            parts.append(f"{lbl}{it.points:+.1f}({_why(it.note)})")
    line = "      " + " ".join(parts)
    if sc.baba_note and sc.baba_note != "特記事項なし":
        line += f"  ※{sc.baba_note}"
    return line


def grounds_lines(marked: list[MarkedHorse], scores: list[HorseScore],
                  baba: str = "良") -> list[str]:
    """スコアの根拠を馬ごとに出す（印の付かない馬も含めた全頭・1頭2行）。

    画像の一覧は「おさらい」として点数だけを見せる様式なので、
    **根拠はこちら（テキスト）に置く**のが本人の指示した分担である
    （2026-09-14「根拠となる情報は文章にして出す」）。CLAUDE.mdの
    「スコア算出根拠（内訳）は必ず馬ごとに表示し、ブラックボックス化しない」
    をテキスト側で満たす箇所にあたる。

    全頭に共通する事情（採点対象外・全馬0点の補正・全馬中立の項目）は
    **レースごとに1回だけ**書く。全頭ぶん繰り返すと根拠が埋もれる。
    """
    if not scores:
        return ["【根拠】出走馬なし"]
    key = (lambda s: s.total_yoi) if baba == "良" else (lambda s: s.total_omoi)
    mark_of = {m.score.horse.umaban: m.mark for m in marked}
    out = [f"【根拠】スコアの内訳（全頭・満点{scores[0].max_base:.0f}点／"
           "載っていない項目は0点）"]
    for i, sc in enumerate(sorted(scores, key=key, reverse=True), start=1):
        h = sc.horse
        ninki = f"{h.ninki}人気{h.tansho_odds:.1f}倍" if h.ninki and h.tansho_odds \
            else (f"{h.ninki}人気" if h.ninki else "人気不明")
        out.append(f"{i:>2} {mark_of.get(h.umaban, '  ')} {h.umaban}{h.name}  "
                   f"良{sc.total_yoi:.1f}/重{sc.total_omoi:.1f}  "
                   f"{h.kyakushitsu or '脚質不明'}  {ninki}")
        out.append(_ground_line(sc))
    if note := _common_note(scores):
        out.append(f"   ※{note}")
    return out


def _common_note(scores: list[HorseScore]) -> str:
    """全馬に共通する事情を1文にする（採点対象外・全馬0点・全馬同点の項目）。"""
    labels = [i.label for i in scores[0].all_items()]
    skipped = scores[0].skipped_items
    zero, flat = [], []
    for lbl in labels:
        if lbl in skipped:
            continue
        pts = [i.points for s in scores for i in s.all_items() if i.label == lbl]
        if all(p == 0 for p in pts):
            zero.append(_ABBR.get(lbl, lbl))
        elif len(set(pts)) == 1:
            flat.append(f"{_ABBR.get(lbl, lbl)}は全馬{pts[0]:.1f}点")
    bits = []
    if skipped:
        bits.append(f"{'・'.join(skipped)}は採点対象外")
    if zero:
        bits.append(f"{'・'.join(zero)}は全馬0点")
    bits += flat
    return "／".join(bits)


def alt_order_note(scores: list[HorseScore], baba: str, n_show: int) -> str | None:
    """馬場の良/非良が逆だった場合に買い目が変わるか。変わらなければ None。

    `assign_marks` は `baba == "良"` かどうかしか見ないため、稍重・重・不良の
    取り違えでは並びは動かない。動くのは良↔非良をまたぐときだけである。

    実際に効くのは**上位4頭の顔ぶれ**（馬連4頭BOX＝推奨の買い目）が変わるか。
    順序だけの入れ替わりなら買い目は1点も変わらないので、そこは短く伝える。
    2026-09-12の阪神10Rがまさにこの形だった（稍重→良で3-4番手が入れ替わったが
    上位4頭も6頭も集合は同じで、買い目は変わらなかった）。
    """
    other = "稍重" if baba == "良" else "良"
    n_osae, n_chuui = split_for_total(n_show)

    def order(b: str) -> list[int]:
        return [m.score.horse.umaban for m in
                assign_marks(scores, baba=b, n_osae=n_osae, n_chuui=n_chuui)]

    now, alt = order(baba), order(other)
    if now == alt:
        return None
    if set(now[:4]) == set(alt[:4]):
        return f"※馬場が{other}でも上位4頭の顔ぶれは同じ（買い目は変わらない）"
    return (f"※馬場が{other}なら上位4頭が {'-'.join(str(u) for u in alt[:4])} に"
            f"変わる（買い目が変わる）。発走前に馬場を確認する")


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
    抜けているのかは点差の散らばり次第で変わる（keiba/hensachi.py）。

    持ち時計を併記する理由: 基礎能力25点の尺度は2026-09-13に上がり3Fから
    **持ち時計指数**（直近365日・距離と馬場で正規化した走破タイム）へ
    変わったが、値はスコアに溶けて見えなかった。出すのは
    **メンバー平均差**——採点がメンバー相対で使っている量そのもので、
    絶対値はレースの格を含むため頭数の違うレースをまたいで読めない。
    **作れない馬は空にする**。中立値を入れると、窓内3走未満で上がり3Fに
    落ちた馬（2歳戦では大半）が「平均並みの時計を持つ馬」に見える。"""
    h = m.score.horse
    ninki = f"{h.ninki}人気" if h.ninki else "—"
    odds = f"{h.tansho_odds:.1f}倍" if h.tansho_odds else "—"
    win, place = exp.format(rank)
    score = f"良{m.score.total_yoi:.1f}/重{m.score.total_omoi:.1f}"
    dev = (devs or {}).get(h.umaban)
    dev_txt = f"偏差{dev:>4.1f}" if dev is not None else "偏差   —"
    md = m.score.mochi_delta
    # 小数2桁。レース内の平均差の幅は実測で 1.0〜1.7 しかないので、
    # 1桁に丸めると近い馬が同じ値に潰れて読み比べられない
    mochi_txt = f"時計{md:>+6.2f}" if md is not None else "時計    —"
    return (f"{rank:>2} {m.mark} {h.umaban:>2} {h.name:<14}"
            f"{ninki:>6}{odds:>8}  {score:>12} {dev_txt} {mochi_txt}  "
            f"{h.kyakushitsu or '—':<3} 1着{win}/着内{place}")


def mochi_note(scores: list[HorseScore]) -> str:
    """持ち時計が何頭に作れたかを1行に添える。

    作れない馬は上がり3Fに落ちる（`score_kiso_nouryoku`）。**混在している
    ことを隠さない**のが目的で、2歳戦・障害では窓内3走に届かず0頭になる。
    0頭のときこそ出す価値がある（そのレースだけ旧尺度で採点されている）。
    """
    n = len(scores)
    k = sum(1 for s in scores if s.mochi_delta is not None)
    used = any(s.mochi_used for s in scores)
    if k and not used:
        tail = "（表示のみ・採点は上がり3F）"
    elif k == n:
        tail = ""
    elif k:
        tail = "（残りは上がり3Fで代替）"
    else:
        tail = "（上がり3Fで採点）"
    return f"持ち時計 {k}/{n}頭{tail}"


def sanko_lines(marked: list[MarkedHorse], scores: list[HorseScore],
                records: dict[str, list[dict]] | None,
                venue: str | None, surface: str, baba: str,
                kyori: int | None, as_of: str | None,
                n_show: int = 8) -> list[str]:
    """参考注記（相手関係・騎手の得意条件・持ち時計の読み・コース注記）。

    いずれも**スコアには入っていない**（`keiba/sanko.py`）。該当が無ければ
    見出しごと出さない。行の有無で「該当なし」を伝えるのは、1点買いの
    ★と同じ扱い（本人の指示「説明しすぎない」）。
    """
    # 障害は None になる（平地で測った実測を当てない）
    sd = surface_kind(surface)
    race_note = course_note(venue, sd, baba)
    stats = load_jockey_stats(venue=venue)
    # 騎手の「得意条件」は全体成績との対比で出すので、比べる相手が要る
    from .scoring import load_ratings
    baseline = load_ratings().get("騎手", {})

    idx = None
    if records:
        from .aite import Index
        idx = Index.build(records)
    today = [s.horse.name for s in scores]

    # 持ち時計を「走ってきたレースの水準」と「そのレース内での相対」に分ける
    # （`keiba/racelevel.py`）。**採点は現行のまま**（絶対＝2成分の和を
    # メンバー相対で使う）。分解して4帯すべてで再現したのは和だけなので、
    # ここは読みの助けとしての表示にとどめる
    # **障害では出さない**（`racelevel.build_levels` が 馬場種別 not in 芝/ダ を
    # 除いているので、レース水準は障害で一度も測っていない）
    level_note = None
    mochi_notes: dict[str, str] = {}
    if sd:
        from . import racelevel as rl
        from .scoring import _base_times
        splits = rl.field_splits(records, today, rl.load_table(venue=venue),
                                 as_of, _base_times(venue))
        level_note = rl.race_note(splits)
        mochi_notes = rl.horse_notes(
            splits, {s.horse.name: s.horse.ninki for s in scores})

    lines: list[str] = []
    for i, m in enumerate(marked[:n_show], start=1):
        h = m.score.horse
        bits = []
        if idx is not None and as_of:
            d = idx.delta(h.name, today, as_of)
            if n := aite_note(d, h.zenso_chakujun):
                bits.append(n)
        if n := jockey_note(h.jockey, stats, venue, sd, kyori,
                            h.kyakushitsu, h.wakuban, baseline):
            bits.append(n)
        if n := rento_note(h.kankaku, h.ninki, h.zenso_chakujun):
            bits.append(n)
        if n := mochi_notes.get(h.name):
            bits.append(n)
        if bits:
            lines.append(f"  {i:>2} {m.mark} {h.umaban:>2} {h.name:<14}"
                         + "  ".join(bits))

    if not lines and not race_note and not level_note:
        return []
    out = ["", "【参考】スコアには未反映"]
    if level_note:
        out.append(f"  ※{level_note}")
    if race_note:
        out.append(f"  ※{race_note}")
    out.extend(lines)
    return out


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
    kyori: int | None = None,
    breakdown: bool = False,
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
    # 一致・不一致は収集した時点のオッズで決まる。朝と最終で人気が入れ替わる馬が
    # 実際にいる（2026-09-12の中央8レースでは3レースで判定がひっくり返った）ため、
    # どの時点の判定なのかを必ず添える。買い目の型も同じ理由で最終オッズで決める
    # 荒れそう／堅そうは **1番人気オッズ帯 × 上位3人気の支持集中度** の2軸で
    # 決める（`keiba/arare.py`）。帯で統制しても残った特徴が集中度だけだった。
    # 率は出さない（順位・区分に付いた一般値であって今日の確率ではない）
    arare = arare_judge(fav, [s.horse for s in scores], venue=venue)
    out.append(f"{fav_txt} → 【{plan.strategy}型】"
               + (f"・{arare}" if arare else "")
               + f"  ◎と1番人気: {'一致' if agree else '不一致'}"
               f" ※収集時のオッズ。発走前に最終オッズで再判定")
    out.append(f"レース内{spread_note(devs)}")

    # **馬場の判定が反転したときの並び順を併記する。**
    # 印の並びは「良か、良以外か」だけで決まる（`keiba/marks.py`）。馬場は
    # 発走までに変わり、特にダートは乾いて回復するので朝の値が古くなりやすい
    # （2026-09-12は生成後もダート4レースの馬場がずれていた）。
    # 反転しても並びが変わらないなら何も出さない（変わる場合だけ知らせる）
    if alt := alt_order_note(scores, baba, len(marked)):
        out.append(alt)

    if marked and (skipped := marked[0].score.skipped_items):
        out.append(f"※ {'・'.join(skipped)}は採点対象外（満点{marked[0].score.max_base:.0f}点）")

    # 目玉: ワイド1点。当てにいくのではなく、損を小さく保って回収率を取る。
    # **推奨が出たときだけ書く**（本人の指示・2026-09-14「見送りと
    # 実測値なしはいらない」）。行が無いこと自体が「買う1点は無い」を
    # 意味する。条件の中身と実測は `scripts/single.py` / `tanpuku.py` 側に残る
    names = {s.horse.umaban: s.horse.name for s in scores}
    pick = best_single(order, favorite_odds=fav)
    tp = best_tanpuku(order, favorite_odds=fav)
    # 実測（回収率・的中率・連敗）も出さない。買い目と同じ理由で、
    # **基準の伝わらない数字を並べない**。数字は `single_stats.json` /
    # `tanpuku_stats.json` と各スクリプトの出力に残る
    if pick is not None and pick.recommended:
        out.append("")
        out.append(f"【ワイド1点】★ {ticket_label(pick.umaban, names)}")
    if tp is not None and tp.recommended:
        if not (pick is not None and pick.recommended):
            out.append("")
        out.append(f"【単複1点】★ {umaban_label(tp.umaban, names.get(tp.umaban))}"
                   f"（{tp.label}）")

    out.append("")
    out.append(f"【スコア順】  {mochi_note(scores)}")
    for i, m in enumerate(marked[:n_show], start=1):
        out.append(_horse_line(i, m, exp, devs))

    marked_umaban = {m.score.horse.umaban for m in marked}
    rest = [s for s in sorted(scores, key=lambda s: s.total_yoi, reverse=True)
            if s.horse.umaban not in marked_umaban]
    if rest:
        out.append("  参考(印なし): " + " ".join(
            f"{s.horse.umaban}{s.horse.name}(偏差{devs.get(s.horse.umaban, 50):.0f})"
            for s in rest[:5]))

    if records and venue and (sk := surface_kind(surface)):
        # コース特性ごとの適性。**点数には入れていない**（scripts/course_traits.py
        # の独立検証で判別力が確認できなかったため）。母数と対比を出して
        # 買う人が判断できる形にする第1段階。
        # 障害（surface_kind が None）は対象外
        lines = []
        for i, m in enumerate(marked[:n_show], start=1):
            h = m.score.horse
            recs = trait_records(records.get(h.name, []), venue,
                                 "芝" if sk == "芝" else "ダート", as_of)
            notable = [r for r in recs if r.tag in ("得意", "苦手")]
            if not notable:
                continue
            # 軸名ではなく**値**を出す。阪神（広いコース）で「小回り=得意」と
            # 表示すると、小回りが得意なのだと誤読される。実際は
            # 「広いコースが得意」なので、値そのものを見せる
            lines.append(f"  {i:>2} {m.mark} {h.umaban:>2} {h.name:<14}" +
                         "  ".join(f"{r.value}={r.tag}({r.diff:+.0%} "
                                   f"{r.n_match}走複{r.rate_match:.0%}"
                                   f"→他{r.n_other}走複{r.rate_other:.0%})"
                                   for r in notable[:2]))
        if lines:
            out.append("")
            out.append("【コース特性】全キャリアから。その馬の中での対比（点数には未反映）")
            out.extend(lines)

    out.extend(sanko_lines(marked, scores, records, venue, surface, baba,
                           kyori, as_of, n_show))

    # **BOXなので組み合わせは並べない**（本人の指示・2026-09-14
    # 「買い目は何個も並べなくていい。ボックスで伝わります」）。
    # 幅ごとの顔ぶれを1行に出すので、以前の【候補】は役目が重なるため畳んだ。
    # ただし**6頭ぶん並べると行が横に広がる**ので、顔ぶれを書くのは
    # MAX_BOX_NAMES 頭まで。それより広い幅は「上位n頭」とだけ書く
    # （並びは上の【スコア順】で読める）。
    # **的中率・回収率は出さない**（本人の指示・2026-09-14「的中回収に
    # ついてはよくわからない基準だと思うのでかかなくてもいい」）。
    # 実測そのものは `box_stats.json` と `scripts/boxstats.py` に残る
    out.append("")
    out.append("【買い目】★=推奨")
    rec = ("ワイド", 3) if plan.wide else ("馬連", 4)
    for o in build_options(order, favorite_odds=fav, recommended=rec):
        if o.width not in (3, 4, 5, 6):
            continue
        head = "★" if o.recommended else "  "
        box = ("-".join(umaban_label(u, names.get(u)) for u in order[:o.width])
               if o.width <= MAX_BOX_NAMES else f"上位{o.width}頭")
        out.append(f"{head}{o.kind} {o.width}頭BOX {o.points:>2}点  {box}")

    if breakdown:
        out.append("")
        out.extend(grounds_lines(marked, scores, baba))
    return "\n".join(out)


def format_day(blocks: list[str], heading: str) -> str:
    body = "\n\n".join(blocks)
    return f"{heading}\n\n{body}\n{RULE}\n{MARK_NOTICE}\n"
