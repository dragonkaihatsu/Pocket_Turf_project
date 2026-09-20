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
MAX_BASE = MAX_KISO + MAX_ZENSO + MAX_COURSE + MAX_KYORI + MAX_CHOKYO  # 85

# 実測成績（scripts/build_ratings.py が作る）。あれば内蔵リストより優先する。
# どのプロファイル（地方/中央）の値を読むかは keiba.profile が決める
MIN_RIDES = 20      # 騎手補正を効かせる最低騎乗数
MIN_PROGENY = 20    # 血統補正を効かせる最低産駒数
MIN_SELF_STARTS = 3 # 馬自身の戦績を適性判断に使う最低出走数

# 騎手・血統補正の重み。CLAUDE.md の方針では騎手・血統は馬自身の能力に
# 「上乗せされる価値」であって、能力評価を覆すものではない。
# 実測でも補正の振れ幅（中央値8点）が能力スコアの1位2位差（中央値2.6点）を
# 上回っており、上乗せが本体を押しのける構造になっていた。ここで縮尺を掛ける。
# 実測（10-12R 178レース・1-9R由来の補正）では重みを下げるほど回収率が上がり、
# 1.0=70.6% / 0.5=72.3% / 0.25=73.5% / 0.0=73.2%。0.25〜0.0の差はノイズの範囲。
# 騎手・血統を残しつつ能力評価を覆せない大きさにする、という位置づけで 0.5 とする。
KISHU_KETTO_WEIGHT = 0.5


def load_ratings(path: Path | str | None = None,
                 venue: str | None = None) -> dict:
    """実測の騎手・種牡馬・脚質成績を読み込む。無ければ空を返す。

    **パスは競馬場名から決める**（`_base_times` と同じ）。`profile.active()`
    に頼ると、`--profile` を受けない単体スクリプト（`build_shinbun.py`
    `build_kompi.py`）では既定のままになり、**中央のレースを大井の脚質・
    騎手・血統データで採点する**。

    2026-09-19の新聞が実際にこれで出ていた。中山9Rで

        大井の ratings  ◎6 ○2 ▲3 △9 …（良54.56/48.60/47.87/47.57）
        中央の ratings  ◎6 ○3 ▲2 △9 …（良55.5/49.8/49.6/47.1）

    と並びが変わる。脚質の点数が大井の実測（先行38.0%・追込13.4%）で
    付くので、7.5点ぶんが別の値になるため。エラーは出ない。
    """
    p = Path(path) if path else (
        profile.for_venue(venue) if venue else profile.active()
    ).path("ratings.json")
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# 一軍騎手の判定。名前の列挙ではなく実測の騎乗数で決めるのは、リストの
# 更新漏れで静かに古い評価になるのを避けるため。
#
# ## 生の騎乗数だけで切ってはいけない（2026-09-12に判明）
#
# 当初は `n >= 400` だけで判定していた。**この閾値は収集量が増えると
# 静かに緩む**。1-8Rの収集で延べ騎乗が25,877→38,575に増えたところ、
# 400騎乗以上の騎手が**15人→32人**になり、同じ「一軍」という言葉が
# 別の集団を指すようになった。その結果:
#
#   前走二桁 × 一軍へ乗り替わりの複勝率
#     9-12R（一軍15人）              16.9%  → 前走6-9着(17.2%)相当
#     1-12R・n>=400（一軍32人）      13.6%  → 前走10着以下(11.8%)相当
#     1-12R・上位15人に固定           16.2%  ← 効果は再現していた
#     1-12R・上位16人に固定           16.4%
#
# つまり効果が消えたのではなく、**定義が緩んで薄まっただけ**だった。
# NORIKAE_KAKUAGE_POINTS はこの複勝率から校正しているので、放置すると
# 収集が進むほど「該当が増えて効果が薄い補正」に化けていく。
#
# そこで**人数（順位）で決める**。上位 JOCKEY_TIER1_TOPN 人、かつ
# JOCKEY_TIER1_RIDES 騎乗以上の両方を満たす騎手だけを一軍とする。
# 順位が収集量への不変性を、騎乗数の下限が「薄いコーパスで誰かを
# 一軍と呼んでしまう」ことを防ぐ（測れないなら補正しない側に倒れる）。
JOCKEY_TIER1_TOPN = 16
JOCKEY_TIER1_RIDES = 400

