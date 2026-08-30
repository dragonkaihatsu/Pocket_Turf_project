"""ペース別展開予想（CLAUDE.md 出力形式の3番目）。

出走馬CSVの拡張カラム「脚質」（逃げ/先行/差し/追込）を集計し、
ハイ/ミドル/スローの発生確率と、各ペースで浮上しやすい脚質・馬を返す。
脚質データが無い馬は集計から除外し、その旨をコメントする。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Horse

STYLES = ("逃げ", "先行", "差し", "追込")


@dataclass
class PaceForecast:
    counts: dict[str, int]
    unknown: int
    probabilities: dict[str, float]  # {"ハイ":.., "ミドル":.., "スロー":..}
    favored: dict[str, list[Horse]]  # ペースごとに浮上しやすい馬
    note: str


def forecast_pace(horses: list[Horse]) -> PaceForecast:
    counts = {s: 0 for s in STYLES}
    unknown = 0
    for h in horses:
        if h.kyakushitsu in counts:
            counts[h.kyakushitsu] += 1
        else:
            unknown += 1

    nige, senko = counts["逃げ"], counts["先行"]

    if nige >= 2:
        probs = {"ハイ": 0.55, "ミドル": 0.35, "スロー": 0.10}
        note = f"逃げ馬{nige}頭でハイペース濃厚。先行争いの消耗を突く差し・追込に注意。"
    elif nige == 1 and senko <= 2:
        probs = {"ハイ": 0.15, "ミドル": 0.40, "スロー": 0.45}
        note = "逃げ馬1頭・先行薄でスローペースの可能性。前残りに注意。"
    elif nige == 1:
        probs = {"ハイ": 0.30, "ミドル": 0.50, "スロー": 0.20}
        note = "逃げ馬1頭・先行争いは中程度でミドルペース想定。"
    else:
        probs = {"ハイ": 0.10, "ミドル": 0.35, "スロー": 0.55}
        note = "逃げ馬不在でスローペース濃厚。前有利の展開に注意。"

    favored = {
        "ハイ": [h for h in horses if h.kyakushitsu in ("差し", "追込")],
        "ミドル": [h for h in horses if h.kyakushitsu != ""],
        "スロー": [h for h in horses if h.kyakushitsu in ("逃げ", "先行")],
    }

    if unknown:
        note += f"（脚質未入力{unknown}頭は集計から除外）"

    return PaceForecast(counts=counts, unknown=unknown, probabilities=probs, favored=favored, note=note)
