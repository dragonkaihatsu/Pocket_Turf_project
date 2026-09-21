"""ペースと4コーナーの隊列を、収集ゼロで作る2つの指標。

どちらも**結果CSVと通過順CSVだけ**から作れる（追加の取得が要らない）。
ラップ表のキャッシュは68%しか無いが、これらは99%作れる。

## ペース指標

勝ち馬の **前半の1F平均 − 上がり3Fの1F平均** を、同じ(場×芝ダ×距離)の
平均からの残差で持つ。正なら前半が相対的に遅い＝スロー＝前残り寄り。

netkeiba自身の `ペース:S/M/H` と突き合わせて検算した（3,747本）:

    S +0.246 / M +0.004 / H −0.232   ← 完全に単調

## 4コーナーの隊列

netkeibaの通過順表記は**馬身差を記号で持っている**:

    (..) 併走   , 1馬身以内   - 2〜4馬身   = 5馬身以上   * 内めを通った

`parse_corner` は数字だけ拾って記号を捨てていたが、記号が隊列の長さそのもの
である。1頭あたり平均間隔にすると、ペースと単調に動く（5,889レース=99%）:

    ハイ寄り 0.46馬身 / 中間 0.40 / スロー寄り 0.30

**人が読むのは着順だけで、この文字列を数える人はいない。** CLAUDE.mdの
設計原則でいう「組み合わせでしか見えない」側の材料にあたる。
"""
from __future__ import annotations

import re

# netkeiba の通過順表記における馬身換算
GAP = {",": 1.0, "-": 3.0, "=": 6.0}


def parse_corner(s: str, n: int) -> list[int] | None:
    """通過順の1コーナー分（例 "4(11,12)(2,13,7,16)-(3,9,10)5,14(8,15)-1,6"）を
    馬番の並びに変換する。桁が頭数を超えて連結された表記（例"1112"）も1桁ずつに割る。

    頭数と極端にずれる場合は取消・除外の混入を疑い None を返す
    （furi_test.py 由来。複数スクリプトに同じ定義が散っていたため
    `keiba/tenkai.py` に集約した）。
    """
    toks = re.findall(r"\d+", s)
    out: list[int] = []
    for t in toks:
        v = int(t)
        if v <= 18:
            out.append(v)
        else:
            out.extend(int(c) for c in t)
    if len(set(out)) != len(out) or not (n - 2 <= len(out) <= n):
        return None
    return out


def last_corner_ranks(corner_text: str, field_size: int) -> dict[int, int]:
    """最終コーナーの通過順テキストから {馬番: 何番手だったか} を返す。

    読めなければ空dict（欠損として扱う。数字を作らない）。
    """
    order = parse_corner(corner_text, field_size)
    if not order:
        return {}
    return {umaban: rank for rank, umaban in enumerate(order, start=1)}


def field_spread(s: str, min_horses: int = 5) -> tuple[float, int] | None:
    """4コーナーの通過順から (先頭〜最後方の推定馬身差, 頭数) を出す。

    括弧の中は併走なので 0 馬身として数える。頭数が足りなければ None。
    """
    if not s:
        return None
    total, n, depth = 0.0, 0, 0
    for t in re.findall(r"\(|\)|\d+|[,\-=]", s.replace("*", "")):
        if t == "(":
            depth += 1
        elif t == ")":
            depth -= 1
        elif t in GAP:
            if depth == 0:
                total += GAP[t]
        else:
            n += 1
    return (total, n) if n >= min_horses else None


def spread_per_horse(s: str, min_horses: int = 5) -> float | None:
    """1頭あたりの平均間隔（馬身）。頭数の違いを吸収するため割る。"""
    got = field_spread(s, min_horses)
    if not got:
        return None
    total, n = got
    return total / (n - 1) if n > 1 else None


def pace_raw(sec: float, agari_3f: float, kyori: int) -> float | None:
    """勝ち馬の走破タイムと上がり3Fから、素のペース指標を出す。

    正なら前半の1Fが上がりの1Fより遅い＝スロー寄り。
    **距離が長いほど前半平均は遅く出る**ので、必ず同じ
    (場×芝ダ×距離)の平均からの残差にして使う（生の値を帯に切らない）。
    """
    if sec is None or agari_3f is None or kyori <= 600 or sec <= agari_3f:
        return None
    return (sec - agari_3f) / ((kyori - 600) / 200.0) - agari_3f / 3.0
