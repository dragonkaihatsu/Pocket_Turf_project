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

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from . import profile
from .models import Horse, HistoryRecord

# ---- 配点上限（CLAUDE.md の配点表） ----
MAX_KISO = 25
MAX_ZENSO = 20
MAX_COURSE = 15
MAX_KYORI = 15
MAX_CHOKYO = 10
MAX_KOSOU = 10
MAX_BASE = (MAX_KISO + MAX_ZENSO + MAX_COURSE + MAX_KYORI
            + MAX_CHOKYO + MAX_KOSOU)  # 95（調教を採点対象外にすると85）

# 実測成績（scripts/build_ratings.py が作る）。あれば内蔵リストより優先する。
# どのプロファイル（地方/中央）の値を読むかは keiba.profile が決める
MIN_RIDES = 20      # 騎手補正を効かせる最低騎乗数
MIN_PROGENY = 20    # 血統補正を効かせる最低産駒数
MIN_SELF_STARTS = 3 # 馬自身の戦績を適性判断に使う最低出走数
MIN_KOSOU_STARTS = 3  # 好走傾向を採点する最低出走数
KOSOU_WINDOW = 5      # 好走傾向を見る直近レース数
# 好走傾向を採点するのに必要な「戦績を持つ馬」の割合。一部の馬しか戦績が
# 無い状態で採点すると、実力ではなく**データが取れているかどうか**で差が
# 付いてしまう。大井244レースで実測したところ、24%しか戦績が無い状態で
# 採点した結果、馬連上位4頭BOXの回収率が135%→99%に落ちた。
MIN_KOSOU_COVERAGE = 0.6

# 騎手・血統補正の重み。CLAUDE.md の方針では騎手・血統は馬自身の能力に
# 「上乗せされる価値」であって、能力評価を覆すものではない。
# 実測でも補正の振れ幅（中央値8点）が能力スコアの1位2位差（中央値2.6点）を
# 上回っており、上乗せが本体を押しのける構造になっていた。ここで縮尺を掛ける。
# 実測（10-12R 178レース・1-9R由来の補正）では重みを下げるほど回収率が上がり、
# 1.0=70.6% / 0.5=72.3% / 0.25=73.5% / 0.0=73.2%。0.25〜0.0の差はノイズの範囲。
# 騎手・血統を残しつつ能力評価を覆せない大きさにする、という位置づけで 0.5 とする。
KISHU_KETTO_WEIGHT = 0.5


def load_ratings(path: Path | str | None = None) -> dict:
    """実測の騎手・種牡馬成績を読み込む。無ければ空を返す。"""
    p = Path(path) if path else profile.active().path("ratings.json")
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


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
    # 採点対象外の項目（データ源が無く、点を付けると情報が無いのに配点だけ
    # 埋まってしまうもの）は scored=False にし、満点からも外す
    scored: bool = True
    max_points: float = 0.0


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
    def max_base(self) -> float:
        """実際に採点した項目の満点合計。採点対象外の項目は含めない。

        調教のように専門紙が要る項目を一律の中立値で埋めると、情報が無いのに
        配点だけ埋まった状態になる。採点しないと決めた項目は満点からも外す。
        """
        skipped = sum(i.max_points for i in self.base_items if not i.scored)
        return MAX_BASE - skipped

    @property
    def skipped_items(self) -> list[str]:
        return [i.label for i in self.base_items if not i.scored]

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


