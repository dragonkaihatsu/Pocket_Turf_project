"""レース内で相対化した特徴量を作る。

外部AIの重要度表を見ると、上位10項目のうち**7つが「メンバートップとの差」
「メンバー平均との差」「メンバー内順位」**だった。うちのスコアリングは
絶対値で入れていて、最後に順位を付けるだけだったので、この情報を
渡せていなかった。

  同じ「前走3着」でも、他が全員1着なら弱く、全員10着なら強い。

材料は build_speed_db.py / build_jockey_db.py が作ったDBから引く。

**未来の情報を入れないための約束**
  - 馬の履歴は「当該レース日より前」だけ
  - 騎手成績は「当該レースの年より前」だけ（DBが年で行を分けてある）
  - 当日の馬場差は使わない（過去走の指数を作るのには使ってよい）
"""
from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

RECENT = 3          # 「近3走」の本数
ALL = "計"          # jockey_stats.csv でまとめ行に入っている印


def _f(x, default=None):
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return default


@dataclass
class SpeedDB:
    """馬名 → その馬の全出走履歴（日付順）。使うときに日付で切る。"""
    by_horse: dict = field(default_factory=lambda: defaultdict(list))

    @classmethod
    def load(cls, path) -> "SpeedDB":
        db = cls()
        p = Path(path)
        if not p.exists():
            return db
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            db.by_horse[r["馬名"]].append({
                "日付": r["日付"], "場": r["場"], "馬場種別": r["馬場種別"],
                "距離": int(r["距離"]), "着順": int(r["着順"]),
                "時計指数": _f(r["時計指数"]), "上がり3F": _f(r["上がり3F"]),
            })
        for v in db.by_horse.values():
            v.sort(key=lambda x: x["日付"])
        return db

    def past(self, name: str, as_of: str) -> list:
        return [x for x in self.by_horse.get(name, ()) if x["日付"] < as_of]

    # --- 1頭ぶんの素の値。相対化は race_features で行う -----------------

    def latest_index(self, name, as_of):
        p = self.past(name, as_of)
        return p[-1]["時計指数"] if p else None

    def best_index(self, name, as_of, n=RECENT):
        p = self.past(name, as_of)[-n:]
        vals = [x["時計指数"] for x in p if x["時計指数"] is not None]
        return max(vals) if vals else None

    def mean_chaku(self, name, as_of, n=RECENT):
        p = self.past(name, as_of)[-n:]
        return statistics.mean(x["着順"] for x in p) if p else None

    def surface_rate(self, name, as_of, surface):
        """芝・ダート別の過去勝率。"""
        p = [x for x in self.past(name, as_of) if x["馬場種別"] == surface]
        return (sum(1 for x in p if x["着順"] == 1) / len(p)) if p else None

    def dist_mean_chaku(self, name, as_of, kyori, tol=200):
        """近い距離での過去平均着順。"""
        p = [x for x in self.past(name, as_of)
             if abs(x["距離"] - kyori) <= tol]
        return statistics.mean(x["着順"] for x in p) if p else None


@dataclass
class JockeyDB:
    """(騎手, 年, 場, 芝ダ, 距離帯) → 成績。年より前だけ足して使う。"""
    rows: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path) -> "JockeyDB":
        db = cls()
        p = Path(path)
        if not p.exists():
            return db
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            key = (r["騎手"], r["年"], r["場"], r["馬場種別"], r["距離帯"])
            db.rows[key] = {
                "騎乗": int(r["騎乗"]), "勝": int(r["勝"]), "複": int(r["複"]),
                "期待勝": _f(r["期待勝"], 0.0), "期待複": _f(r["期待複"], 0.0),
                "単勝払戻": _f(r["単勝払戻"], 0.0),
            }
        return db

    def stats(self, jockey, year, venue=ALL, surface=ALL, band=ALL,
              min_rides=20):
        """その年より前を合算する。母数に満たなければ None。"""
        tot = {"騎乗": 0, "勝": 0, "複": 0, "期待勝": 0.0, "期待複": 0.0}
        for (j, y, v, s, b), a in self.rows.items():
            if j != jockey or v != venue or s != surface or b != band:
                continue
            if y >= year:
                continue           # 当該年以降は使わない
            for k in tot:
                tot[k] += a[k]
        if tot["騎乗"] < min_rides:
            return None
        return {
            "騎乗": tot["騎乗"],
            "勝率": tot["勝"] / tot["騎乗"],
            "複勝率": tot["複"] / tot["騎乗"],
            "勝期待比": tot["勝"] / tot["期待勝"] if tot["期待勝"] else None,
        }


