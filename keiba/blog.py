"""アメーバブログなどに貼り付けるHTMLを作る（スマホ表示優先）。

アメブロには外部から投稿するAPIが無い（AtomPub APIは終了済み）。
そこで**HTML編集モードにそのまま貼れる形**で書き出す。

描画データは `keiba.site.build_payload` と同じものを使う。以前は独自に
組み立てていたため、公開ページ側の方針変更（回収率を載せない、
「気になるワイド」に改称など）が反映されず、**古い文言のまま出続けていた**。
データ源を1つにして、そのズレを起こさないようにする。

アメブロのHTML編集には制約がある:

- `<style>` ブロックや外部CSSは落とされる → **インラインstyleだけで組む**
- `<script>` は通らない → タブや折りたたみは使えない（サイト版とここが違う）
- 記事の表示幅はスマホで概ね 320〜380px → **横に広い表を置かない**
- **本文は半角60,000文字まで。HTMLタグを含めて数える**
- 投稿時の自動整形で文字数が増えることがあるため、安全圏を48,000文字に置く

Ameba Pick が禁じているのは「ギャンブルに関する広告案件」であって、
予想記事の公開そのものではない。ただし他社アフィリエイトは全面禁止。
"""
from __future__ import annotations

AMEBA_LIMIT = 60000
SAFE_LIMIT = 48000

INK = "#222"
MUTED = "#666"
LINE = "#ddd"
PANEL = "#f5f5f5"
SHU = "#c62b23"
BLUE = "#1b4b86"
GREEN = "#1d6b46"
WAKU = {1: ("#fff", "#222"), 2: ("#222", "#fff"), 3: ("#c62b23", "#fff"),
        4: ("#2a5f9e", "#fff"), 5: ("#e0b41f", "#222"), 6: ("#2c7a45", "#fff"),
        7: ("#dd6b1c", "#fff"), 8: ("#e08fa6", "#222")}

BASE = f"font-family:-apple-system,'Hiragino Kaku Gothic ProN',sans-serif;color:{INK};"
DEFAULT_NOTE = ("印は◎本命／○対抗／▲単穴／△押さえ／注警戒。"
                "馬券はご自身の判断でお願いします。")