def score_course_tekisei(
    horse: Horse,
    history: list[HistoryRecord] | None,
    self_record: dict | None = None,
) -> tuple[ScoreItem, bool | None]:
    """コース適性（15点）: 同レースの過去10年データに当該馬の出走歴があれば
    その平均着順から算出。出走歴が無ければ手動評価カラムか中立値にフォールバック。

    戻り値の bool|None は「該当コース経験あり」かどうか（初コースペナルティ判定用）。
    history が None（過去10年データ自体が未提供）の場合は判定不能として None を返し、
    「未経験と確認された」わけではないことを区別する（全馬一律ペナルティを避けるため）。
    """
    if self_record:
        st = self_record
        n = st["着順あり"]
        if n >= MIN_SELF_STARTS:
            avg = st["平均着順"]
            # 平均1着→満点、平均8着以下→下限
            pts = _scale(avg, 8, 1, MAX_COURSE * 0.3, MAX_COURSE)
            return ScoreItem(
                "コース適性", round(pts, 2),
                f"当地{n}走・平均着順{avg:.1f}着"
                f"（{st['勝']}勝・複勝率{st['複'] / n:.0%}）",
            ), True
        if n > 0:
            return ScoreItem("コース適性", MAX_COURSE * 0.55,
                              f"当地{n}走のみ（{MIN_SELF_STARTS}走未満）→中立値"), True
        no_run = "当地の出走歴なし" if st["出走"] == 0 else "当地は出走のみで着順なし"
        return ScoreItem("コース適性", MAX_COURSE * 0.55, f"{no_run}→中立値"), False

    if history is None:
        return ScoreItem("コース適性", MAX_COURSE * 0.55, "過去10年データ未提供→中立値"), None

    past = [r for r in history if r.name == horse.name and r.chakujun is not None]
    if past:
        avg = statistics.mean(r.chakujun for r in past)
        # 平均1着→満点、平均8着以下→下限
        pts = _scale(avg, 8, 1, MAX_COURSE * 0.3, MAX_COURSE)
        return ScoreItem(
            "コース適性", round(pts, 2),
            f"当該レース過去出走{len(past)}回・平均着順{avg:.1f}着",
        ), True

    return ScoreItem("コース適性", MAX_COURSE * 0.55, "当該コース出走歴なし→中立値"), False


# 脚質補正を効かせる最低頭数。これを下回る脚質は中立に倒す
MIN_KYAKUSHITSU = 50


def score_kyori_tekisei(
    horse: Horse,
    kyori_hyoka_override: float | None,
    ratings: dict | None = None,
    self_kyori: dict | None = None,
    ichi_band: str = "",
    ichi_note: str = "",
) -> ScoreItem:
    """距離・展開・脚質（15点）。

    配点の半分を「距離」、半分を「展開・脚質」に割る。

    距離パートは、レース横断の距離別成績データを本仕様が定義していないため
    既定では中立値。距離適性評価カラム（0-15）で人間/Claudeの判断を差し込める。

    脚質パートは data/ratings.json の実測値（scripts/build_ratings.py が作る）を
    使う。大井は4角の位置取りが着順をほぼ支配するコースで、744レースの実測でも
    先行の勝率は追込の約4倍あり、1-9Rと10-12Rで同じ傾向が再現する。脚質は
    馬自身の特性であり、騎手・血統のような上乗せ要素とは区別して扱う。

    実測値が無い・母数不足の場合は中立に倒し、推定値を作らない。
    """
    half = MAX_KYORI / 2

    if kyori_hyoka_override is not None:
        pts = max(0.0, min(MAX_KYORI, kyori_hyoka_override))
        return ScoreItem("距離・展開・脚質", pts, "距離適性評価カラムによる手動評価")

    ratings = ratings if ratings is not None else load_ratings()

    # 距離パート: 馬自身の当該距離での成績があれば使う
    kyori_pts, kyori_note = half * 0.55, "距離別の戦績なし→中立"
    if self_kyori and self_kyori["着順あり"] >= MIN_SELF_STARTS:
        n, avg = self_kyori["着順あり"], self_kyori["平均着順"]
        kyori_pts = _scale(avg, 8, 1, half * 0.3, half)
        kyori_note = (f"当該距離{n}走・平均着順{avg:.1f}着"
                      f"（{self_kyori['勝']}勝・複勝率{self_kyori['複'] / n:.0%}）")

    # 展開パート: その馬自身の4角履歴から推定した位置を優先し、
    # 無ければ脚質ラベルに落とす。中央の「逃げ」は4割弱しかハナを取れず
    # 複勝率も差し馬と同じで、ラベルだけでは順序尺度にならないため
    kyaku = horse.kyakushitsu.strip()
    for key, label, note_head in (("位置推定", ichi_band, ichi_note),
                                  ("脚質", kyaku, f"脚質「{kyaku}」")):
        table = ratings.get(key, {})
        rec = table.get(label) if label else None
        if not rec or rec.get("n", 0) < MIN_KYAKUSHITSU:
            continue
        # 実測複勝率を、その表のいちばん低い区分〜いちばん高い区分で正規化する
        rates = [v["複勝率"] for v in table.values() if v.get("n", 0) >= MIN_KYAKUSHITSU]
        lo, hi = min(rates), max(rates)
        pts = _scale(rec["複勝率"], lo, hi, half * 0.3, half) if hi > lo else half * 0.55
        head = note_head if key == "脚質" else f"推定位置「{label}」{note_head}"
        return ScoreItem(
            "距離・展開・脚質", round(kyori_pts + pts, 2),
            f"{kyori_note}／{head} 実測複勝率{rec['複勝率']:.1%}(n={rec['n']})",
        )

    reason = "脚質データなし" if not kyaku else f"脚質「{kyaku}」の実測値なし・母数不足"
    return ScoreItem("距離・展開・脚質", round(kyori_pts + half * 0.55, 2),
                     f"{kyori_note}／{reason}→展開は中立")


