"""コース特性ごとの適性を、馬の全キャリアから読んで表示用にまとめる。

## 点数に入れず表示だけにしている理由

特性で束ねると母数は3倍になる（同じ競馬場17.6% → 同じ小回り53.8%）が、
`scripts/course_traits.py` で同一人気帯内のリフトを測ったところ、
5軸×4人気帯=20区分のうち19区分で2025年と2026年の符号が反転した。
**判別力が確認できていないものを点数にはしない**（CLAUDE.mdの方針）。

ただし再現しなかった理由はデータ不足である可能性が高い。あの検証は
9-12Rだけを集めた収集データを使っており、1頭の過去走数の中央値が3走
しかなかった。ここで使うのは `keiba.cli horses` で取った**全キャリア**
なので、1頭あたりの母数は比較にならないほど厚い。

そこで、メンバー質差分と同じ2段階のうち第1段階（表示のみ）として出す。
買う人が見て判断でき、かつ実戦の記録が溜まれば第2段階（点数化）の
判定材料になる。

## 「得意」の意味

水準（強い馬か弱い馬か）ではなく、**その馬の中での対比**を出す。
水準は人気が既に織り込んでいるので、測れば必ず市場に負ける
（CLAUDE.md 偏差値化の失敗・相手の質の失敗）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .courses import same_trait_courses, traits
from .horsedb import records_before

# 対比を出すのに必要な、片側あたりの最低出走数。
# 2走だと複勝率が0%/50%/100%の3値しか取らず、適性ではなくノイズを測る
MIN_SIDE = 3

# 表示する軸の順。馬場種別で意味が変わらないものを先に置く
AXES = ("小回り", "坂", "芝種", "回り")


@dataclass
class TraitRecord:
    axis: str
    value: str
    n_match: int
    rate_match: float
    n_other: int
    rate_other: float | None
    courses: list[str]

    @property
    def diff(self) -> float | None:
        """一致側 − 不一致側の複勝率。両側に実績が無ければ None。"""
        if self.rate_other is None:
            return None
        return self.rate_match - self.rate_other

    @property
    def tag(self) -> str:
        d = self.diff
        if d is None:
            return "対比なし"
        if d >= 0.15:
            return "得意"
        if d <= -0.15:
            return "苦手"
        return "差なし"

    def text(self) -> str:
        head = f"{self.value}{self.n_match}走 複{self.rate_match:.0%}"
        if self.rate_other is None:
            return f"{head}（他条件の実績なし→対比不能）"
        return (f"{head} / 他{self.n_other}走 複{self.rate_other:.0%}"
                f" → {self.tag}")


def trait_records(rows: list[dict], venue: str, surface: str | None = None,
                  as_of: date | str | None = None,
                  min_side: int = MIN_SIDE) -> list[TraitRecord]:
    """1頭ぶんの戦績から、軸ごとの適性を返す。

    as_of を渡すとその日より前の戦績だけを使う（後知恵を排除）。
    当日の予想では as_of=None でよい（未来の行はそもそも存在しない）。
    """
    past = records_before(rows, as_of)
    out: list[TraitRecord] = []
    for axis, val in traits(venue, surface).items():
        if axis not in AXES:
            continue
        group = set(same_trait_courses(venue, axis, surface))
        match, other = [], []
        for r in past:
            if not (r.get("着順") or "").isdigit():
                continue
            (match if r["場"] in group else other).append(int(r["着順"]))
        if len(match) < min_side:
            continue
        rate_other = (sum(1 for c in other if c <= 3) / len(other)
                      if len(other) >= min_side else None)
        out.append(TraitRecord(
            axis=axis, value=val, n_match=len(match),
            rate_match=sum(1 for c in match if c <= 3) / len(match),
            n_other=len(other), rate_other=rate_other,
            courses=sorted(group),
        ))
    # 得意・苦手がはっきりしている軸を先に出す
    out.sort(key=lambda t: -abs(t.diff) if t.diff is not None else 0.0)
    return out


def summary_line(rows: list[dict], venue: str, surface: str | None = None,
                 as_of: date | str | None = None, limit: int = 2) -> str:
    """1行で出す短い要約。実績が薄い馬は「データ不足」と明示する。"""
    recs = trait_records(rows, venue, surface, as_of)
    notable = [r for r in recs if r.tag in ("得意", "苦手")][:limit]
    if notable:
        return " ".join(f"{r.axis}={r.tag}({r.diff:+.0%})" for r in notable)
    if recs:
        return f"特性差なし（{recs[0].n_match}走ベース）"
    return "データ不足"
