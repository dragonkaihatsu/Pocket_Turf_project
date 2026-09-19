#!/usr/bin/env python3
"""新聞レイアウト（軸／相手／押さえ＋結果・配当）をHTML／PNGで出す。

    python3 scripts/build_shinbun.py --config config/2026-09-20_中央.json \
        --out output/2026-09-20_中央_新聞.html \
        --png output/2026-09-20_中央_新聞.png

**同じコマンドを発走前と発走後の両方で流す。** 結果CSV・配当CSVが
入っているレースだけ自動で色が付く（1着=桃／2着=橙／3着=水色、馬番の
背面に🥇🥈🥉）。入っていないレースは空欄のままで、数字を作らない。

貼り先はアメブロを想定し、禁止タグが1つでも残っていたら終了コード1。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import shinbun

# CLAUDE.md「アメブロに貼るには変換が要る」の禁止タグ
FORBIDDEN = ("html", "head", "body", "iframe", "object", "form", "input",
             "embed", "textarea", "script", "meta", "button", "option",
             "title", "svg", "frame", "frameset", "param")
LIMIT = 60_000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--png")
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--chrome")
    ap.add_argument("--title", help="Artifact用。貼る用には付けない")
    ap.add_argument("--published",
                    help="公表した印の並びJSON {\"中山9R\": [6,2,...]}。"
                         "渡すとスコアで並べ直さず、その並びに結果を塗る")
    a = ap.parse_args()

    with open(a.config, encoding="utf-8-sig") as f:
        config = json.load(f)
    published = shinbun.load_published(a.published) if a.published else None
    page = shinbun.build_sheet(config, title=a.title, published=published)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # BOMは付けない（コピペで先頭にゴミ文字が入るだけ害になる）
    out.write_text(page, encoding="utf-8")

    size = len(page.encode("utf-8"))
    print(f"{out}  {size:,}バイト  上限{LIMIT:,}の{size / LIMIT:.0%}")
    if size > LIMIT:
        print("  ✗ アメブロの本文上限を超えている")
    allowed = {"title"} if a.title else set()      # --title のときだけ許す
    bad = [t for t in FORBIDDEN
           if t not in allowed and re.search(rf"<{t}[\s>/]", page, re.I)]
    if bad:
        print(f"  ✗ 禁止タグが残っている: {', '.join(bad)}")
        return 1
    print("  ✓ 禁止タグなし")

    if a.png:
        from keiba.shot import render_png
        png = Path(a.png)
        render_png(page, png, scale=a.scale, chrome=a.chrome)
        print(f"{png}  {png.stat().st_size:,}バイト")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
