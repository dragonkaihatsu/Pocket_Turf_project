"""100点メジャー: スコアを【馬単体能力・好走傾向・騎手・血統】の4つに束ねる。

ドラゴンさんの整理に合わせた**見せ方**であって、順位を決める計算式は
変えていない。ここは意図的にそうしている。

順位を変えると何が起きるかは実測した。好走傾向（直近5走の着内率）は
それ自体では着内率と単調に対応する強い指標だが、スコアに組み込んで
順位を動かすと**回収率が落ちた**（大井9-12R 244レース、馬連上位4頭BOX
135%→99%）。市場がすでに織り込んでいる情報を足すと、スコアが人気順に
近づき、スコアの取り柄である「市場とのズレ」が消えるためと考えられる。

だから100点メジャーは配点の再編ではなく、同じスコアを4つの軸で読み直す
ためのレイヤーとして置く。

配点（すべて採点できた場合）:

    馬単体能力  45点 = 基礎能力25 + 前走内容20 + 馬固有の補正
    好走傾向    40点 = コース適性15 + 距離・展開・脚質15 + 好走傾向10
    騎手         8点
    血統         7点
                ----
                100点

採点対象外の項目があると満点は100点未満になる。そのときは**満点を
下げたまま併記する**（100点に引き伸ばして数字を作らない）。
"""
from __future__ import annotations

from dataclasses import dataclass

from .scoring import (MAX_COURSE, MAX_KISO, MAX_KOSOU, MAX_KYORI, MAX_ZENSO,
                      HorseScore)

MAX_KISHU = 8
MAX_KETTO = 7

# 馬自身に紐づく補正（枠順・前走不利・高齢・初コース）は馬単体能力に寄せる。
# 騎手・血統だけが「上乗せされる価値」として独立した軸になる。
KISHU_LABEL = "騎手補正"
KETTO_LABEL = "血統補正"

NOURYOKU_ITEMS = ("基礎能力", "前走内容")
KEIKO_ITEMS = ("コース適性", "距離・展開・脚質", "好走傾向")

MAX_NOURYOKU = MAX_KISO + MAX_ZENSO          # 45
MAX_KEIKO = MAX_COURSE + MAX_KYORI + MAX_KOSOU  # 40
MAX_TOTAL = MAX_NOURYOKU + MAX_KEIKO + MAX_KISHU + MAX_KETTO  # 100


@dataclass
class Category:
    label: str
    points: float
    max_points: float
    detail: str

    @property
    def rate(self) -> float:
        return self.points / self.max_points if self.max_points else 0.0


@dataclass
class Measure:
    horse_name: str
    categories: list[Category]

    @property
    def points(self) -> float:
        return round(sum(c.points for c in self.categories), 2)

    @property
    def max_points(self) -> float:
        return round(sum(c.max_points for c in self.categories), 2)

    @property
    def is_full_scale(self) -> bool:
        return abs(self.max_points - MAX_TOTAL) < 1e-9

    def line(self) -> str:
        parts = " ".join(f"{c.label}{c.points:.1f}/{c.max_points:.0f}"
                         for c in self.categories)
        return f"{self.points:.1f}/{self.max_points:.0f}点  {parts}"


def _band(correction: float, max_points: float) -> float:
    """±の補正を 0〜max_points の帯に写す。中立は真ん中。

    補正そのものの大きさは変えない（KISHU_KETTO_WEIGHT で既に縮尺済み）。
    帯からはみ出す分だけ丸める。
    """
    return max(0.0, min(max_points, max_points / 2 + correction))


def measure_of(score: HorseScore) -> Measure:
    """1頭ぶんのスコアを100点メジャーに束ね直す。"""
    scored = {i.label: i for i in score.base_items if i.scored}
    skipped = {i.label: i for i in score.base_items if not i.scored}
    corr = {i.label: i.points for i in score.corrections}

    # 馬固有の補正（騎手・血統以外）は馬単体能力に寄せる
    other = sum(p for label, p in corr.items()
                if label not in (KISHU_LABEL, KETTO_LABEL))

    nou_pts = sum(scored[l].points for l in NOURYOKU_ITEMS if l in scored) + other
    nou_max = sum(scored[l].max_points or _default_max(l)
                  for l in NOURYOKU_ITEMS if l in scored)
    keiko_pts = sum(scored[l].points for l in KEIKO_ITEMS if l in scored)
    keiko_max = sum(scored[l].max_points or _default_max(l)
                    for l in KEIKO_ITEMS if l in scored)

    missing = [l for l in KEIKO_ITEMS if l in skipped]
    detail = "・".join(l for l in KEIKO_ITEMS if l in scored) or "採点項目なし"
    if missing:
        detail += f"（{('・'.join(missing))}は採点対象外）"

    cats = [
        Category("馬単体能力", round(max(0.0, min(nou_max, nou_pts)), 2), nou_max,
                 "基礎能力・前走内容＋馬固有の補正"),
        Category("好走傾向", round(keiko_pts, 2), keiko_max, detail),
        Category("騎手", round(_band(corr.get(KISHU_LABEL, 0.0), MAX_KISHU), 2),
                 MAX_KISHU, "実測の騎乗成績（上乗せ扱い）"),
        Category("血統", round(_band(corr.get(KETTO_LABEL, 0.0), MAX_KETTO), 2),
                 MAX_KETTO, "実測の産駒成績（上乗せ扱い）"),
    ]
    return Measure(score.horse.name, cats)


def _default_max(label: str) -> float:
    return {"基礎能力": MAX_KISO, "前走内容": MAX_ZENSO, "コース適性": MAX_COURSE,
            "距離・展開・脚質": MAX_KYORI, "好走傾向": MAX_KOSOU}.get(label, 0.0)


def measure_race(scores: list[HorseScore]) -> list[Measure]:
    return [measure_of(s) for s in scores]