CHOKYO_TABLE = {"S": 10, "A": 8, "B": 6, "C": 4, "D": 2}


def _has_chokyo(horse: Horse) -> bool:
    raw = horse.chokyo_hyoka.strip().upper()
    if raw in CHOKYO_TABLE:
        return True
    try:
        float(raw)
        return True
    except ValueError:
        return False


def score_chokyo(horse: Horse, field_horses: list[Horse] | None = None) -> ScoreItem:
    """調教（10点）: 調教評価（S/A/B/C/D、または数値1-5）を素点化。

    調教評価は専門紙からしか取れず、収集した馬柱には入っていない。
    **そのレースの誰も評価を持たない場合は採点対象外**とし、満点からも外す。
    一律の中立値で埋めると、情報が無いのに配点だけ埋まった状態になるため。

    一部の馬だけ評価がある場合は、持たない馬を中立値にして採点を続ける
    （評価を入力した馬だけが不利/有利にならないようにする）。
    """
    raw = horse.chokyo_hyoka.strip().upper()
    if raw in CHOKYO_TABLE:
        return ScoreItem("調教", CHOKYO_TABLE[raw], f"調教評価: {horse.chokyo_hyoka}",
                         max_points=MAX_CHOKYO)
    try:
        n = float(raw)
        pts = _scale(n, 1, 5, 2, 10)
        return ScoreItem("調教", round(pts, 2), f"調教評価(数値): {raw}",
                         max_points=MAX_CHOKYO)
    except ValueError:
        pass

    if field_horses is not None and not any(_has_chokyo(h) for h in field_horses):
        return ScoreItem("調教", 0.0, "採点対象外（調教評価は専門紙が必要）",
                         scored=False, max_points=MAX_CHOKYO)
    return ScoreItem("調教", 5, "調教評価データなし→中立値", max_points=MAX_CHOKYO)


def score_kosou_keiko(past: list[dict] | None,
                     field_coverage: float = 1.0) -> ScoreItem:
    """好走傾向（10点）: 直近5走の着内率をそのまま点数にする。

    大井9-12R 244レースの実測で、直近5走の着内率は実際の着内率と単調に対応した
    （0%の馬 14.0% → 80-100%の馬 66.0%）。しかもスコア順位で層別しても
    差が残る（1-2位で50.0%対69.7%、3-4位で34.4%対53.7%、5-8位で14.7%対
    25.7%）ため、既存の能力スコアが取りこぼしている情報がここにある。

    ただし**市場はこれをかなり織り込んでいる**（人気で層別すると差が
    安定しない）。スコアの当てはまりは良くなるが、それだけで妙味が
    出るわけではない点に注意。

    戦績が3走に満たない馬は判断材料が無いので中立値。ただし**戦績を持つ馬が
    レースの6割に満たない場合は項目ごと採点対象外**にする。一部の馬だけ
    採点すると、実力ではなくデータが取れているかどうかで差が付くためで、
    実測でも回収率が明確に落ちた（135%→99%）。
    """
    if field_coverage < MIN_KOSOU_COVERAGE:
        return ScoreItem(
            "好走傾向", 0.0,
            f"採点対象外（戦績を持つ馬が{field_coverage:.0%}しかいない／"
            f"{MIN_KOSOU_COVERAGE:.0%}必要）",
            scored=False, max_points=MAX_KOSOU)
    if past is None or len(past) < MIN_KOSOU_STARTS:
        return ScoreItem("好走傾向", MAX_KOSOU * 0.5, "直近戦績が3走未満→中立値",
                         max_points=MAX_KOSOU)

    recent = past[-KOSOU_WINDOW:]
    ok = [r for r in recent if str(r.get("着順", "")).isdigit()]
    if not ok:
        return ScoreItem("好走傾向", MAX_KOSOU * 0.5, "直近走の着順が取れず→中立値",
                         max_points=MAX_KOSOU)
    rate = sum(1 for r in ok if int(r["着順"]) <= 3) / len(ok)
    pts = round(_scale(rate, 0.0, 1.0, 0.0, MAX_KOSOU), 2)
    return ScoreItem("好走傾向", pts,
                     f"直近{len(ok)}走の着内率 {rate:.0%}"
                     f"（{'-'.join(str(r['着順']) for r in ok)}着）",
                     max_points=MAX_KOSOU)


