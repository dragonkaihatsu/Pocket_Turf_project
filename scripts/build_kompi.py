#!/usr/bin/env python3
"""コンピ指数風の一覧表を設定JSONから組む。

    python3 scripts/build_kompi.py --config config/2026-09-13_中央.json \
        --out data/2026-09-13_指数表.html

既定の出力は**アメブロにそのまま貼れる**（禁止タグを1つも使わず、CSSは
`.kompi` の下にスコープ）。Artifact で見るときだけ `--title` を付ける
（`<title>` はアメブロの禁止タグなので、貼る用には付けない）。

`--metric hensachi` でセルの数字をレース内偏差値に切り替える。既定は
スコア素点（75点満点）で、`daily` のカードに出る数字と一致する。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.kompi import build_sheet, load_calibration

# アメブロで使えないタグ（CLAUDE.md「アメブロに貼るには変換が要る」）
FORBIDDEN = ("html", "head", "body", "frame", "frameset", "iframe", "object",
             "param", "server", "javascript", "form", "input", "embed",
             "textarea", "script", "meta", "button", "option", "title", "svg")
LIMIT = 60_000      # アメブロ本文の上限（半角60,000文字＝バイト）


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--calibration",
                    default="data/profiles/jra/calibration.json")
    ap.add_argument("--metric", choices=("score", "hensachi"), default="score")
    ap.add_argument("--title", default=None,
                    help="Artifact用に<title>を足す。貼る用には付けない")
    a = ap.parse_args()

    with open(a.config, encoding="utf-8-sig") as f:
        config = json.load(f)
    cal = load_calibration(a.calibration)
    if cal is None:
        print(f"※ 実測表が無いので最下段を出さない: {a.calibration}")

    sheet = build_sheet(config, cal, metric=a.metric, title=a.title)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 貼る用はBOMを付けない（コピペで先頭にゴミ文字が入るだけ害になる）
    out.write_text(sheet, encoding="utf-8")

    size = len(sheet.encode("utf-8"))
    print(f"{out}  {size:,}バイト  上限{LIMIT:,}の{size / LIMIT:.0%}")
    if a.title:
        print("  ※ --title を付けたのでArtifact用。アメブロには貼れない")
        return 0
    bad = [t for t in FORBIDDEN if f"<{t}" in sheet.lower()]
    if bad:
        print(f"  ✗ 禁止タグが残っている: {', '.join(bad)}")
        return 1
    print("  ✓ 禁止タグなし" + ("" if size <= LIMIT else "  ✗ 上限オーバー"))
    return 0 if size <= LIMIT else 1


if __name__ == "__main__":
    raise SystemExit(main())