# 前走二桁着順の馬が一軍騎手に乗り替わったときに、前走内容へ足す点数。
#
# **勘で決めていない**。中央9-12Rの前走ペア14,485組で測ると、この形の馬の
# 今走複勝率は17.0%（n=507）で、前走6-9着だった馬の17.2%（n=4,090）とほぼ
# 同じだった（前走二桁で継続騎乗なら10.4%）。前走内容の素点は
# 二桁=3点・6-9着=6点なので、その差の3点を足して「前走6-9着相当」に
# 見なす、という意味の補正である（scripts/review_hypotheses.py）。
#
# 勝率でも +3.3p（6.7%対3.4%）で、複勝率・勝率の両方が2025年と2026年で
# 再現している。母数507に対して見分けられる差は4.0pt（複勝）なので、
# 観測した6.6ptは母数の裏付けがある
# NORIKAE_KAKUAGE_POINTS は ZENSO_TABLE の下で導出する（この行より後）

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

# 持ち時計指数を基礎能力に使うのに要求する、メンバー内で指数が作れた頭数。
# 2頭では「最小〜最大に正規化」が両端2頭だけの話になり、尺度にならない
MIN_MOCHI_FIELD = 4


def score_kiso_nouryoku(horse: Horse, field_horses: list[Horse],
                        mochi: dict[str, float] | None = None,
                        agari_mix: float = 0.0) -> ScoreItem:
    """基礎能力（25点）: 近走能力の相対評価。

    尺度の優先順位（2026-09-13 に更新）:

      1. 基礎能力評価カラム（手動）
      2. **持ち時計指数**（直近365日・距離と馬場で正規化した走破タイム）
      3. 前走の上がり3F

    2 を上に置いた理由は実測である（`scripts/mochidokei_test.py`、中央9-12R・
    窓内3走以上の17,585出走）。1-3番人気帯の複勝リフトが

        素の上がり3F偏差値   2025 +1.0p(判定不能) → 2026 +4.9p(差あり)
        持ち時計・メンバー相対 2025 +6.0p(差あり)  → 2026 +7.6p(差あり)

    と、**上がり3Fは期間で出方が変わるのに、持ち時計は両期間で差あり**だった。
    4-5番人気帯で上がり3Fが示す逆転（上位の勝率が下位より低い）も、
    メンバー相対の持ち時計では順方向に直る。

    **絶対値では使わない。** 絶対値のまま帯に切ると1-3番人気の複勝リフトが
    2025 −0.5p → 2026 +3.4p と符号ごと変わる。レース内で最小〜最大に
    正規化することがメンバー相対（重要度表の「トップとの差」「平均との差」）
    と同じ形になる。

    持ち時計が作れない馬（窓内3走未満）は上がり3Fに落とす。**混在するのは
    承知の上**で、落とす先が中立値だと情報のある馬だけ動いて歪むため。
    """
    if horse.kiso_nouryoku_override is not None:
        pts = max(0.0, min(MAX_KISO, horse.kiso_nouryoku_override))
        return ScoreItem("基礎能力", pts, "手動評価カラムによる上書き")

    w = max(0.0, min(1.0, agari_mix))
    mochi_pts = mochi_note = None
    if mochi and len(mochi) >= MIN_MOCHI_FIELD and horse.name in mochi:
        v = mochi[horse.name]
        lo, hi = min(mochi.values()), max(mochi.values())
        mochi_pts = _scale(v, lo, hi, MAX_KISO * 0.4, MAX_KISO)
        mochi_note = (f"持ち時計指数{v:+.2f}（メンバー{len(mochi)}頭中 "
                      f"{hi:+.2f}〜{lo:+.2f}・"
                      f"平均差{v - statistics.fmean(mochi.values()):+.2f}）")

    agari_pts = agari_note = None
    times = [h.agari_3f for h in field_horses if h.agari_3f is not None]
    if times and horse.agari_3f is not None:
        best, worst = min(times), max(times)
        # 上がり3F は小さいほど速い＝良い
        agari_pts = _scale(horse.agari_3f, worst, best, MAX_KISO * 0.4, MAX_KISO)
        agari_note = (f"上がり3F={horse.agari_3f:.1f}秒"
                      f"（出走馬中 最速{best:.1f}〜最遅{worst:.1f}）の相対評価")

    if mochi_pts is not None and agari_pts is not None and w > 0.0:
        if w >= 1.0:
            return ScoreItem("基礎能力", round(agari_pts, 2),
                             agari_note + "（上がり3F単独・持ち時計は不使用）")
        pts = (1.0 - w) * mochi_pts + w * agari_pts
        return ScoreItem(
            "基礎能力", round(pts, 2),
            f"持ち時計{mochi_pts:.1f}点と上がり3F{agari_pts:.1f}点を "
            f"{1 - w:.0%}:{w:.0%} で混合／{mochi_note}／{agari_note}",
        )

    if mochi_pts is not None:
        return ScoreItem("基礎能力", round(mochi_pts, 2), mochi_note)

    if agari_pts is not None:
        tail = "（持ち時計が作れず上がり3Fで代替）" if (mochi is not None and w < 1.0) else ""
        return ScoreItem("基礎能力", round(agari_pts, 2), agari_note + tail)

    return ScoreItem("基礎能力", MAX_KISO * 0.6, "上がり3Fデータなし→中立値")


