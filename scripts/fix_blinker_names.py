#!/usr/bin/env python3
"""収集済み出走馬CSVの馬名から、ブリンカー記号「 B」を別列へ移す。

netkeibaの馬柱では、ブリンカー着用馬の馬名末尾に「 B」が付く。一方
**結果ページ側には付かない**。そのため馬名を突き合わせキーにしている
処理が、B着用馬だけ静かに失敗していた:

    keiba/scoring.py  records.get(horse.name, [])  → 空
      → コース適性・距離適性が中立値へ落ちる（該当4,022行）

収集側（keiba/collect.py）は修正済み。これは既存データの移行用。
安全のため、変換後に「馬名が空になった」「行数が変わった」場合は
そのファイルを書き戻さない。

    python3 scripts/fix_blinker_names.py --dir data/collected_jra --apply
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def fix_file(path: Path, apply: bool) -> int:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields or "馬名" not in fields:
        return 0

    changed = 0
    for r in rows:
        name = (r.get("馬名") or "").strip()
        if name.endswith(" B"):
            stripped = name[:-2].strip()
            if not stripped:          # 馬名が消えるなら触らない
                continue
            r["馬名"] = stripped
            r["ブリンカー"] = "B"
            changed += 1
    if not changed or not apply:
        return changed

    if "ブリンカー" not in fields:
        fields.append("ブリンカー")
    for r in rows:
        r.setdefault("ブリンカー", "")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return changed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", action="append", required=True,
                    help="対象ディレクトリ（複数指定可）")
    ap.add_argument("--apply", action="store_true",
                    help="付けないと件数を数えるだけ（既定は dry-run）")
    args = ap.parse_args()

    total = files = 0
    for d in args.dir:
        for p in sorted(Path(d).glob("*_出走馬.csv")):
            n = fix_file(p, args.apply)
            if n:
                total += n
                files += 1
    verb = "修正" if args.apply else "検出（dry-run）"
    print(f"{verb}: {total:,}行 / {files:,}ファイル")


if __name__ == "__main__":
    main()
