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


# ---------------------------------------------------------------------------
# 回収率の検出力（2026-09-12 追加）
#
# 「正解率は期間をまたいで再現する量、回収率は再現しない量」と記録してきたが、
# **再現しない理由を2つに分けていなかった**:
#
#   (A) 正解率の優位が価格に織り込まれていて、回収率の優位が存在しない
#   (B) 優位はあるが、回収率は分散が大きく、同じ優位を見るのに桁違いの母数が要る
#
# 実測すると(B)だった。前走二桁×一軍乗り替わり（n=693）で、勝率の差+3.4ptは
# 249頭で主張できるのに、回収率の差+93ptには2,117頭が要る（**9倍**）。
# 1頭あたり払戻のばらつきは σ≒10.8（回収率の単位）で、回収率そのものの
# 10倍以上ある。複勝は1頭ごとに0か1しか動かないが、払戻は0円か数万円動く。
#
# そこで**正解率とまったく同じ枠組み**（差あり／差なし／判定不能）を
# 回収率にも用意する。片方だけ甘い基準で読むのを防ぐため。

# 回収率で「意味のある差」とみなす下限。控除率25%＝損益分岐が100%なので、
# 25pt動かないと買い方の判断は変わらない。この母数で見分けられる差が
# これを超えるなら「効果があっても見えない」領域
ROI_MDD_LIMIT = 0.25


def need_for_roi(sd: float, diff: float) -> int:
    """回収率の差 diff（0.30 = 30pt）を見分けるのに要る母数。

    sd は1頭あたり払戻の標準偏差（回収率の単位＝賭け金で割った値）。
    2標本の平均の差の検定なので分散を2つ分見る。
    """
    if diff <= 0 or sd <= 0:
        return 0
    return int(((Z_ALPHA + Z_BETA) ** 2 * 2 * sd ** 2) / diff ** 2) + 1


def min_detectable_roi(n: int, sd: float) -> float:
    """その母数で見分けられる最小の回収率差。`need_for_roi` の逆。"""
    if n <= 0 or sd <= 0:
        return float("inf")
    return (Z_ALPHA + Z_BETA) * sqrt(2 * sd ** 2 / n)


@dataclass
class RoiVerdict:
    label: str
    n: int
    roi: float
    roi_control: float
    ci: tuple[float, float]   # ブートストラップ90%区間
    mdd: float                # この母数で見分けられる最小の回収率差
    diff: float
    code: str                 # 差あり / 差なし / 判定不能
    need_n: int
    hits: int                 # 的中本数（CLAUDE.mdの「10本以上」基準用）
    z: float                  # 2標本の差 ÷ その標準誤差

    @property
    def ok(self) -> bool:
        return self.code == "差あり"

    def line(self) -> str:
        arrow = "＋" if self.diff >= 0 else "−"
        return (f"{self.label:<32}{self.n:>6,}{self.roi:>7.0%}"
                f"  [{self.ci[0]:>5.0%}-{self.ci[1]:>5.0%}]"
                f"{arrow}{abs(self.diff) * 100:>4.0f}p"
                f"{self.mdd * 100:>6.0f}p{self.need_n:>8,}"
                f"  z={self.z:>+5.2f}  {self.code}")


def judge_roi(label: str, pay: list[float], pay_control: list[float],
              stake: float = 100.0, n_boot: int = 2000,
              seed: int = 20260912,
              mdd_limit: float = ROI_MDD_LIMIT) -> RoiVerdict | None:
    """払戻の配列から回収率を判定する。`judge` と同じ3値を返す。

    pay / pay_control は1点あたりの払戻（円、外れは0）。

    ## 対照の回収率を「固定値」として扱ってはいけない（2026-09-12）

    最初は `judge` と同じ形（対照の点推定が検証群の区間の外なら差あり）で
    書いたが、**回収率では対照側の誤差が無視できない**。実測では対照
    4,525頭でも σ=13.5 なので、その平均の標準誤差は13.5/√4525 ≒ **20pt**
    ある。率なら対照の母数が大きければ点推定はほぼ確定するが、回収率は
    裾が重いのでそうならない。

    そこで**2標本の検定**にする:

        se = √(σ²/n + σ_c²/n_c)      z = 差 / se

    前走二桁×一軍乗り替わりだと se≒46pt・差104pt → z=2.3 で有意。
    `need_n`（検出力80%に要る母数）は別の話で、**有意だが検出力不足**の
    ときは効果量が過大に出ている可能性を含む（勝者の呪い）。
    両方を返して読み分ける。

    区間表示はブートストラップで作る（正規近似の区間は狭く出る）。
    """
    import random as _random
    if len(pay) < 2 or len(pay_control) < 2:
        return None
    roi = [p / stake for p in pay]
    roi_c = [p / stake for p in pay_control]
    n = len(roi)
    mean = sum(roi) / n
    mean_c = sum(roi_c) / len(roi_c)
    var = sum((x - mean) ** 2 for x in roi) / (n - 1)
    sd = sqrt(var)
    sd_c = sqrt(sum((x - mean_c) ** 2 for x in roi_c) / (len(roi_c) - 1))
    rng = _random.Random(seed)
    boot = sorted(sum(rng.choices(roi, k=n)) / n for _ in range(n_boot))
    lo, hi = boot[int(n_boot * 0.05)], boot[int(n_boot * 0.95) - 1]
    mdd = min_detectable_roi(n, max(sd, sd_c))
    diff = mean - mean_c
    se = sqrt(var / n + sd_c ** 2 / len(roi_c))
    z = diff / se if se > 0 else 0.0
    if abs(z) >= Z_ALPHA:
        code = "差あり"
    elif mdd <= mdd_limit:
        code = "差なし"
    else:
        code = "判定不能"
    return RoiVerdict(label=label, n=n, roi=mean, roi_control=mean_c,
                      ci=(lo, hi), mdd=mdd, diff=diff, code=code,
                      need_n=need_for_roi(max(sd, sd_c), abs(diff)),
                      hits=sum(1 for x in roi if x > 0), z=z)


ROI_HEADER = (f"{'区分':<32}{'n':>6}{'回収':>7}{'  90%区間':>16}"
              f"{'差':>6}{'要る差':>7}{'必要n':>8}  判定")