# 前走着順 → 素点。**実測の今走複勝率を線形に写した値**であって、
# 着順の見た目どおりの並びではない（`scripts/zenso_table.py` が作る）。
#
# 中央9-12R・前走ペア23,757組（履歴1-12R→今走9-12R）での今走複勝率:
#
#     2着 42.9% > 3着 36.8% > **1着 32.0%** > 4着 29.0% > 5着 23.8%
#     > 6-9着 17.4% > 10着以下 11.4%
#
# **前走1着は2着・3着より低く、4着並みである。** 前走1着馬は昇級初戦に
# なりやすくクラスの壁に当たるためで、本人が指摘した「昇級戦の壁」が
# そのまま出ている。1着の95%CI[30.4-33.6]は2着[40.6-45.2]・3着[34.6-39.0]
# と重ならず、**2025・2026の両年で順序が完全に一致**する。
#
# 写像の両端は 3〜20 に固定してあるので**項目の配点20点は変えていない**。
# 変えたのは順序と間隔だけ（持ち時計指数を入れたときと同じ方針）。
ZENSO_TABLE = {1: 14.1, 2: 20.0, 3: 16.7, 4: 12.5, 5: 9.7}
ZENSO_6_9 = 6.2
ZENSO_10_OVER = 3.0

# 乗り替わり補正の大きさ＝「前走二桁の素点を前走6-9着へ読み替える」差そのもの。
# **定数で置かず表から導く**（旧実装は 3.0 と直書きで、ZENSO_TABLE を直すと
# 静かにずれる状態だった。一軍騎手の閾値を2か所に書いた件と同じ失敗）。
# 実測: 前走二桁×一軍騎手へ乗り替わりの複勝率は前走6-9着とほぼ同じ水準
NORIKAE_KAKUAGE_POINTS = round(ZENSO_6_9 - ZENSO_10_OVER, 2)


def score_zenso_naiyou(horse: Horse) -> ScoreItem:
    """前走内容（20点）: 前走着順を素点化。前走不利補正は別レイヤーで加点。"""
    ch = horse.zenso_chakujun
    if ch is None:
        return ScoreItem("前走内容", MAX_ZENSO * 0.5, "前走着順データなし→中立値")
    if ch in ZENSO_TABLE:
        pts = ZENSO_TABLE[ch]
    elif ch <= 9:
        pts = ZENSO_6_9
    else:
        pts = ZENSO_10_OVER
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

    table = ratings.get("脚質", {})
    kyaku = horse.kyakushitsu.strip()
    rec = table.get(kyaku)

    if not rec or rec.get("n", 0) < MIN_KYAKUSHITSU:
        reason = (f"脚質「{kyaku}」の実測が母数不足(n={rec['n']})" if rec
                  else ("脚質データなし" if not kyaku else f"脚質「{kyaku}」の実測値なし"))
        return ScoreItem("距離・展開・脚質", round(kyori_pts + half * 0.55, 2),
                          f"{kyori_note}／{reason}→脚質は中立")

    # 実測複勝率を、その場のいちばん低い脚質〜いちばん高い脚質で正規化する
    rates = [v["複勝率"] for v in table.values() if v.get("n", 0) >= MIN_KYAKUSHITSU]
    lo, hi = min(rates), max(rates)
    kyaku_pts = _scale(rec["複勝率"], lo, hi, half * 0.3, half) if hi > lo else half * 0.55

    return ScoreItem(
        "距離・展開・脚質", round(kyori_pts + kyaku_pts, 2),
        f"{kyori_note}／脚質「{kyaku}」実測複勝率{rec['複勝率']:.1%}(n={rec['n']})",
    )


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