def _rank(values: list, higher_is_better: bool) -> list:
    """None を最下位に置いた 1始まりの順位。同値は同順位にしない。"""
    order = sorted(range(len(values)),
                   key=lambda i: (values[i] is None,
                                  -values[i] if (values[i] is not None
                                                 and higher_is_better)
                                  else (values[i] if values[i] is not None
                                        else 0)))
    out = [0] * len(values)
    for pos, i in enumerate(order, 1):
        out[i] = pos
    return out


def _rel(values: list, higher_is_better: bool) -> dict:
    """メンバートップとの差・平均との差・順位をまとめて返す。"""
    known = [v for v in values if v is not None]
    if not known:
        n = len(values)
        return {"top差": [None] * n, "平均差": [None] * n,
                "順位": [None] * n}
    top = max(known) if higher_is_better else min(known)
    avg = statistics.mean(known)
    sign = 1 if higher_is_better else -1
    return {
        "top差": [None if v is None else sign * (v - top) for v in values],
        "平均差": [None if v is None else sign * (v - avg) for v in values],
        "順位": _rank(values, higher_is_better),
    }


def race_features(names: list, jockeys: list, as_of: str, venue: str,
                  surface: str, kyori: int, speed: SpeedDB,
                  jockey_db: JockeyDB | None = None) -> list[dict]:
    """出走各馬について、レース内で相対化した特徴量を返す。

    names / jockeys は同じ並び。戻り値も同じ並びの dict のリスト。
    値が取れない馬は None のまま返す（**中立値で埋めて数字を作らない**）。
    """
    year = as_of[:4]
    band = ("〜1400" if kyori <= 1400 else
            "1401-1800" if kyori <= 1800 else "1801〜")

    latest = [speed.latest_index(n, as_of) for n in names]
    best3 = [speed.best_index(n, as_of) for n in names]
    chaku3 = [speed.mean_chaku(n, as_of) for n in names]
    srate = [speed.surface_rate(n, as_of, surface) for n in names]
    dchaku = [speed.dist_mean_chaku(n, as_of, kyori) for n in names]

    jwin = jcourse = [None] * len(names)
    if jockey_db is not None:
        jwin = [(jockey_db.stats(j, year) or {}).get("勝率") for j in jockeys]
        jcourse = [(jockey_db.stats(j, year, venue=venue) or {}).get("勝率")
                   for j in jockeys]

    r_latest = _rel(latest, True)      # 時計指数は高いほど良い
    r_best3 = _rel(best3, True)
    r_chaku = _rel(chaku3, False)      # 着順は小さいほど良い
    r_srate = _rel(srate, True)
    r_dchaku = _rel(dchaku, False)
    r_jwin = _rel(jwin, True)

    out = []
    for i in range(len(names)):
        out.append({
            # 表1位・2位: 近走時計指数とメンバートップ／平均との差
            "時計_top差": r_latest["top差"][i],
            "時計_平均差": r_latest["平均差"][i],
            "時計_順位": r_latest["順位"][i],
            # 表6位: 近3走の最高時計指数のメンバー内順位
            "近3走最高時計_順位": r_best3["順位"][i],
            "近3走最高時計_top差": r_best3["top差"][i],
            # 表5位: 近3走の平均着順のメンバー内順位
            "近3走平均着順_順位": r_chaku["順位"][i],
            "近3走平均着順": chaku3[i],
            # 表4位: 芝ダ別の過去勝率のメンバー内順位
            "芝ダ勝率_順位": r_srate["順位"][i],
            # 表8位: 馬の距離別の過去平均着順
            "距離別平均着順": dchaku[i],
            "距離別平均着順_順位": r_dchaku["順位"][i],
            # 表7位・10位: 騎手
            "騎手当該場勝率": jcourse[i],
            "騎手勝率_順位": r_jwin["順位"][i],
            "_距離帯": band,
        })
    return out
