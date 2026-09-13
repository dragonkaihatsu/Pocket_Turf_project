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


def for_venue(venue: str | None) -> Profile:
    """その競馬場のプロファイルを**切り替えずに**返す。

    `use_for_venue` はグローバルを書き換えるため、採点の途中で呼ぶと
    他の読み込み（ratings など）にも影響する。実測ファイルを引くだけの
    用途はこちらを使う（CLAUDE.md「プロファイル任せにせずパスを引数で受ける」の
    精神に沿って、少なくとも**場から決める**）。
    """
    return Profile(profile_for_venue(venue))


# ---------------------------------------------------------------------------
# 収集ディレクトリと出力先プロファイルの食い違いを止める（2026-09-13 追加）
#
# 実際に踏んだ事故: `scripts/calibrate.py --out data/profiles/jra/calibration.json`
# を既定の `--dir data/collected`（地方）で走らせ、**大井244レースの対応表を
# 中央のプロファイルに書き込んだ**。ヘッダには「大井9-12R 244レース」と
# 出ていたが、エラーは出ないので気づかずに通る。
#
# CLAUDE.mdはこの型の事故を繰り返し記録している（プロファイル取り違え・
# 帯の絞り込み・一軍の定義・race_idに開催日が無い件）。共通しているのは
# **もっともらしい違う数字が静かに出る**ことなので、書き込む前に止める。
# ---------------------------------------------------------------------------

def venues_in_dir(directory, limit: int = 400) -> set[str]:
    """収集ディレクトリのファイル名から競馬場名を集める。"""
    from .racefiles import race_venue
    out = set()
    for p in sorted(Path(directory).glob("*_結果.csv"))[:limit]:
        v = race_venue(p.name)
        if v:
            out.add(v)
    return out


def profile_for_dir(directory) -> str | None:
    """そのディレクトリが地方/中央どちらのデータか。混在・不明なら None。"""
    kinds = {profile_for_venue(v) for v in venues_in_dir(directory)}
    kinds.discard(None)
    return kinds.pop() if len(kinds) == 1 else None


def profile_of_path(path) -> str | None:
    """出力先パスから、どのプロファイルに書こうとしているかを読む。"""
    parts = {p for p in Path(path).parts}
    for name in ("jra", "nar"):
        if name in parts:
            return name
    return None


def assert_same_profile(directory, out_path) -> None:
    """入力データと出力先プロファイルが一致しなければ止める。

    どちらかが判定できないときは通す（推測で止めると使えなくなる）。
    止めるのは**はっきり食い違っているときだけ**。
    """
    src, dst = profile_for_dir(directory), profile_of_path(out_path)
    if src and dst and src != dst:
        raise SystemExit(
            f"■ 中止: 入力データと出力先プロファイルが食い違っている\n"
            f"    入力 {directory} は {src} のデータ"
            f"（{'・'.join(sorted(venues_in_dir(directory)))[:40]}…）\n"
            f"    出力 {out_path} は {dst} のプロファイル\n"
            f"  --dir を出力先に合わせること。地方の実測値を中央に当てても"
            f"エラーは出ず、もっともらしい違う予想が出るだけなので危険")
