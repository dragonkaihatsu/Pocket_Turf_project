"""アメーバブログに貼り付けるHTMLを作る（スマホ表示優先）。

アメブロには外部から投稿するAPIが無い（AtomPub APIは終了済み）。
そこで**HTML編集モードにそのまま貼れる形**で書き出す。

アメブロのHTML編集には制約がある:

- `<style>` ブロックや外部CSSは落とされる → **インラインstyleだけで組む**
- `<script>` は通らない → 動的なタブや折りたたみは使わない
- 記事の表示幅はスマホで概ね 320〜380px → **横に広い表を置かない**
- ブログ側のテーマが文字色・背景を持つ → 前景色と背景色を必ず両方指定し、
  テーマ任せにしない（白背景テーマでも黒背景テーマでも読める組み合わせにする）

そのため馬の一覧は table ではなく、1頭=1ブロックの積み上げにしている。
スコアは数字だけでなく横棒でも出す。スマホでは数字の比較が読み取りにくいため。
"""
from __future__ import annotations

from .betting import BettingPlan
from .boxes import build_options
from .expectation import Expectation
from .marks import MarkedHorse
from .scoring import HorseScore
from .single import best_single

# 白背景でも薄い色背景でも読める配色。彩度を抑え、印だけを色で立てる
# アメブロの本文上限は半角60,000文字で、**HTMLタグを含めて**数えられる。
# しかも投稿時に自動整形されて文字数が増えることがあるため、余裕を持たせる。
# インラインstyleは1頭ごとに繰り返されるので、色は3桁、宣言は最小限にする。
AMEBA_LIMIT = 60000
SAFE_LIMIT = 48000   # 自動整形で増えるぶんの余白

INK = "#222"
MUTED = "#666"
LINE = "#ddd"
PANEL = "#f5f5f5"
MARK_COLORS = {"◎": "#c0392b", "○": "#1f6fb2", "▲": "#2e7d4f",
               "△": "#7a6a3a", "注": "#6b4a8a"}

BASE = f"font-family:-apple-system,'Hiragino Kaku Gothic ProN',sans-serif;color:{INK};"


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _bar(ratio: float, color: str) -> str:
    """スコアの横棒。スマホでは数字の大小が読み取りにくいので併記する。"""
    pct = max(2, min(100, round(ratio * 100)))
    # 枠と中身の二重divをやめ、border-top 1本で描く。アメブロは本文の
    # 文字数をHTMLタグ込みで数えるため、1頭あたり数十文字の差が効いてくる
    return f'<div style="border-top:5px solid {color};width:{pct}%;margin-top:4px"></div>'


def _horse_block(rank: int, m: MarkedHorse, top_score: float, exp: Expectation) -> str:
    h = m.score.horse
    color = MARK_COLORS.get(m.mark, MUTED)
    ninki = f"{h.ninki}番人気" if h.ninki else "人気—"
    odds = f"{h.tansho_odds:.1f}倍" if h.tansho_odds else "オッズ—"
    win, place = exp.format(rank)
    # 期待度は実測が無ければ「—」になる。その場合は行ごと出さない
    exp_txt = "" if win == "—" and place == "—" else f" / 1着{win}・着内{place}"
    ratio = m.score.total_yoi / top_score if top_score else 0.0
    return (
        f'<div style="padding:8px 0;border-bottom:1px solid {LINE}">'
        f'<div style="font-size:15px;line-height:1.5">'
        f'<b style="color:{color}">{_esc(m.mark)}</b> '
        f'<span style="color:{MUTED}">{h.umaban}</span> '
        f'<b>{_esc(h.name)}</b> {m.score.total_yoi:.1f}</div>'
        f'<div style="font-size:12px;color:{MUTED};line-height:1.6">'
        f'{ninki} / {odds} / {_esc(h.kyakushitsu or "脚質—")}{exp_txt}</div>'
        f'{_bar(ratio, color)}</div>'
    )


def _section(title: str, body: str) -> str:
    return (f'<div style="margin:18px 0 6px;font-size:13px;font-weight:bold;'
            f'color:{MUTED}">{_esc(title)}</div>{body}')