# ---------------------------------------------------------------------------
# 補正項目（加減算）
# ---------------------------------------------------------------------------

def _lookup(table: dict, name: str) -> dict | None:
    """馬柱の騎手名は略記されることがあるため、前方一致でも引く。"""
    if not name:
        return None
    if name in table:
        return table[name]
    for k, v in table.items():
        if k.startswith(name) or name.startswith(k):
            return v
    return None


def correction_kishu(
    horse: Horse,
    tiers: dict[int, tuple[str, ...]] | None = None,
    ratings: dict | None = None,
) -> ScoreItem:
    """騎手補正。実測成績があればそれを使い、無ければ内蔵ティアにフォールバックする。"""
    ratings = ratings if ratings is not None else load_ratings()
    if rec := _lookup(ratings.get("騎手", {}), horse.jockey):
        n, rate = rec["n"], rec["複勝率"]
        if n < MIN_RIDES:
            return ScoreItem("騎手補正", 0.0,
                             f"{horse.jockey}: 複勝率{rate:.0%}（{n}騎乗・母数不足のため補正なし）")
        if rate >= 0.45:
            pts = 3.0
        elif rate >= 0.35:
            pts = 2.0
        elif rate >= 0.28:
            pts = 1.0
        elif rate < 0.10:
            pts = -2.0
        elif rate < 0.18:
            pts = -1.0
        else:
            pts = 0.0
        return ScoreItem("騎手補正", round(pts * KISHU_KETTO_WEIGHT, 2),
                         f"{horse.jockey}: 当地複勝率{rate:.0%}（{n}騎乗の実測）")

    tiers = tiers or DEFAULT_JOCKEY_TIERS
    for pts, names in sorted(tiers.items(), reverse=True):
        if any(n in horse.jockey for n in names):
            return ScoreItem("騎手補正", float(pts), f"実績上位騎手: {horse.jockey}")
    if horse.kishu_norikae:
        return ScoreItem("騎手補正", -1.0, f"乗り替わり（プラス実績なし）: {horse.jockey}")
    return ScoreItem("騎手補正", 0.0, f"{horse.jockey}（実測データなし）")


def correction_ketto(horse: Horse, ratings: dict | None = None) -> ScoreItem:
    """血統補正（種牡馬の当地成績）。

    CLAUDE.md の方針どおり、産駒数が少ない種牡馬は「血統軸ではニュートラル評価」
    とし、補正を掛けずにその旨をコメントに残す。
    """
    if not horse.ketto_chichi:
        return ScoreItem("血統補正", 0.0, "血統データなし→ニュートラル評価")
    ratings = ratings if ratings is not None else load_ratings()
    rec = _lookup(ratings.get("種牡馬", {}), horse.ketto_chichi)
    if not rec:
        return ScoreItem("血統補正", 0.0, f"{horse.ketto_chichi}: 当地データなし→ニュートラル評価")
    n, rate = rec["n"], rec["複勝率"]
    if n < MIN_PROGENY:
        return ScoreItem("血統補正", 0.0,
                         f"{horse.ketto_chichi}産駒: 複勝率{rate:.0%}"
                         f"（{n}頭・母数不足のためニュートラル評価）")
    if rate >= 0.45:
        pts = 2.0
    elif rate >= 0.40:
        pts = 1.0
    elif rate < 0.15:
        pts = -1.0
    else:
        pts = 0.0
    return ScoreItem("血統補正", round(pts * KISHU_KETTO_WEIGHT, 2),
                     f"{horse.ketto_chichi}産駒: 当地複勝率{rate:.0%}（{n}頭の実測）")


