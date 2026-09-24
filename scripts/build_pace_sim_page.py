#!/usr/bin/env python3
"""G1ペース・シミュレーターのページを作る。

    python3 scripts/build_pace_sim.py          # 先に材料（pace_sim.json）を作る
    python3 scripts/build_pace_sim_page.py     # → output/G1ペースシミュレーター.html

`scripts/pace_sim_template.html` の `__DATA__` に `pace_sim.json` を埋め込むだけ。
描画と実測を分けておくと、収集が増えたら材料だけ作り直せば済む
（`build_jockey_page.py` と同じ作り）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data/profiles/jra/pace_sim.json"))
    ap.add_argument("--template", default=str(ROOT / "scripts/pace_sim_template.html"))
    ap.add_argument("--out", default=str(ROOT / "output/G1ペースシミュレーター.html"))
    a = ap.parse_args()

    data = json.loads(Path(a.data).read_text(encoding="utf-8"))
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # </script> で埋め込みが途切れないように
    blob = blob.replace("</", "<\\/")
    html = Path(a.template).read_text(encoding="utf-8").replace("__DATA__", blob)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"{out}  {len(html.encode('utf-8')):,}バイト・G1 {len(data['G1'])}本")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