# ---------------------------------------------------------------------------
# 補正項目（加減算）
# ---------------------------------------------------------------------------

def _candidates(table: dict, name: str) -> dict:
    """表記ゆれを含めて、その名前と両立するキーを全部集める。"""
    return {k: v for k, v in table.items() if same_jockey(name, k)}


def _lookup(table: dict, name: str) -> dict | None:
    """馬柱の略記に対応して引く。表記ゆれと別人を区別する。

    実測の表には**同じ人物が主表記＋ごく少数の別表記で二重に入っている**:

        田口(421騎乗) と 田口貫(4騎乗)、松若(395) と 松若風(2)、
        菊沢(472) と 菊沢一(3)、団野(455) と 団野大(7)

    一方で**別人が前方一致する**こともある:

        岩田康(344) と 岩田望(473) … どちらも「岩田」で始まる

    両者は構造で区別できる。**候補が入れ子（短い方が長い方の前方一致）なら
    同一人物**、**互いに前方一致しない兄弟なら別人**である。

      * 入れ子 → 同一人物なので、騎乗数がいちばん多い表記を代表にする
        （長い方を採ると n=4 の別表記を掴んで母数不足になる）
      * 兄弟   → 誰の成績か確定できないので **None を返して補正を掛けない**

    以前は「最も長い一致」を採っていたため、田口を引くと田口貫(4騎乗)に
    当たり、一軍騎手が一軍と判定されない不具合が出ていた。
    """
    if not name:
        return None
    if name in table:
        return table[name]
    cands = _candidates(table, name)
    if not cands:
        return None
    keys = sorted(cands, key=len)
    for a, b in zip(keys, keys[1:]):
        if not b.startswith(a):
            return None          # 兄弟関係 → 別人の可能性があるので引かない
    return max(cands.values(), key=lambda v: v.get("n", 0))


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


def same_jockey(a: str, b: str) -> bool:
    """2つの騎手表記が同一人物を指すか。

    netkeibaは表記を切る長さが一定でないため、同じ騎手が
    「国分恭介」「国分恭」のように別の文字列で出てくる。素の文字列比較で
    「乗り替わり」と判定すると、継続騎乗を乗り替わりと読んでしまう
    （実例: 田山旺佑→田山、国分恭介→国分恭）。

    一方が他方の前方一致なら同一人物とみなす。**前方一致しない場合は
    別人**として扱う（角田大和と角田和はどちらも他方で始まらないので
    正しく別人になる）。
    """
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


_TIER1_CUT_CACHE: dict[tuple[int, int], int] = {}


def tier1_min_rides(ratings: dict | None = None) -> int:
    """一軍とみなす騎乗数の下限を、その表の中の**順位**から決める。

    上位 `JOCKEY_TIER1_TOPN` 人目の騎乗数と `JOCKEY_TIER1_RIDES` の
    大きいほうを返す。収集量が増えて全体の騎乗数が膨らんでも、一軍の
    人数は増えない（上の解説を参照）。同数の騎手が並ぶと16人を少し
    超えることはあるが、境界の扱いとして許容する。
    """
    table = (ratings if ratings is not None else load_ratings()).get("騎手", {})
    # キーは**中身**から作る。最初 `id(table)` を混ぜたところ、別の表が
    # 同じidを再利用して（前の表がGCされた後）古い閾値を返した。
    # 人数と延べ騎乗が一致する表は実質同じ表なので、これで十分に区別できる
    counts = [r.get("n", 0) for r in table.values()
              if isinstance(r, dict) and r.get("n", 0) > 0]
    key = (len(counts), sum(counts))
    hit = _TIER1_CUT_CACHE.get(key)
    if hit is not None:
        return hit
    ns = sorted(counts, reverse=True)
    cut = ns[min(JOCKEY_TIER1_TOPN, len(ns)) - 1] if ns else 0
    val = max(cut, JOCKEY_TIER1_RIDES)
    if len(_TIER1_CUT_CACHE) > 64:
        _TIER1_CUT_CACHE.clear()
    _TIER1_CUT_CACHE[key] = val
    return val