def format_race_html(
    title: str,
    surface: str,
    post_time: str,
    marked: list[MarkedHorse],
    scores: list[HorseScore],
    plan: BettingPlan,
    exp: Expectation | None = None,
    n_show: int = 8,
) -> str:
    """1レース分のHTML。アメブロのHTML編集にそのまま貼れる。"""
    exp = exp if exp is not None else Expectation()
    fav = plan.favorite_odds
    order = [m.score.horse.umaban for m in marked]
    fav_umaban = next((s.horse.umaban for s in scores if s.horse.ninki == 1), None)
    agree = fav_umaban is not None and order and order[0] == fav_umaban
    top_score = marked[0].score.total_yoi if marked else 0.0

    parts = [
        '<div style="margin:0 0 28px;">',
        f'<div style="border-left:4px solid {INK};padding-left:10px;margin-bottom:10px;">'
        f'<div style="font-size:18px;font-weight:bold;line-height:1.4;">{_esc(title)}</div>'
        f'<div style="font-size:12px;color:{MUTED};">'
        f'{_esc(surface)}{"  発走" + _esc(post_time) if post_time else ""}</div></div>',
        f'<div style="background:{PANEL};padding:10px 12px;border-radius:6px;'
        f'font-size:13px;line-height:1.7;">'
        f'1番人気 {f"{fav:.1f}倍" if fav else "オッズ不明"} → <strong>{_esc(plan.strategy)}型</strong><br>'
        f'◎と1番人気: <strong>{"一致" if agree else "不一致"}</strong>'
        f'<span style="color:{MUTED};">'
        f'（一致なら勝率55%・不一致なら14%が実測値）</span></div>',
    ]

    pick = best_single(order, favorite_odds=fav)
    if pick is None:
        body = f'<div style="font-size:14px;">実測データなし → 判断材料なし</div>'
    elif pick.recommended:
        body = (f'<div style="font-size:20px;font-weight:bold;">★ {_esc(pick.combo)}</div>'
                f'<div style="font-size:12px;color:{MUTED};line-height:1.6;">'
                f'{_esc(pick.label)}<br>{_esc(pick.stat_text())}</div>')
    else:
        body = (f'<div style="font-size:16px;font-weight:bold;">見送り推奨</div>'
                f'<div style="font-size:12px;color:{MUTED};line-height:1.6;">'
                f'参考 {_esc(pick.combo)}（{_esc(pick.label)}）<br>'
                f'{_esc(pick.reason)}<br>{_esc(pick.stat_text())}</div>')
    parts.append(_section("ワイド1点", body))

    parts.append(_section("スコア順", "".join(
        _horse_block(i, m, top_score, exp) for i, m in enumerate(marked[:n_show], 1))))

    marked_umaban = {m.score.horse.umaban for m in marked}
    rest = [s for s in sorted(scores, key=lambda s: s.total_yoi, reverse=True)
            if s.horse.umaban not in marked_umaban]
    if rest:
        parts.append(
            f'<div style="font-size:12px;color:{MUTED};margin-top:8px;line-height:1.7;">'
            f'参考(印なし): '
            + "  ".join(f"{s.horse.umaban} {_esc(s.horse.name)}" for s in rest[:5])
            + "</div>")

    cand = "<br>".join(
        f'<span style="color:{MUTED}">{w}頭</span> '
        f'<b>{"-".join(str(u) for u in order[:w])}</b>'
        for w in (3, 4, 5, 6) if len(order) >= w)
    parts.append(_section("候補（スコア順の馬番）",
                          f'<div style="font-size:14px;line-height:1.9">{cand}</div>'))

    # 買い目は**推奨だけ組み合わせを並べ、他は1行の要約**にする。
    # 8通り全部の組み合わせを出すと記事が10万字級になり、スマホでは
    # スクロールだけで終わってしまう。幅を広げたい人には数字を添える
    rec = ("ワイド", 3) if plan.wide else ("馬連", 4)
    options = [o for o in build_options(order, favorite_odds=fav, recommended=rec)
               if o.width in (3, 4, 5, 6)]
    buys = []
    for o in options:
        if not o.recommended:
            continue
        st = o.stats
        stat = (f"的中{st['的中率']:.0%}・回収{st['回収率']:.0%}・黒字{st['黒字確率']:.0%}"
                if st else "実測データなし")
        buys.append(
            f'<div style="background:{PANEL};padding:10px 12px;border-radius:6px;">'
            f'<div style="font-size:15px;font-weight:bold;">'
            f'★ {_esc(o.kind)} {o.width}頭BOX {o.points}点</div>'
            f'<div style="font-size:12px;color:{MUTED};margin:2px 0 6px;">{stat}</div>'
            f'<div style="font-size:14px;word-break:break-all;line-height:1.9;">'
            + "　".join(f"{a}-{b}" for a, b in o.combos) + "</div></div>")
    rows = []
    for o in options:
        if o.recommended:
            continue
        st = o.stats
        stat = (f"的中{st['的中率']:.0%}／回収{st['回収率']:.0%}／黒字{st['黒字確率']:.0%}"
                if st else "実測なし")
        rows.append(f"{o.kind}{o.width}頭 {o.points}点　{stat}")
    if rows:
        buys.append(
            f'<div style="margin-top:10px;font-size:12px;color:{MUTED};line-height:1.9">'
            f'幅を広げる場合の実測値（馬番は上の候補から）<br>'
            + "<br>".join(rows) + "</div>")
    parts.append(_section("買い目（★=推奨）", "".join(buys)))
    parts.append("</div>")
    return "".join(parts)