def _esc(s) -> str:
    return (str(s if s is not None else "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _chip(umaban, waku) -> str:
    bg, fg = WAKU.get(waku if isinstance(waku, int) and 1 <= waku <= 8 else 1)
    return (f'<span style="display:inline-block;min-width:1.5em;padding:1px 3px;'
            f'text-align:center;background:{bg};color:{fg};border:1px solid {LINE};'
            f'font-weight:bold">{_esc(umaban)}</span>')


def format_race_html(race: dict) -> str:
    """1レース分。`build_payload` の races 要素をそのまま受け取る。"""
    p = [f'<div style="margin:0 0 26px">']
    p.append(f'<div style="border-left:3px solid {SHU};padding-left:9px;margin-bottom:9px">'
             f'<div style="font-size:12px;color:{MUTED};letter-spacing:.08em">'
             f'{_esc(race["venue"])} {_esc(race["no"])}</div>'
             f'<div style="font-size:19px;font-weight:bold;line-height:1.35">'
             f'{_esc(race["name"])}</div>'
             f'<div style="font-size:12px;color:{MUTED}">{_esc(race.get("surface", ""))}'
             + (f'　発走{_esc(race["post"])}' if race.get("post") else "") + '</div></div>')

    marked = [h for h in race["horses"] if h.get("mark")]
    rows = "".join(
        f'<div style="padding:5px 0;border-bottom:1px solid {LINE};font-size:15px">'
        f'<span style="color:{SHU};font-weight:bold;display:inline-block;'
        f'min-width:1.4em">{_esc(h["mark"])}</span>'
        f'{_chip(h["umaban"], h.get("waku"))}'
        f'<span style="margin-left:7px">{_esc(h["name"])}</span>'
        f'<span style="float:right;color:{MUTED};font-size:12px">'
        + (f'{h["ninki"]}人気' if h.get("ninki") else "") + '</span></div>'
        for h in marked)
    p.append(f'<div style="margin-bottom:12px">{rows}</div>')

    s = race.get("single")
    if s:
        body = (f'<div style="font-size:26px;font-weight:bold;color:{SHU};'
                f'letter-spacing:.02em">{_esc(s["combo"])}</div>'
                if s.get("rec") else
                f'<div style="font-size:17px;color:{MUTED}">今回は見送り</div>')
        p.append(f'<div style="background:{PANEL};padding:10px 12px;margin-bottom:12px">'
                 f'<div style="font-size:11px;letter-spacing:.16em;color:{MUTED};'
                 f'margin-bottom:3px">気になるワイド</div>{body}'
                 f'<div style="font-size:11px;color:{MUTED};margin-top:3px">'
                 f'{_esc(s.get("label", ""))}</div></div>')

    rec = next((b for b in race.get("boxes", []) if b.get("rec")), None)
    if rec:
        alt = "　".join(f'{_esc(b["kind"])}{b["width"]}頭 {b["points"]}点'
                        for b in race["boxes"] if not b.get("rec"))
        p.append(f'<div style="border:1px solid {SHU};padding:9px 11px;margin-bottom:10px">'
                 f'<div style="font-size:12px;color:{SHU};font-weight:bold;'
                 f'letter-spacing:.1em">買い目　{_esc(rec["kind"])} {rec["width"]}頭BOX '
                 f'{rec["points"]}点</div>'
                 f'<div style="font-size:16px;font-weight:bold;margin-top:5px;'
                 f'line-height:1.8;word-break:break-all">'
                 + "　".join(_esc(c) for c in rec["combos"]) + '</div>'
                 + (f'<div style="font-size:11px;color:{MUTED};margin-top:7px;'
                    f'line-height:1.7">広げる場合　{alt}</div>' if alt else "")
                 + '</div>')

    rest = [h for h in race["horses"] if not h.get("mark")]
    if rest:
        p.append(f'<div style="font-size:11px;color:{MUTED};line-height:1.9">'
                 f'印なし　'
                 + "　".join(f'{h["umaban"]} {_esc(h["name"])} {h["score"]:.0f}'
                             for h in rest) + '</div>')

    res = race.get("result")
    if res:
        top = "".join(
            f'<div style="padding:4px 0;font-size:14px">'
            f'<span style="color:{MUTED};display:inline-block;min-width:1.6em">'
            f'{t["chaku"]}着</span>'
            f'<span style="color:{SHU};display:inline-block;min-width:1.4em">'
            f'{_esc(t.get("mark") or "")}</span>'
            f'{_chip(t["umaban"], t.get("waku"))}'
            f'<span style="margin-left:7px">{_esc(t["name"])}</span></div>'
            for t in res["top"])
        b = res.get("buy")
        hit = b and b.get("hits")
        judge = (f'{_esc(b["kind"])}{b["width"]}頭BOX '
                 + (f'<span style="color:{SHU};font-weight:bold">的中 '
                    f'{_esc(b["hits"][0]["combo"])} '
                    f'{b["hits"][0]["pay"]:,}円</span>' if hit else
                    f'<span style="color:{MUTED}">不的中</span>')) if b else ""
        p.append(f'<div style="margin-top:12px;border-top:2px solid {INK};padding-top:8px">'
                 f'<div style="font-size:11px;letter-spacing:.16em;color:{MUTED};'
                 f'margin-bottom:4px">結果</div>{top}'
                 + (f'<div style="font-size:13px;margin-top:6px">{judge}</div>'
                    if judge else "") + '</div>')

    p.append("</div>")
    return "".join(p)


def format_day_html(blocks: list[str], date_label: str, note: str = "") -> str:
    """1日ぶんをまとめる。題字と日付、末尾に注意書き。"""
    logo = (f'<div style="font-size:20px;font-weight:bold;font-style:italic;'
            f'letter-spacing:.06em;margin-bottom:2px">'
            f'<span style="color:{BLUE}">POCKET</span> '
            f'<span style="color:{GREEN}">TURF</span> '
            f'<span style="font-size:.62em;font-style:normal;color:#fff;'
            f'background:{BLUE};border-radius:5px;padding:2px 6px;'
            f'letter-spacing:.06em">WEB</span></div>')
    head = (f'<div style="{BASE}max-width:640px;margin:0 auto">'
            f'{logo}'
            f'<div style="border-top:1px solid {INK};border-bottom:1px solid {INK};'
            f'height:3px;margin:8px 0 12px"></div>'
            f'<div style="font-size:23px;font-weight:bold;margin-bottom:18px">'
            f'{_esc(date_label)}</div>')
    tail = (f'<div style="margin-top:20px;border-top:1px solid {LINE};padding-top:9px;'
            f'font-size:11px;color:{MUTED};line-height:1.8">'
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
# テキスト版
# ---------------------------------------------------------------------------
# ブログの本文は**等幅フォントではない**。半角スペースで桁を揃えると、
# ターミナルでは読めてもブログに貼ると崩れる。そこで貼り付け用テキストは
# 1項目1行・桁揃えなしで組み、全角17字（34桁）以内に折り返す。

WRAP = 17  # 全角何字で折り返すか（スマホの1行に収まる幅）


def _wrap(text: str, width: int = WRAP) -> list[str]:
    """全角 width 字で折る。空白で切れない日本語があるため文字数で折る。"""
    out, line = [], ""
    for ch in text:
        line += ch
        if len(line) >= width:
            out.append(line)
            line = ""
    if line:
        out.append(line)
    return out or [""]


def format_race_text(race: dict) -> str:
    """1レース分のテキスト。桁揃えはしない。"""
    L = [f'■ {race["venue"]}{race["no"]} {race["name"]}',
         f'{race.get("surface", "")}'
         + (f'　発走{race["post"]}' if race.get("post") else "")]

    L.append("")
    L.append("【印】")
    for h in race["horses"]:
        if not h.get("mark"):
            continue
        ninki = f"　{h['ninki']}人気" if h.get("ninki") else ""
        L.append(f'{h["mark"]} {h["umaban"]} {h["name"]}{ninki}')

    s = race.get("single")
    if s:
        L.append("")
        L.append("【気になるワイド】")
        L.append(s["combo"] if s.get("rec") else "今回は見送り")
        if s.get("label"):
            L.extend(_wrap(s["label"]))

    rec = next((b for b in race.get("boxes", []) if b.get("rec")), None)
    if rec:
        L.append("")
        L.append(f'【買い目】{rec["kind"]} {rec["width"]}頭BOX {rec["points"]}点')
        # 組み合わせは4つずつ並べる。1行が長くなりすぎないように
        combos = rec["combos"]
        for i in range(0, len(combos), 4):
            L.append("　".join(combos[i:i + 4]))
        alt = [b for b in race["boxes"] if not b.get("rec")]
        if alt:
            L.append("広げる場合")
            for b in alt:
                L.append(f'　{b["kind"]}{b["width"]}頭 {b["points"]}点')

    rest = [h for h in race["horses"] if not h.get("mark")]
    if rest:
        L.append("")
        L.append("【印なし】")
        for h in rest:
            L.append(f'{h["umaban"]} {h["name"]} {h["score"]:.0f}')

    res = race.get("result")
    if res:
        L.append("")
        L.append("【結果】")
        for t in res["top"]:
            L.append(f'{t["chaku"]}着 {t.get("mark") or "－"} {t["umaban"]} {t["name"]}')
        b = res.get("buy")
        if b:
            if b.get("hits"):
                L.append(f'{b["kind"]}{b["width"]}頭BOX 的中')
                L.append(f'　{b["hits"][0]["combo"]}　{b["hits"][0]["pay"]:,}円')
            else:
                L.append(f'{b["kind"]}{b["width"]}頭BOX 不的中')
    return "\n".join(L)


def format_day_text(blocks: list[str], date_label: str, note: str = "") -> str:
    head = f"POCKET TURF WEB\n{date_label}\n"
    tail = "\n" + "\n".join(_wrap(note or DEFAULT_NOTE))
    return head + "\n\n".join(blocks) + "\n" + tail + "\n"