def is_tier1_jockey(name: str, ratings: dict | None = None) -> bool:
    """実測の騎乗数から一軍騎手かどうかを判定する。

    同一性の解決は `_lookup` に任せる（入れ子の表記ゆれは畳み、別人の
    可能性がある兄弟関係は引かない）。名前が確定できなければ False に
    なるので、**曖昧な名前では加点しない**側に倒れる。

    閾値は `tier1_min_rides` が表から決める。固定の騎乗数ではないのは、
    収集量が増えると該当者が増えて定義が緩むため。
    """
    table = (ratings if ratings is not None else load_ratings())
    rec = _lookup(table.get("騎手", {}), name) if name else None
    return bool(rec and rec.get("n", 0) >= tier1_min_rides(table))


def zenso_jockey(records: dict[str, list[dict]] | None, horse: Horse,
                 as_of=None) -> str | None:
    """前走の騎手。馬別戦績から、レース日より前の最新の1走を見る。

    馬柱（出走馬CSV）には前走の騎手が入っていないため、全キャリアを
    取ってある馬でしか判定できない。取れない馬は None を返し、補正を
    掛けない（データが無いことを「該当しない」と混同しないため）。
    """
    if not records:
        return None
    from .horsedb import records_before
    past = records_before(records.get(horse.name, []), as_of)
    if not past:
        return None
    return (past[-1].get("騎手") or "").strip() or None


def correction_norikae(
    horse: Horse,
    records: dict[str, list[dict]] | None = None,
    as_of=None,
    ratings: dict | None = None,
) -> ScoreItem:
    """乗り替わり補正: 前走大敗のあと一軍騎手に乗り替わった形だけを評価する。

    **測れた条件にしか点を付けない**。中央9-12Rの前走ペア14,485組での実測:

      前走二桁着順 × 一軍騎手へ乗り替わり  複勝率17.0%(n=507) / 勝率6.7%
      前走二桁着順 × 継続騎乗              複勝率10.4%       / 勝率3.4%
      前走1-5着   × 一軍騎手へ乗り替わり  複勝率31.7%(n=755) / 勝率 差-0.2p
      前走1-5着   × 継続騎乗              複勝率32.5%

    前者は複勝率+6.6p・勝率+3.3pで、どちらも2025年と2026年で再現した。
    後者は母数755で差が無い（4.8pt以上なら見えた）。つまり
    **「強い騎手に替われば走る」のではなく「大敗のあと騎手を強化した形」
    だけが効く**。前走6-9着は未検証なので補正しない。

    回収率は別の話である。ここで足すのは「前走をどれだけ割り引くか」という
    能力評価であって、妙味の主張ではない（複勝回収76%・単勝回収も独立検証
    では再現しない）。KISHU_KETTO_WEIGHT を掛けないのは、この点数が
    騎手の上乗せではなく前走内容の読み替えであり、実測の対応表から
    直接出した大きさだから。掛けると校正が崩れる
    """
    ch = horse.zenso_chakujun
    if ch is None:
        return ScoreItem("乗り替わり補正", 0.0, "前走着順データなし→補正なし")

    prev = zenso_jockey(records, horse, as_of)
    if prev is None:
        return ScoreItem("乗り替わり補正", 0.0,
                         "前走の騎手が不明（馬別戦績が無い）→補正なし")

    ratings = ratings if ratings is not None else load_ratings()
    now_t1 = is_tier1_jockey(horse.jockey, ratings)
    prev_t1 = is_tier1_jockey(prev, ratings)
    # 素の文字列比較にしない。前走の騎手は馬ページ由来のフルネーム、今走は
    # 馬柱由来の略記なので、同一人物でも文字列が違う（国分恭介／国分恭）
    changed = not same_jockey(prev, horse.jockey)

    if ch >= 10 and changed and now_t1 and not prev_t1:
        return ScoreItem(
            "乗り替わり補正", NORIKAE_KAKUAGE_POINTS,
            f"前走{ch}着→一軍騎手へ乗り替わり（{prev}→{horse.jockey}）"
            f"。実測で前走6-9着相当（複勝率17.0%・n=507）")
    if ch <= 5 and changed and now_t1 and not prev_t1:
        return ScoreItem(
            "乗り替わり補正", 0.0,
            f"前走{ch}着からの格上げ乗り替わり（{prev}→{horse.jockey}）"
            f"。実測で差なし（n=755）→補正なし")
    if changed:
        return ScoreItem("乗り替わり補正", 0.0,
                         f"乗り替わり（{prev}→{horse.jockey}）だが"
                         "測れている条件に当たらない→補正なし")
    return ScoreItem("乗り替わり補正", 0.0, f"継続騎乗（{horse.jockey}）")


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