def correction_wakuban(horse: Horse, history: list[HistoryRecord] | None) -> ScoreItem:
    by_frame: dict[int, list[bool]] = {}
    for r in history or []:
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


def correction_hatsu_course(horse: Horse, has_course_experience: bool | None) -> ScoreItem:
    """has_course_experience が None（過去10年データ未提供で判定不能）の場合は
    「未経験と確認された」わけではないので、初コース側の判定はスキップする。
    長期休養明けの判定は独立に行う。
    """
    long_layoff = horse.kyusoku_days is not None and horse.kyusoku_days > 180
    confirmed_no_experience = has_course_experience is False
    if confirmed_no_experience or long_layoff:
        reasons = []
        if confirmed_no_experience:
            reasons.append("初コース")
        if long_layoff:
            reasons.append(f"長期休養明け({horse.kyusoku_days}日)")
        return ScoreItem("初コース・ぶっつけペナルティ", -3.0, "・".join(reasons))
    note = "判定不能（過去10年データ未提供）" if has_course_experience is None else "該当なし"
    return ScoreItem("初コース・ぶっつけペナルティ", 0.0, note)


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
    history: list[HistoryRecord] | None,
    kyori: int | None,
    jockey_tiers: dict[int, tuple[str, ...]] | None = None,
    records: dict[str, list[dict]] | None = None,
    as_of=None,
    venue: str | None = None,
    corner_records: dict[str, list[dict]] | None = None,
) -> HorseScore:
    """venue は開催場名。コース適性はその場での自己成績から出すため、
    **渡さないとコース適性は中立になる**。以前は既定が「大井」だったが、
    中央のレースで大井の実績を探しに行く潜在バグだったため None にした。
    """
    self_course = self_kyori = None
    past: list[dict] | None = None
    kosou_coverage = 0.0
    if records is not None:
        from .horsedb import records_before, summarize
        # 後知恵を排除するため、レース日より前の戦績だけを見る
        past = records_before(records.get(horse.name, []), as_of)
        if past:
            if venue:
                self_course = summarize(past, ba=venue)
            if kyori:
                self_kyori = summarize(past, kyori=kyori)
        # 好走傾向は「レース内の何割が戦績を持っているか」で採点可否を決める
        if field_horses:
            have = sum(
                1 for h in field_horses
                if len(records_before(records.get(h.name, []), as_of)) >= MIN_KOSOU_STARTS)
            kosou_coverage = have / len(field_horses)

    # 4角の位置推定。過去の通過順と脚質ラベルを合わせて「何番手にいそうか」を出す
    ichi_band = ichi_note = ""
    if corner_records is not None:
        from .tenkai import band_of, estimate, records_before as corner_before
        past_c = corner_before(corner_records.get(horse.name, []), as_of)
        rel, ichi_note = estimate(past_c, horse.kyakushitsu)
        ichi_band = band_of(rel)

    course_item, has_experience = score_course_tekisei(horse, history, self_course)
    ratings = load_ratings()

    base_items = [
        score_kiso_nouryoku(horse, field_horses),
        score_zenso_naiyou(horse),
        course_item,
        score_kyori_tekisei(horse, None, ratings, self_kyori, ichi_band, ichi_note),
        score_chokyo(horse, field_horses),
        score_kosou_keiko(past, kosou_coverage),
    ]
    corrections = [
        correction_kishu(horse, jockey_tiers, ratings),
        correction_ketto(horse, ratings),
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
    history: list[HistoryRecord] | None,
    kyori: int | None = None,
    jockey_tiers: dict[int, tuple[str, ...]] | None = None,
    records: dict[str, list[dict]] | None = None,
    as_of=None,
    venue: str | None = None,
    corner_records: dict[str, list[dict]] | None = None,
) -> list[HorseScore]:
    """出走馬をまとめて採点する。

    records に馬別戦績（馬名→行）を渡すと、コース適性・距離適性を
    その馬自身の実績から算出する。as_of にレース日を渡すと、それ以前の
    戦績だけを使う（過去レースを採点するときは必ず指定すること）。
    venue に開催場名を渡すとコース適性がその場の自己成績になる。
    渡さなければコース適性は中立のままになる。
    """
    return [score_horse(h, horses, history, kyori, jockey_tiers,
                        records, as_of, venue, corner_records) for h in horses]
