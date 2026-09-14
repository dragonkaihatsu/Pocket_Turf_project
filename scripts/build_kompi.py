#!/usr/bin/env python3
"""コンピ指数風の一覧表を設定JSONから組む。

    python3 scripts/build_kompi.py --config config/2026-09-13_中央.json \
        --out output/2026-09-13_中央_指数表.html \
        --png output/2026-09-13_中央_指数表.png

既定の出力は**アメブロにそのまま貼れる**（禁止タグを1つも使わず、CSSは
`.kompi` の下にスコープ）。Artifact で見るときだけ `--title` を付ける
（`<title>` はアメブロの禁止タグなので、貼る用には付けない）。

`--png` は同じ表を画像で書き出す（貼り先がHTMLを受けないとき用）。
`--metric hensachi` でセルの数字をレース内偏差値に切り替える。既定は
スコア素点（75点満点）で、`daily` のカードに出る数字と一致する。

**最下段の実測（順位別の勝率・複勝率）は既定で出さない。** 本人の指示
「勝率は入れないでいいです あくまで参考」。付けるときだけ `--rates`。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.kompi import build_sheet, load_calibration
from keiba.shot import render_png

# アメブロで使えないタグ（CLAUDE.md「アメブロに貼るには変換が要る」）
FORBIDDEN = ("html", "head", "body", "frame", "frameset", "iframe", "object",
             "param", "server", "javascript", "form", "input", "embed",
             "textarea", "script", "meta", "button", "option", "title", "svg")
LIMIT = 60_000      # アメブロ本文の上限（半角60,000文字＝バイト）


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", help="貼る用のHTML（省略可・--pngだけでもよい）")
    ap.add_argument("--png", help="同じ表を画像で書き出す")
    ap.add_argument("--scale", type=int, default=2, help="PNGの倍率（既定2）")
    ap.add_argument("--chrome", default=None, help="PNGを撮る実行ファイル")
    ap.add_argument("--rates", action="store_true",
                    help="最下段に順位別の実測（勝率・複勝率）を付ける")
    ap.add_argument("--calibration",
                    default="data/profiles/jra/calibration.json")
    ap.add_argument("--metric", choices=("score", "hensachi"), default="score")
    ap.add_argument("--title", default=None,
                    help="Artifact用に<title>を足す。貼る用には付けない")
    a = ap.parse_args()
    if not (a.out or a.png):
        ap.error("--out か --png のどちらかは指定する")

    with open(a.config, encoding="utf-8-sig") as f:
        config = json.load(f)
    cal = None
    if a.rates:
        cal = load_calibration(a.calibration)
        if cal is None:
            print(f"※ 実測表が無いので最下段を出さない: {a.calibration}")

    sheet = build_sheet(config, cal, metric=a.metric, title=a.title)
    rc = 0
    if a.out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        # 貼る用はBOMを付けない（コピペで先頭にゴミ文字が入るだけ害になる）
        out.write_text(sheet, encoding="utf-8")
        size = len(sheet.encode("utf-8"))
        print(f"{out}  {size:,}バイト  上限{LIMIT:,}の{size / LIMIT:.0%}")
        if a.title:
            print("  ※ --title を付けたのでArtifact用。アメブロには貼れない")
        else:
            bad = [t for t in FORBIDDEN if f"<{t}" in sheet.lower()]
            if bad:
                print(f"  ✗ 禁止タグが残っている: {', '.join(bad)}")
                rc = 1
            else:
                print("  ✓ 禁止タグなし"
                      + ("" if size <= LIMIT else "  ✗ 上限オーバー"))
            if size > LIMIT:
                rc = 1

    if a.png:
        # 画像には <title> を入れず、外部フォントも読まない（取得を待たない）
        body = build_sheet(config, cal, metric=a.metric)
        w, h = render_png(body, a.png, scale=a.scale, chrome=a.chrome)
        p = Path(a.png)
        print(f"{p}  {w}×{h}px ×{a.scale}  {p.stat().st_size:,}バイト")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