def load_waku_stats(path: Path | str | None = None,
                    venue: str | None = None) -> list[dict]:
    """場×芝ダの枠番バイアス実測（`scripts/build_waku_table.py`）を読む。

    `HistoryRecord`（同一レース名の過去10年データ）は日々の自動予想では
    一度も渡っていない（発火率0%）。同じレース名の多年データを集めるのは
    特別戦では非現実的なので、`keiba/courses.py` と同じ「場で束ねる」
    やり方で手元のコーパス（1-12R）から作った代用表。パスはratings.json等
    と同じく**競馬場名から**決める（`profile.active()` に頼らない）。
    """
    p = Path(path) if path else (
        profile.for_venue(venue) if venue else profile.active()
    ).path("waku_stats.json")
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in d.get("組み合わせ", []) if e.get("採用")]


def correction_wakuban(horse: Horse, history: list[HistoryRecord] | None,
                       venue: str | None = None, surface: str | None = None,
                       waku_stats: list[dict] | None = None) -> ScoreItem:
    """**同一レース名の過去10年データ**（`history`）があればそちらを優先する
    （その特別戦自体の枠バイアスなので、束ねた表より直接的）。無ければ
    `waku_stats`（場×芝ダで束ねた実測。`--採用`のセルのみ、両期間3年で
    符号が再現したものに限る）で代用する。
    """
    by_frame: dict[int, list[bool]] = {}
    for r in history or []:
        if r.wakuban is None or r.chakujun is None:
            continue
        by_frame.setdefault(r.wakuban, []).append(r.chakujun <= 3)

    if horse.wakuban in by_frame and len(by_frame) >= 2:
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
            f"{horse.wakuban}枠 複勝率{my_rate:.0%}（全体平均{mean_rate:.0%}・"
            "レース固有の過去10年データ）",
        )

    if not venue or not surface or not waku_stats:
        return ScoreItem("枠順補正", 0.0, "過去10年データ・実測表のいずれも無し→補正なし")

    from .sanko import waku_band
    band = waku_band(horse.wakuban)
    if band not in ("内枠(1-2)", "外枠(7-8)"):
        return ScoreItem("枠順補正", 0.0, f"{horse.wakuban}枠は中枠(3-6)で対象外")
    sd = surface[:1]
    hit = next((e for e in waku_stats if e["場"] == venue and e["芝ダ"] == sd
               and e["枠帯"] == band), None)
    if hit is None:
        return ScoreItem("枠順補正", 0.0,
                         f"{venue}・{sd}・{band}: 場×芝ダの実測は再現していない→補正なし")
    diff = hit["差"]
    pts = 3.0 if abs(diff) >= 0.045 else 2.0
    pts = pts if diff > 0 else -pts
    return ScoreItem(
        "枠順補正", pts,
        f"{horse.wakuban}枠（{band}） {venue}・{sd}の実測{diff * 100:+.1f}p"
        f"（n={hit['n']:,}・2024-2026再現・場×芝ダで束ねた代用表）",
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
    mochi: dict[str, float] | None = None,
    agari_mix: float = 0.0,
    surface: str | None = None,
    waku_stats: list[dict] | None = None,
) -> HorseScore:
    """venue は開催場名。コース適性はその場での自己成績から出すため、
    **渡さないとコース適性は中立になる**。以前は既定が「大井」だったが、
    中央のレースで大井の実績を探しに行く潜在バグだったため None にした。
    surface（芝/ダ）は枠順補正の場×芝ダ代用表を引くために使う。
    """
    self_course = self_kyori = None
    if records is not None:
        from .horsedb import records_before, summarize
        # 後知恵を排除するため、レース日より前の戦績だけを見る
        past = records_before(records.get(horse.name, []), as_of)
        if past:
            if venue:
                self_course = summarize(past, ba=venue)
            if kyori:
                self_kyori = summarize(past, kyori=kyori)

    course_item, has_experience = score_course_tekisei(horse, history, self_course)
    # **venue を渡す**。渡さないと既定プロファイル（地方）の実測を
    # 中央のレースに当てる（上の load_ratings のコメントを参照）
    ratings = load_ratings(venue=venue)

    base_items = [
        score_kiso_nouryoku(horse, field_horses, mochi, agari_mix),
        score_zenso_naiyou(horse),
        course_item,
        score_kyori_tekisei(horse, None, ratings, self_kyori),
        score_chokyo(horse, field_horses),
    ]
    corrections = [
        correction_kishu(horse, jockey_tiers, ratings),
        correction_norikae(horse, records, as_of, ratings),
        correction_ketto(horse, ratings),
        correction_wakuban(horse, history, venue, surface, waku_stats),
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
    base_times=None,
    agari_mix: float = 0.0,
    surface: str | None = None,
) -> list[HorseScore]:
    """出走馬をまとめて採点する。

    records に馬別戦績（馬名→行）を渡すと、コース適性・距離適性を
    その馬自身の実績から算出する。as_of にレース日を渡すと、それ以前の
    戦績だけを使う（過去レースを採点するときは必ず指定すること）。
    venue に開催場名を渡すとコース適性がその場の自己成績になる。
    渡さなければコース適性は中立のままになる。
    surface（芝/ダ）は枠順補正の場×芝ダ代用表を引くために使う。
    渡さなければ枠順補正はレース固有の過去10年データが無い限り0点のまま。
    """
    mochi = load_mochi(records, horses, as_of, base_times, venue)
    waku_stats = load_waku_stats(venue=venue) if surface else None
    return [score_horse(h, horses, history, kyori, jockey_tiers,
                        records, as_of, venue, mochi, agari_mix,
                        surface, waku_stats)
            for h in horses]


