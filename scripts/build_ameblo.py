#!/usr/bin/env python3
"""予想HTMLをアメブロの記事に貼れる形へ変換する。

## なぜ変換が要るのか

`keiba.cli daily` が出すHTMLは**そのままでは貼れない**。アメブロには

1. **禁止タグ**がある（html / head / body / script / meta / button / svg /
   iframe / form / input / textarea / embed / object など）。含んでいると
   「禁止タグが含まれています」で投稿できない
2. **記事本文の上限が60,000バイト（HTMLタグ込み）**。予想HTML1日分は
   約290KBあり、**4.8倍オーバー**する

なので (a) 禁止タグを落とし、(b) レースごとに分割する。

## 落とすと何が失われるか

タブ（9R/10R/…の切り替え）と並び順トグル（馬番順/スコア順）は `<button>` と
`<script>` でできているので**両方とも消える**。代わりに:

- タブ → レースごとに別記事にするので不要
- 並び順 → **スコア順に並べ替えて出す**。JSが無いときの既定は馬番順だが、
  予想として読むならスコア順のほうが有用なので、変換時に並べ替える

タップ展開は `<details>`/`<summary>` で、これは禁止タグではなくJSも要らない
ので**そのまま動く**。

## CSSはスコープする

`<style>` は禁止タグではないが、`:root` や `body` をそのまま書くと
**アメブロ側のページCSSと衝突する**（記事の外まで色が変わる）。全セレクタを
`.kb` の下に入れ直す。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# アメブロの禁止タグ。記事本文・メッセージボード・フリースペース・自己紹介で
# 使えない。title は自己紹介でのみ可なので記事では禁止側に置く
PROHIBITED = [
    "html", "head", "body", "frame", "frameset", "iframe", "object", "param",
    "server", "javascript", "form", "input", "embed", "textarea", "script",
    "meta", "button", "option", "title", "svg",
]
LIMIT = 60_000          # 記事本文の上限（バイト・HTMLタグ込み）
WRAP = "kb"             # CSSのスコープに使うクラス名


def strip_block(html: str, tag: str) -> str:
    """`<tag ...>...</tag>` を中身ごと落とす。"""
    return re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", "", html, flags=re.S | re.I)


def split_top_level(css: str) -> list[tuple[str, str, bool]]:
    """スタイルシートを (前置き, 中身, @ルールか) に分ける。

    波括弧を数えるだけの素朴な走査。`@media` の中にさらにルールが入るので
    入れ子を扱う必要があり、正規表現では書けない。
    """
    out, i, n = [], 0, len(css)
    while i < n:
        brace = css.find("{", i)
        if brace < 0:
            break
        head = css[i:brace]
        depth, j = 1, brace + 1
        while j < n and depth:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        out.append((head, css[brace + 1:j - 1], head.lstrip().startswith("@")))
        i = j
    return out


def scope_selector(sel: str) -> str:
    """セレクタを `.kb` の下に入れる。

    `:root` と `body` は**置き換える**（`.kb :root` は何にも当たらない）。
    `*` は子孫にしないと全ページに当たる。
    """
    parts = []
    for s in sel.split(","):
        s = s.strip()
        if not s or s.startswith("/*"):
            continue
        if s in (":root", "html", "body", "html body"):
            parts.append(f".{WRAP}")
        elif s == "*":
            parts.append(f".{WRAP}, .{WRAP} *")
        else:
            parts.append(f".{WRAP} {s}")
    return ", ".join(parts)


def scope_css(css: str) -> str:
    """スタイルシート全体をスコープする。@ルールは中身を再帰的に処理する。"""
    out = []
    for head, body, is_at in split_top_level(css):
        comment = ""
        m = re.match(r"\s*((?:/\*.*?\*/\s*)*)(.*)", head, re.S)
        if m:
            comment, head = m.group(1).strip(), m.group(2)
        if comment:
            out.append(comment)
        if is_at:
            # @media / @supports は中身にセレクタが入る。@keyframes は入らない
            inner = body if head.lstrip().startswith("@keyframes") else scope_css(body)
            out.append(f"{head.strip()}{{{inner}}}")
        else:
            out.append(f"{scope_selector(head)}{{{body.strip()}}}")
    return "\n".join(out)


def sort_cards_by_score(section: str) -> str:
    """馬のカードをスコア順に並べ替える。

    JSが無いと既定の馬番順のままになる。予想として読むならスコア順が
    有用なので、貼る前に並べ替えてしまう。
    """
    m = re.search(r'(<div class="cards"[^>]*>)(.*?)(</div>\s*)(?=<(?:div|section|/section))',
                  section, re.S)
    if not m:
        return section
    cards = re.findall(r'<details\b.*?</details>', m.group(2), re.S)
    if len(cards) < 2:
        return section

    def score(c: str) -> float:
        s = re.search(r'data-score="([-\d.]+)"', c)
        return float(s.group(1)) if s else -1e9

    cards.sort(key=score, reverse=True)
    return section[:m.start(2)] + "".join(cards) + section[m.end(2):]


def drop_breakdown(section: str) -> str:
    """配点内訳（タップ展開の中身）を落とす。

    **内訳は本文の82%を占める**（実測: 1頭あたり2,118バイト × 出走頭数）。
    場ごとに4レースまとめると内訳込みで約145,000バイトになり、上限
    60,000バイトの2.4倍。落とせば約33,000バイトに収まる。

    ただしCLAUDE.mdは「スコア算出根拠（内訳）は必ず馬ごとに表示し、
    ブラックボックス化しない」と定めている。**落とすのは方針との
    トレードオフ**なので、既定にはしない（`--no-breakdown` を明示する）。
    """
    section = re.sub(r'<div class="bd">.*?</div>\s*(?=</details>)', "",
                     section, flags=re.S)
    # 中身が無くなった details は、開いても何も出ないので div に落とす
    section = re.sub(r"<details\b([^>]*)>\s*<summary>(.*?)</summary>\s*</details>",
                     r'<div class="card"\1>\2</div>', section, flags=re.S)
    return section


def check_prohibited(html: str) -> list[str]:
    """残っている禁止タグ。1つでもあれば投稿できないので必ず通す。"""
    return [t for t in PROHIBITED if re.search(rf"<{t}\b", html, re.I)]


def convert(html: str, venues: list[str], drop_bd: bool = False
            ) -> tuple[str, list[tuple[str, str]]]:
    """(スコープ済みCSS, [(レース名, 本文HTML)]) を返す。"""
    css_m = re.search(r"<style>(.*?)</style>", html, re.S)
    css = scope_css(css_m.group(1)) if css_m else ""

    for tag in ("script", "style", "title"):
        html = strip_block(html, tag)
    html = re.sub(r'<nav class="tabs".*?</nav>', "", html, flags=re.S)
    html = re.sub(r'<div class="toolbar">.*?</div>\s*(?=<div class="cards")',
                  "", html, flags=re.S)

    sections = re.findall(r'<section class="race"[^>]*>.*?</section>', html, re.S)
    races = []
    for i, sec in enumerate(sections):
        sec = sec.replace(" hidden", "")
        sec = sort_cards_by_score(sec)
        if drop_bd:
            sec = drop_breakdown(sec)
        rno = re.search(r'<span class="rno">([^<]+)</span>', sec)
        name = re.search(r"<h2>([^<]+)</h2>", sec)
        venue = venues[i] if i < len(venues) else ""
        label = f"{venue}{rno.group(1) if rno else i + 1}"
        if name:
            label += f" {name.group(1)}"
        races.append((label, sec))
    return css, races


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True, help="keiba.cli daily が出したHTML")
    ap.add_argument("--config", help="競馬場名を取るための設定JSON")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--limit", type=int, default=LIMIT)
    ap.add_argument("--split", choices=["race", "venue"], default="race",
                    help="race=レースごと1記事 / venue=競馬場ごと1記事")
    ap.add_argument("--as-text", action="store_true", default=True,
                    help="貼り付け用に .txt でも出す（既定で出す）")
    ap.add_argument("--no-breakdown", action="store_true",
                    help="配点内訳を落とす（本文の82%%。venue分割はこれが無いと入らない）")
    args = ap.parse_args()

    html = Path(args.html).read_text(encoding="utf-8-sig")
    venues = []
    if args.config:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
        venues = [r.get("venue", "") for r in cfg.get("races", [])]

    css, races = convert(html, venues, drop_bd=args.no_breakdown)

    if args.split == "venue":
        grouped: dict[str, list[str]] = {}
        for label, sec in races:
            v = re.match(r"[^\d]+", label)
            grouped.setdefault(v.group(0).strip() if v else "", []).append(sec)
        races = [(v, "".join(secs)) for v, secs in grouped.items()]
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"CSS {len(css.encode()):,}バイト / {len(races)}レース")
    print(f"{'ファイル':<34}{'バイト':>10}  判定")
    bad_total = 0
    for i, (label, sec) in enumerate(races, 1):
        doc = f'<style>\n{css}\n</style>\n<div class="{WRAP}">{sec}</div>\n'
        bad = check_prohibited(doc)
        name = re.sub(r"[^\w一-龥ぁ-んァ-ヴー]+", "_", label).strip("_")
        p = outdir / f"{i:02d}_{name}.html"
        # アメブロはコピペで貼る。BOMを付けると先頭にゴミ文字が入るので付けない
        p.write_text(doc, encoding="utf-8")
        if args.as_text:
            # **貼るのに要るのはソースそのもの**。`.html` で渡すと開いたときに
            # 描画されてしまい、コピーできるのは「見た目」であってタグではない。
            # さらにこの断片は `<meta charset>` を入れられない（禁止タグ）ので、
            # ローカルで直接開くと文字コードが判定できず日本語が化ける。
            # `.txt` なら中身がそのまま出て、全選択→コピーで貼れる。
            # こちらは**BOMを付ける**（Windowsのメモ帳が化けないため。
            # 全選択のコピーにBOMは含まれないので貼り付け先には入らない）
            p.with_suffix(".txt").write_text(doc, encoding="utf-8-sig")
        size = len(doc.encode())
        tag = "OK" if size <= args.limit and not bad else ""
        if bad:
            tag = f"✗ 禁止タグ {' '.join(bad)}"
            bad_total += 1
        elif size > args.limit:
            tag = f"✗ {size - args.limit:,}バイト超過"
            bad_total += 1
        print(f"  {p.name:<32}{size:>10,}  {tag}")

    print(f"\n上限 {args.limit:,}バイト（HTMLタグ込み）。"
          "貼るときはアメブロの「HTML表示」に切り替えて全文を貼る")
    if bad_total:
        print(f"! {bad_total}件が貼れない状態")
    sys.exit(1 if bad_total else 0)


if __name__ == "__main__":
    main()
