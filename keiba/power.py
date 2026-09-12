"""母数が足りているかを判定する道具。

## なぜ必要か

CLAUDE.mdは「母数が小さい統計から結論を出さない。率を提示するときは必ず
母数を併記する」としてきたが、**併記するだけでは足りなかった**。実際に
「複勝率40.0%対32.0%（8pt差）」を上向き材料と書いてしまい、あとで n=65 では
15pt未満の差は見えないことが分かって撤回している。

そこで「その母数で見分けられる差の大きさ」を先に計算し、
**観測した差がそれ未満なら判定不能として扱う**。事後の注記ではなく
事前・事後の選別に使う。

## 目安

対照の複勝率22%に対して必要な母数（有意水準5%両側・検出力80%）:

    1pt差 → 13,598頭   3pt差 → 1,538頭   5pt差 → 562頭
    8pt差 →    224頭  15pt差 →    66頭

人気帯×条件で切ると数百頭になるので、**そこで見える差は最低5〜8pt**。
それ未満の「傾向」は読み取れないものとして扱う。
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

Z_ALPHA = 1.959964   # 両側5%
Z_BETA = 0.841621    # 検出力80%

# この母数で見分けられる差がこれより大きい区分は「判定不能」にする。
# 実測で本物と確認できた効果は3〜8pt程度なので、5ptを超えると
# 「効果があっても見えない」領域になる
MDD_LIMIT = 0.05


def wilson(k: int, n: int) -> tuple[float, float]:
    """二項比率の95%信頼区間（Wilson）。母数が薄くても破綻しない。"""
    if n <= 0:
        return (0.0, 0.0)
    ph = k / n
    d = 1 + Z_ALPHA * Z_ALPHA / n
    c = ph + Z_ALPHA * Z_ALPHA / (2 * n)
    m = Z_ALPHA * sqrt(ph * (1 - ph) / n + Z_ALPHA * Z_ALPHA / (4 * n * n))
    return (max(0.0, (c - m) / d), min(1.0, (c + m) / d))


def required_n(p_control: float, diff: float) -> int:
    """対照 p_control に対し diff の差を検出するのに必要な検証群の母数。

    対照は十分大きい（数千〜万）ことを前提にした近似。手元のデータでは
    対照が1万頭規模なので実用上問題にならない。
    """
    if diff <= 0:
        return 0
    p1 = min(0.999, max(0.001, p_control + diff))
    num = (Z_ALPHA * sqrt(p_control * (1 - p_control))
           + Z_BETA * sqrt(p1 * (1 - p1))) ** 2
    return int(round(num / (diff * diff)))


def min_detectable_diff(n: int, p_control: float) -> float:
    """母数 n で見分けられる最小の差。required_n の逆関数（二分探索）。"""
    if n <= 0:
        return 1.0
    lo, hi = 1e-4, 0.5
    for _ in range(80):
        mid = (lo + hi) / 2
        if required_n(p_control, mid) > n:
            lo = mid
        else:
            hi = mid
    return hi


@dataclass
class Verdict:
    label: str
    n: int
    hits: int
    rate: float
    ci: tuple[float, float]
    p_control: float
    n_control: int
    mdd: float            # この母数で見分けられる最小の差
    diff: float           # 観測した差（検証群 − 対照）
    separated: bool       # 対照の点推定が信頼区間の外か
    code: str             # 差あり / 差なし / 判定不能
    need_n: int           # 観測した差を主張するのに必要だった母数

    @property
    def ok(self) -> bool:
        return self.code == "差あり"

    def line(self) -> str:
        arrow = "＋" if self.diff >= 0 else "−"
        return (f"{self.label:<32}{self.n:>6,}{self.rate:>7.1%}"
                f"  [{self.ci[0]:>5.1%}-{self.ci[1]:>5.1%}]"
                f"{arrow}{abs(self.diff) * 100:>4.1f}p"
                f"{self.mdd * 100:>7.1f}p{self.need_n:>8,}  {self.code}")


def judge(label: str, hits: int, n: int,
          hits_control: int, n_control: int,
          mdd_limit: float = MDD_LIMIT) -> Verdict:
    """検証群と対照群を比べ、母数を踏まえた判定を返す。

    判定:
      差あり   … 対照の点推定が検証群の信頼区間の外（差を主張できる）
      差なし   … 区間が重なるが、母数は十分（効果があれば見えたはず）
      判定不能 … 区間が重なり、かつこの母数では意味のある差も見えない
    """
    rate = hits / n if n else 0.0
    p_control = hits_control / n_control if n_control else 0.0
    ci = wilson(hits, n)
    mdd = min_detectable_diff(n, p_control)
    diff = rate - p_control
    separated = not (ci[0] <= p_control <= ci[1])
    if separated:
        code = "差あり"
    elif mdd <= mdd_limit:
        code = "差なし"
    else:
        code = "判定不能"
    return Verdict(label=label, n=n, hits=hits, rate=rate, ci=ci,
                   p_control=p_control, n_control=n_control, mdd=mdd,
                   diff=diff, separated=separated, code=code,
                   need_n=required_n(p_control, abs(diff)) if diff else 0)


HEADER = (f"{'区分':<32}{'n':>6}{'率':>7}{'  95%CI':>16}"
          f"{'差':>6}{'要る差':>7}{'必要n':>8}  判定")