DEFAULT_NOTE = ("回収率・黒字確率は収集済みレースの実測値です。"
                "馬券は必ずご自身の判断でお願いします。")


def format_day_html(blocks: list[str], heading: str, note: str = "") -> str:
    """1日ぶんをまとめる。先頭に見出し、末尾に注意書き。"""
    head = (f'<div style="{BASE}max-width:640px;margin:0 auto;">'
            f'<div style="font-size:20px;font-weight:bold;line-height:1.5;'
            f'margin-bottom:20px;">{_esc(heading)}</div>')
    tail = (f'<div style="margin:24px 0 0;font-size:11px;color:{MUTED};'
            f'line-height:1.8;border-top:1px solid {LINE};padding-top:10px;">'
            f'{_esc(note or DEFAULT_NOTE)}</div></div>')
    return head + "".join(blocks) + tail


def fits_ameba(html: str) -> tuple[bool, int]:
    """アメブロの本文上限に収まるか。(収まるか, 文字数) を返す。

    上限は半角60,000文字で、**HTMLタグを含めて**数えられる。さらに投稿時の
    自動整形で増えることがあるため、判定は余白を取った SAFE_LIMIT で行う。
    """
    n = len(html)
    return n <= SAFE_LIMIT, n


# ---------------------------------------------------------------------------
# テキスト版（HTMLを使わずに貼る場合）
# ---------------------------------------------------------------------------
# ブログの本文は**等幅フォントではない**。cli text の桁揃え（半角スペースで
# 列を合わせる形式）はターミナルやメモ帳では読めるが、ブログに貼ると列が
# 崩れて読めなくなる。そこで貼り付け用のテキストは
#   - 桁揃えに頼らない（1項目1行、または全角スペース区切り）
#   - スマホの1行に収まる幅（全角26字程度）に抑える
# という別のレイアウトにする。

TXT_RULE = "━" * 13          # 全角13字ぶん。スマホの1行に収まる
TXT_THIN = "─" * 13


def _txt_section(title: str) -> str:
    return f"\n【{title}】"


def _txt_width(text: str) -> int:
    """全角を2、半角を1として数える。スマホの折り返し位置の目安にする。"""
    return sum(2 if ord(c) > 0x2000 else 1 for c in text)


