"""メンバー質の差分（相手弱化・相手強化）を予想時に出す。

## なぜ差分なのか

先に検証した「前走で負けた相手の質」は**水準**を測っており、水準は
レース名＝クラスから読めるので市場に織り込まれていた（同一人気帯内で
逆転した）。ここで測るのは

    差分 = 前走のメンバー質 − 今走のメンバー質     正なら相手弱化

**クラス名は新聞に載るが、「同じ3勝クラスでも中身が濃いか薄いか」は
載らない。** 2レースの出走馬全員を突き合わせて初めて見える量なので、
設計原則の「組み合わせでしか見えない」側に当たる。

## 独立検証を通っている条件だけを意味づける

`scripts/aite_delta.py` で測った結果、**連続値としてそのまま使うのは誤り**
だった（相手弱化(大)と相手強化(大)がほぼ並ぶ。強化側には「格上げ挑戦でも
力がある馬」が混ざる）。両期間で再現したのは前走着順との組み合わせだけ:

    前走二桁 × 相手弱化   勝率5.1%（相手強化2.7%の約2倍）
    前走1-2着 × 相手強化  勝率11.5%（弱化18.2%から落ちる）

なので `note()` は**その2つに当たるときだけ**踏み込んだ言い方をする。

## スコアには入れない（第1段階＝表示のみ）

判断は買う人に委ねる。CLAUDE.md「表示のみ → 独立検証を通ってから点数化」
の第1段階で、点数化するなら反映後にバックテストで確認してから。
"""
from __future__ import annotations

import bisect
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

# 1頭の勝率を使うのに要る最低出走数。1走だと0%か100%しか取らない
MIN_STARTS = 2
# メンバー質を作るのに要る、勝率が出せる頭数
MIN_FIELD = 3

# 差分の帯。境目は `scripts/aite_delta.py` の dt() と**完全に同じ**にする。
# 不等号の向きまで合わせること（あちらは弱化側が >= 、同等と強化(小)が >）。
# ここだけ >= にすると、ちょうど -0.02 の馬が別の帯に入る
BANDS = ((0.06, False, "相手弱化(大)"),
         (0.02, False, "相手弱化(小)"),
         (-0.02, True, "ほぼ同等"),
         (-0.06, True, "相手強化(小)"))
WEAKEST = "相手強化(大)"


def label_of(delta: float) -> str:
    for lo, strict, name in BANDS:
        if (delta > lo) if strict else (delta >= lo):
            return name
    return WEAKEST


@dataclass
class Index:
    """戦績から (日付, 場, R) → 出走馬名 と、馬ごとの日付列を作る。

    前走のメンバーは「その馬の前走がどのレースか」を特定してから、
    **そのレースの全出走馬**を引く必要がある。収集済みの戦績はすべての
    出走馬の行を持っているので、通信ゼロで作れる。
    """

    field: dict[tuple[str, str, str], list[str]]
    dates: dict[str, list[str]]
    # cumwins[名前][i] = その馬の i 走目より前の勝利数（長さ n+1）
    wins: dict[str, list[int]]
    runs: dict[str, list[tuple[str, str, str]]]   # 馬ごとの (日付,場,R)

    @classmethod
    def build(cls, records: dict[str, list[dict]]) -> "Index":
        field: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        dates: dict[str, list[str]] = {}
        wins: dict[str, list[int]] = {}
        runs: dict[str, list[tuple[str, str, str]]] = {}
        for name, rows in records.items():
            rs = sorted(rows, key=lambda r: r["日付"])
            dates[name] = [r["日付"] for r in rs]
            runs[name] = [(r["日付"], r["場"], r["R"]) for r in rs]
            acc, cum = 0, [0]
            for r in rs:
                if (r.get("着順") or "").isdigit() and int(r["着順"]) == 1:
                    acc += 1
                cum.append(acc)
            wins[name] = cum
            for r in rs:
                field[(r["日付"], r["場"], r["R"])].append(name)
        return cls(dict(field), dates, wins, runs)

    def prior(self, name: str, cutoff: str) -> tuple[int, int]:
        """cutoff より前の (出走数, 勝利数)。"""
        ds = self.dates.get(name)
        if not ds:
            return 0, 0
        i = bisect.bisect_left(ds, cutoff)
        return i, self.wins[name][i]

    def quality(self, names: list[str], cutoff: str,
                exclude: str | None = None) -> float | None:
        """出走馬の、cutoff 時点までの勝率の平均。"""
        rates = []
        for nm in names:
            if nm == exclude:
                continue
            s, w = self.prior(nm, cutoff)
            if s >= MIN_STARTS:
                rates.append(w / s)
        if len(rates) < MIN_FIELD:
            return None
        return statistics.mean(rates)

    def previous_run(self, name: str, cutoff: str):
        """cutoff より前の、直近の (日付, 場, R)。無ければ None。"""
        rs = self.runs.get(name)
        if not rs:
            return None
        ds = self.dates[name]
        i = bisect.bisect_left(ds, cutoff)
        return rs[i - 1] if i else None

    def delta(self, name: str, today_field: list[str],
              as_of: date | str) -> float | None:
        """前走のメンバー質 − 今走のメンバー質。正なら相手弱化。"""
        cutoff = as_of.isoformat() if isinstance(as_of, date) else str(as_of)
        prev = self.previous_run(name, cutoff)
        if prev is None:
            return None
        prev_names = self.field.get(prev)
        if not prev_names:
            return None
        fq_prev = self.quality(prev_names, cutoff, exclude=name)
        fq_now = self.quality(today_field, cutoff, exclude=name)
        if fq_prev is None or fq_now is None:
            return None
        return fq_prev - fq_now


def note(delta: float | None, zenso_chakujun: int | None) -> str | None:
    """表示用の一言。独立検証を通った組み合わせだけ踏み込む。

    差分だけで「弱化なら買い」とは言わない（単調な関係が無いことが
    実測で分かっている）。前走着順と組み合わさったときだけ、その旨を出す。
    """
    if delta is None or zenso_chakujun is None:
        return None
    lab = label_of(delta)
    weak = lab.startswith("相手弱化")
    strong = lab.startswith("相手強化")
    # **裸のラベルは出さない。** 差分そのものには単調な関係が無く
    # （弱化(大)と強化(大)がほぼ並ぶ）、しかもラベルはレース単位の事実に
    # なりやすい。OP戦では出走馬のほぼ全頭が「相手強化」になるので、
    # 全頭に付けば判別の役に立たない
    if weak and zenso_chakujun >= 10:
        return f"{lab}／前走二桁から相手が緩む"
    if strong and zenso_chakujun <= 2:
        return f"{lab}／前走1-2着は相手が楽だった可能性"
    return None
