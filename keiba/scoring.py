"""100点スコアリングエンジン。

CLAUDE.md の配点表・補正項目をそのままコード化したもの。
各項目は (点数, 根拠コメント) のペアで返し、馬ごとの内訳を必ず提示できる
ようにしている（ブラックボックス化しない、という運用ルールに対応）。

データから機械的に決め切れない項目（距離適性など、レース横断データが
無いと本来は判断できない項目）は、中立値にフォールバックした上で
その旨をコメントに明記し、CSVの上書きカラムで人間/Claudeの判断を
差し込めるようにしている。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .models import Horse, HistoryRecord

# ---- 配点上限（CLAUDE.md の配点表） ----
MAX_KISO = 25
MAX_ZENSO = 20
MAX_COURSE = 15
MAX_KYORI = 15
MAX_CHOKYO = 10
MAX_BASE = MAX_KISO + MAX_ZENSO + MAX_COURSE + MAX_KYORI + MAX_CHOKYO  # 85

# 騎手補正の目安ティア（必要に応じて呼び出し側で差し替え可能）
DEFAULT_JOCKEY_TIERS: dict[int, tuple[str, ...]] = {
    3: ("ルメール", "川田将雅"),
    2: ("武豊", "戸崎圭太", "横山武史", "松山弘平", "レーン"),
    1: (
        "池添謙一", "福永祐一", "岩田望来", "横山典弘", "田辺裕信",
        "三浦皇成", "坂井瑠星", "北村友一", "菱田裕二", "岩田康誠", "浜中俊",
    ),
}


@dataclass
class ScoreItem:
    label: str
    points: float
    note: str


@dataclass
class HorseScore:
    horse: Horse
    base_items: list[ScoreItem] = field(default_factory=list)
    corrections: list[ScoreItem] = field(default_factory=list)
    baba_note: str = ""

    @property
    def base_subtotal(self) -> float:
        return sum(i.points for i in self.base_items)

    @property
    def correction_subtotal(self) -> float:
        return sum(i.points for i in self.corrections)

    @property
    def total_yoi(self) -> float:
        """良馬場スコア（馬場補正レイヤーを含まない基準スコア）"""
        return self.base_subtotal + self.correction_subtotal

    @property
    def total_omoi(self) -> float:
        """重馬場スコア（馬場状態補正レイヤー ±5 を加味）"""
        return self.total_yoi + self._baba_delta

    _baba_delta: float = 0.0

    def all_items(self) -> list[ScoreItem]:
        return self.base_items + self.corrections


def _scale(value: float, lo: float, hi: float, out_lo: float, out_hi: float) -> float:
    """value を [lo, hi] から [out_lo, out_hi] へ線形変換（クリップ付き）。"""
    if hi == lo:
        return (out_lo + out_hi) / 2
    ratio = (value - lo) / (hi - lo)
    ratio = max(0.0, min(1.0, ratio))
    return out_lo + ratio * (out_hi - out_lo)


# ---------------------------------------------------------------------------
# 基礎項目（85点満点の内訳）
# ---------------------------------------------------------------------------

def score_kiso_nouryoku(horse: Horse, field_horses: list[Horse]) -> ScoreItem:
    """基礎能力（25点）: 上がり3F の相対順位を近走能力の代理指標として使用。
    手動評価（基礎能力評価カラム）があればそちらを優先する。
    """
    if horse.kiso_nouryoku_override is not None:
        pts = max(0.0, min(MAX_KISO, horse.kiso_nouryoku_override))
        return ScoreItem("基礎能力", pts, "手動評価カラムによる上書き")

    times = [h.agari_3f for h in field_horses if h.agari_3f is not None]
    if not times or horse.agari_3f is None:
        return ScoreItem("基礎能力", MAX_KISO * 0.6, "上がり3Fデータなし→中立値")

    best, worst = min(times), max(times)
    # 上がり3F は小さいほど速い＝良い
    pts = _scale(horse.agari_3f, worst, best, MAX_KISO * 0.4, MAX_KISO)
    return ScoreItem(
        "基礎能力", round(pts, 2),
        f"上がり3F={horse.agari_3f:.1f}秒（出走馬中 最速{best:.1f}〜最遅{worst:.1f}）の相対評価",
    )


ZENSO_TABLE = {1: 20, 2: 17, 3: 14, 4: 11, 5: 9}


def score_zenso_naiyou(horse: Horse) -> ScoreItem:
    """前走内容（20点）: 前走着順を素点化。前走不利補正は別レイヤーで加点。"""
    ch = horse.zenso_chakujun
    if ch is None:
        return ScoreItem("前走内容", MAX_ZENSO * 0.5, "前走着順データなし→中立値")
    if ch in ZENSO_TABLE:
        pts = ZENSO_TABLE[ch]
    elif ch <= 9:
        pts = 6
    else:
        pts = 3
    return ScoreItem("前走内容", pts, f"前走{ch}着（{horse.zenso_race or '前走レース名不明'}）")


def score_course_tekisei(horse: Horse, history: list[HistoryRecord]) -> tuple[ScoreItem, bool]:
    """コース適性（15点）: 同レースの過去10年データに当該馬の出走歴があれば
    その平均着順から算出。出走歴が無ければ手動評価カラムか中立値にフォールバック。
    戻り値の bool は「該当コース経験あり」かどうか（初コースペナルティ判定用）。
    """
    past = [r for r in history if r.name == horse.name and r.chakujun is not None]
    if past:
        avg = statistics.mean(r.chakujun for r in past)
        # 平均1着→満点、平均8着以下→下限
        pts = _scale(avg, 8, 1, MAX_COURSE * 0.3, MAX_COURSE)
        return ScoreItem(
            "コース適性", round(pts, 2),
            f"当該レース過去出走{len(past)}回・平均着順{avg:.1f}着",
        ), True

    if horse.kiso_nouryoku_override is not None:
        pass  # override は基礎能力専用なので流用しない
    return ScoreItem("コース適性", MAX_COURSE * 0.55, "当該コース出走歴なし→中立値"), False


def score_kyori_tekisei(horse: Horse, kyori_hyoka_override: float | None) -> ScoreItem:
    """距離適性（15点）: レース横断の距離別成績データを本仕様は定義していない
    ため、既定では中立値。距離適性評価カラム（0-15）で人間/Claudeの判断を
    差し込める。
    """
    if kyori_hyoka_override is not None:
        pts = max(0.0, min(MAX_KYORI, kyori_hyoka_override))
        return ScoreItem("距離適性", pts, "距離適性評価カラムによる手動評価")
    return ScoreItem(
        "距離適性", MAX_KYORI * 0.55,
        "距離別成績データ未入力→中立値（距離適性評価カラムで上書き推奨）",
    )


CHOKYO_TABLE = {"S": 10, "A": 8, "B": 6, "C": 4, "D": 2}


def score_chokyo(horse: Horse) -> ScoreItem:
    """調教（10点）: 調教評価（S/A/B/C/D、または数値1-5）を素点化。"""
    raw = horse.chokyo_hyoka.strip().upper()
    if raw in CHOKYO_TABLE:
        return ScoreItem("調教", CHOKYO_TABLE[raw], f"調教評価: {horse.chokyo_hyoka}")
    try:
        n = float(raw)
        pts = _scale(n, 1, 5, 2, 10)
        return ScoreItem("調教", round(pts, 2), f"調教評価(数値): {raw}")
    except ValueError:
        return ScoreItem("調教", 5, "調教評価データなし→中立値")


# ---------------------------------------------------------------------------
# 補正項目（加減算）
# ---------------------------------------------------------------------------

def correction_kishu(horse: Horse, tiers: dict[int, tuple[str, ...]] | None = None) -> ScoreItem:
    tiers = tiers or DEFAULT_JOCKEY_TIERS
    for pts, names in sorted(tiers.items(), reverse=True):
        if any(n in horse.jockey for n in names):
            return ScoreItem("騎手補正", float(pts), f"実績上位騎手: {horse.jockey}")
    if horse.kishu_norikae:
        return ScoreItem("騎手補正", -1.0, f"乗り替わり（プラス実績なし）: {horse.jockey}")
    return ScoreItem("騎手補正", 0.0, f"{horse.jockey}（該当なし）")


def correction_wakuban(horse: Horse, history: list[HistoryRecord]) -> ScoreItem:
    by_frame: dict[int, list[bool]] = {}
    for r in history:
        if r.wakuban is None or r.chakujun is None:
            continue
        by_frame.setdefault(r.wakuban, []).append(r.chakujun <= 3)

    if horse.wakuban not in by_frame or len(by_frame) < 2:
        return ScoreItem("枠順補正", 0.0, "過去10年データ不足→補正なし")

    rates = {w: sum(v) / len(v) for w, v in by_frame.items() if v}
    mean_rate = statistics.mean(rates.values())
    my_rate = rates.get(horse.wakuban, mean_rate)
    diff = my_rate - mean_rate

    if diff >= 0.15:
        pts = 3.0
    elif diff >= 0.05:
        pts = 2.0
    elif diff <= -0.15:
        pts = -3.0
    elif diff <= -0.05:
        pts = -2.0
    else:
        pts = 0.0
    return ScoreItem(
        "枠順補正", pts,
        f"{horse.wakuban}枠 複勝率{my_rate:.0%}（全体平均{mean_rate:.0%}）",
    )


def correction_zenso_furi(horse: Horse) -> ScoreItem:
    if horse.zenso_furi:
        return ScoreItem("前走不利補正", 2.0, "前走は展開・コース適性等の外的要因で崩れたと判定")
    return ScoreItem("前走不利補正", 0.0, "該当なし")


def correction_koreiuma(horse: Horse, kyori: int | None) -> ScoreItem:
    age = horse.age
    if age is None or age < 7:
        return ScoreItem("高齢馬補正", 0.0, "該当なし（7歳未満）")

    base = -3.0 if age == 7 else -5.0
    if kyori is not None and kyori <= 1600:
        pts = round(base * 0.75, 2)
        note = f"{age}歳・距離{kyori}m(1600m以下のため75%軽減)"
    else:
        pts = base
        note = f"{age}歳"
    return ScoreItem("高齢馬補正", pts, note)


def correction_hatsu_course(horse: Horse, has_course_experience: bool) -> ScoreItem:
    long_layoff = horse.kyusoku_days is not None and horse.kyusoku_days > 180
    if not has_course_experience or long_layoff:
        reasons = []
        if not has_course_experience:
            reasons.append("初コース")
        if long_layoff:
            reasons.append(f"長期休養明け({horse.kyusoku_days}日)")
        return ScoreItem("初コース・ぶっつけペナルティ", -3.0, "・".join(reasons))
    return ScoreItem("初コース・ぶっつけペナルティ", 0.0, "該当なし")


def baba_delta(horse: Horse) -> tuple[float, str]:
    """馬場状態補正レイヤー（±5点）の重馬場側デルタ。良馬場側は0固定。"""
    delta = 0.0
    reasons = []
    if horse.michiwaru_koumono:
        delta += 4.0
        reasons.append("道悪巧者")
    if horse.kyakushitsu == "逃げ":
        delta += 2.0
        reasons.append("逃げ脚質（重馬場で押し切り期待）")
    elif horse.kyakushitsu in ("差し", "追込") and not horse.michiwaru_koumono:
        delta -= 2.0
        reasons.append("差し/追込かつ道悪実績なし（末脚が削がれるリスク）")
    delta = max(-5.0, min(5.0, delta))
    note = "・".join(reasons) if reasons else "特記事項なし"
    return delta, note


def apply_handicap_discount(score: HorseScore, horse: Horse) -> None:
    """ハンデ戦実績の割引: 前走がハンデ戦の好走だった場合、基礎能力・前走内容を
    保守的に評価する（0.9倍）。base_items を直接書き換える。
    """
    if not horse.zenso_handicap:
        return
    for item in score.base_items:
        if item.label in ("基礎能力", "前走内容"):
            discounted = round(item.points * 0.9, 2)
            item.note += "（前走ハンデ戦の好走のため0.9倍に割引・本斤量/格上馬との経験値要確認）"
            item.points = discounted


def score_horse(
    horse: Horse,
    field_horses: list[Horse],
    history: list[HistoryRecord],
    kyori: int | None,
    jockey_tiers: dict[int, tuple[str, ...]] | None = None,
) -> HorseScore:
    course_item, has_experience = score_course_tekisei(horse, history)

    base_items = [
        score_kiso_nouryoku(horse, field_horses),
        score_zenso_naiyou(horse),
        course_item,
        score_kyori_tekisei(horse, None),
        score_chokyo(horse),
    ]
    corrections = [
        correction_kishu(horse, jockey_tiers),
        correction_wakuban(horse, history),
        correction_zenso_furi(horse),
        correction_koreiuma(horse, kyori),
        correction_hatsu_course(horse, has_experience),
    ]

    score = HorseScore(horse=horse, base_items=base_items, corrections=corrections)
    apply_handicap_discount(score, horse)

    delta, note = baba_delta(horse)
    score._baba_delta = delta
    score.baba_note = note
    return score


def score_race(
    horses: list[Horse],
    history: list[HistoryRecord],
    kyori: int | None = None,
    jockey_tiers: dict[int, tuple[str, ...]] | None = None,
) -> list[HorseScore]:
    return [score_horse(h, horses, history, kyori, jockey_tiers) for h in horses]
