"""地方版・中央版のデータを取り違えないための仕組み。

スコアリングの計算式は地方でも中央でも同じだが、**その計算に使う実測値は
まったく別物**である。大井の1番人気は複勝率75.9%、中央は62.8%。脚質の効き方も
違う。中央のレースを大井の対応表で採点すると、エラーにならないまま
もっともらしい間違った予想が出る。これがいちばん危ない失敗の仕方なので、
どちらの数字を使うかを1か所で決める。

    data/profiles/nar/   地方（大井など）の実測値
    data/profiles/jra/   中央の実測値

いずれも同じファイル名を持つ:
    ratings.json       脚質・騎手・種牡馬の実測成績
    calibration.json   スコア順位 → 勝率・着内率
    box_stats.json     上位n頭BOXの点数別成績
    horse_records.csv  馬別の全戦績
    race_info.csv      レースごとの距離・馬場
    thresholds.json    買い目の型を切り替える1番人気オッズの閾値

無い項目は「データなし」として中立に倒す。数字を作らないという既存の方針は
プロファイルでも変えない。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = ROOT / "data" / "profiles"

NAR = "nar"
JRA = "jra"
DEFAULT_PROFILE = NAR

# 競馬場名からプロファイルを引く。ここに無い場合は既定を使う
JRA_VENUES = {"札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"}
NAR_VENUES = {"門別", "盛岡", "水沢", "浦和", "船橋", "大井", "川崎", "金沢", "笠松",
              "名古屋", "園田", "姫路", "高知", "佐賀"}

FILES = ("ratings.json", "calibration.json", "box_stats.json",
         "horse_records.csv", "race_info.csv", "thresholds.json")

# 買い目の型の既定閾値（地方＝大井の実測から決めた値）
DEFAULT_THRESHOLDS = {"鉄板_上限オッズ": 2.0, "波乱_下限オッズ": 3.0}


def profile_for_venue(venue: str | None) -> str:
    """競馬場名からプロファイル名を返す。分からなければ既定。"""
    if not venue:
        return DEFAULT_PROFILE
    if venue in JRA_VENUES or venue == "中央":
        return JRA
    if venue in NAR_VENUES or venue == "地方":
        return NAR
    return DEFAULT_PROFILE


@dataclass(frozen=True)
class Profile:
    name: str

    @property
    def dir(self) -> Path:
        return PROFILES_DIR / self.name

    def path(self, filename: str) -> Path:
        return self.dir / filename

    def exists(self, filename: str) -> bool:
        return self.path(filename).exists()

    def load_json(self, filename: str, default=None):
        p = self.path(filename)
        if not p.exists():
            return {} if default is None else default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {} if default is None else default

    @property
    def thresholds(self) -> dict:
        t = dict(DEFAULT_THRESHOLDS)
        t.update(self.load_json("thresholds.json"))
        return t

    def describe(self) -> str:
        have = [f for f in FILES if self.exists(f)]
        missing = [f for f in FILES if not self.exists(f)]
        label = "地方" if self.name == NAR else ("中央" if self.name == JRA else self.name)
        s = f"プロファイル: {label}({self.name}) / 揃っている: {len(have)}/{len(FILES)}"
        if missing:
            s += f" / 未整備: {', '.join(missing)}"
        return s


_active: Profile = Profile(os.environ.get("KEIBA_PROFILE", DEFAULT_PROFILE))


def active() -> Profile:
    return _active


def use(name: str) -> Profile:
    """使用するプロファイルを切り替える。"""
    global _active
    _active = Profile(name)
    return _active


def use_for_venue(venue: str | None) -> Profile:
    return use(profile_for_venue(venue))
