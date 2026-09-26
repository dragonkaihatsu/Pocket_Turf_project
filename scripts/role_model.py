#!/usr/bin/env python3
"""1日1万円のロールモデルの買い目を出す（中身は `keiba/rolemodel.py`）。

    python3 scripts/role_model.py --config config/2026-09-27_中央.json \
        --published data/2026-09-27_中央_公表印.json \
        --out output/2026-09-27_中央_ロールモデル.txt

--published を渡すと公表した印の並びの上位4頭を使う（公表版と買い目を揃える）。
渡さなければスコアから作る（新聞と同じ採点経路）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba import rolemodel, shinbun  # noqa: E402


def tops_from_scores(config: dict) -> dict[str, list[int]]:
    by_name = shinbun.load_by_name(None, shinbun.config_venue(config))
    as_of = shinbun.config_date(config)
    out = {}
    for r in config["races"]:
        if rolemodel.race_number(r) not in rolemodel.RACES:
            continue
        row = shinbun.race_row(r, by_name, as_of)
        out[shinbun.published_key(r)] = [c.umaban for c in row.cells]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--published")
    ap.add_argument("--out")
    a = ap.parse_args()

    with open(a.config, encoding="utf-8-sig") as f:
        config = json.load(f)
    tops = (shinbun.load_published(a.published) if a.published
            else tops_from_scores(config))
    src = "印は公表版" if a.published else "印はスコアから作成"
    text = rolemodel.format_day(rolemodel.plan_day(config, tops),
                                heading=f"{config.get('title', '')}（{src}）")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding="utf-8-sig")
        print(f"書き出し: {a.out}")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