def load_mochi(records, horses, as_of, base_times=None,
               venue: str | None = None) -> dict[str, float]:
    """出走馬の持ち時計（近走平均）をまとめて出す。基準表が無ければ空。

    **レース単位で1回だけ作る**。1頭ずつ作るとメンバー内の正規化ができない。

    基準表の探し方は **競馬場名から決める**（`profile.profile_for_venue`）。
    `profile.active()` に頼ってはいけない: 集計スクリプトはプロファイルを
    切り替えないものが多く（`accuracy.py` / `calibrate.py` は既定の nar のまま）、
    **中央のレースを採点しているのに nar の基準表を探して「無い」と判断し、
    静かに旧尺度（上がり3F）へ落ちる**。実際にそれで A/B が12セル全部
    完全一致し、「新尺度でも数字が動かない」と誤読しかけた。
    CLAUDE.md「集計スクリプトがプロファイルを指定していない事故」の再発である。
    """
    if not records:
        return {}
    base = base_times if base_times is not None else _base_times(venue)
    if base is None:
        return {}
    from . import mochidokei as mk
    return mk.field_indices(records, [h.name for h in horses], as_of, base)


# 基準表はレースごとに読み直すと 2,000 レースで 2,000 回 JSON を開く。
# パスと更新時刻でキャッシュする（**id() では鍵にしない**。一軍騎手の閾値
# キャッシュで前の表がGCされた後に同じidが再利用され、古い値を返した）
_BASE_CACHE: dict[tuple[str, float], object] = {}


def _base_times(venue: str | None = None):
    """基準表を読む。無ければ None。

    venue を渡せばその競馬場のプロファイル（中山→jra、大井→nar）から探す。
    None は「持ち時計を作れない」という意味で、全馬0とは区別する
    （区別しないと基準表を置き忘れたときに静かに全馬同点になる）。
    """
    from . import mochidokei as mk
    prof = profile.for_venue(venue) if venue else profile.active()
    p = Path(prof.path("base_times.json"))
    if not p.exists():
        return None
    key = (str(p), p.stat().st_mtime)
    if key not in _BASE_CACHE:
        _BASE_CACHE.clear()
        _BASE_CACHE[key] = mk.BaseTimes.load(p)
    return _BASE_CACHE[key]