def _chunk(token: str, limit: int) -> list[str]:
    """空白の無い長い文字列（日本語の文など）を幅で切る。"""
    out, cur = [], ""
    for ch in token:
        if _txt_width(cur + ch) > limit and cur:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def _wrap_tokens(text: str, limit: int = 34) -> list[str]:
    """スマホの1行に収まる幅で折り返す。

    ブログはプロポーショナルフォントなので桁揃えはできないが、
    1行が長すぎると勝手に折り返されて読みにくくなる。ここで区切る。
    空白で切れない日本語の文は文字数で切る。
    """
    lines: list[str] = []
    cur = ""
    for token in text.split():
        if _txt_width(token) > limit:
            # 単独で幅を超えるトークン（日本語の文など）は文字で切る
            if cur:
                lines.append(cur)
                cur = ""
            pieces = _chunk(token, limit)
            lines.extend(pieces[:-1])
            cur = pieces[-1]
            continue
        cand = f"{cur} {token}".strip()
        if cur and _txt_width(cand) > limit:
            lines.append(cur)
            cur = token
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def format_race_text(
    title: str,
    surface: str,
    post_time: str,
    marked: list[MarkedHorse],
    scores: list[HorseScore],
    plan: BettingPlan,
    exp: Expectation | None = None,
    n_show: int = 8,
) -> str:
    """1レース分のテキスト。ブログの通常エディタにそのまま貼れる。"""
    exp = exp if exp is not None else Expectation()
    fav = plan.favorite_odds
    order = [m.score.horse.umaban for m in marked]
    fav_umaban = next((s.horse.umaban for s in scores if s.horse.ninki == 1), None)
    agree = fav_umaban is not None and order and order[0] == fav_umaban

    out = [TXT_RULE, title]
    if surface or post_time:
        out.append(f"{surface}{'  発走' + post_time if post_time else ''}")
    out.append(f"1番人気 {f'{fav:.1f}倍' if fav else 'オッズ不明'} → {plan.strategy}型")
    out.append(f"◎と1番人気: {'一致' if agree else '不一致'}")

    pick = best_single(order, favorite_odds=fav)
    out.append(_txt_section("ワイド1点"))
    if pick is None:
        out.append("実測データなし → 判断材料なし")
    elif pick.recommended:
        out.append(f"★ {pick.combo}（{pick.label}）")
        out.extend(_wrap_tokens(pick.stat_text()))
    else:
        out.append("見送り推奨")
        out.append(f"参考 {pick.combo}（{pick.label}）")
        out.extend(_wrap_tokens(pick.reason))
        out.extend(_wrap_tokens(pick.stat_text()))

    out.append(_txt_section("スコア順"))
    for i, m in enumerate(marked[:n_show], start=1):
        h = m.score.horse
        out.append(f"{m.mark} {h.umaban} {h.name}　{m.score.total_yoi:.1f}点")
        # スマホの1行（全角17字ぶん）に収めるため、区切りは「 / 」ではなく
        # 空白1つにし、「番人気」も「人気」に詰める
        bits = [f"{h.ninki}人気" if h.ninki else "人気—",
                f"{h.tansho_odds:.1f}倍" if h.tansho_odds else "オッズ—",
                h.kyakushitsu or "脚質—"]
        win, place = exp.format(i)
        if not (win == "—" and place == "—"):
            bits.append(f"1着{win} 着内{place}")
        out.append("　" + " ".join(bits))

    marked_umaban = {m.score.horse.umaban for m in marked}
    rest = [s for s in sorted(scores, key=lambda s: s.total_yoi, reverse=True)
            if s.horse.umaban not in marked_umaban]
    if rest:
        out.append("参考(印なし)")
        for line in _wrap_tokens(
                " ".join(f"{s.horse.umaban}{s.horse.name}" for s in rest[:5]), 32):
            out.append("　" + line)

    out.append(_txt_section("候補（スコア順の馬番）"))
    for w in (3, 4, 5, 6):
        if len(order) >= w:
            out.append(f"{w}頭　" + "-".join(str(u) for u in order[:w]))

    rec = ("ワイド", 3) if plan.wide else ("馬連", 4)
    options = [o for o in build_options(order, favorite_odds=fav, recommended=rec)
               if o.width in (3, 4, 5, 6)]
    out.append(_txt_section("買い目"))
    for o in options:
        if not o.recommended:
            continue
        st = o.stats
        out.append(f"★ {o.kind} {o.width}頭BOX {o.points}点")
        for line in _wrap_tokens(" ".join(f"{a}-{b}" for a, b in o.combos), 24):
            out.append("　" + line.replace(" ", "　"))
        if st:
            out.append(f"　的中{st['的中率']:.0%}／回収{st['回収率']:.0%}"
                       f"／黒字{st['黒字確率']:.0%}")
    others = []
    for o in options:
        if o.recommended:
            continue
        st = o.stats
        # 1行に収めるため、見出しで項目名を示して値だけ並べる
        stat = (f"{st['的中率']:.0%}/{st['回収率']:.0%}/{st['黒字確率']:.0%}"
                if st else "実測なし")
        others.append(f"{o.kind}{o.width}頭 {o.points}点　{stat}")
    if others:
        out.append(TXT_THIN)
        out.append("幅を広げる場合（的中/回収/黒字）")
        out.extend(others)
    return "\n".join(out)


def format_day_text(blocks: list[str], heading: str, note: str = "") -> str:
    body = "\n\n".join(blocks)
    return f"{heading}\n\n{body}\n\n{TXT_RULE}\n{note or DEFAULT_NOTE}\n"
