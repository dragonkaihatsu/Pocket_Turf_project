"""予想（買い目）の対象レースを決める1か所。

> レース数を絞る重要性が今日わかりました
> 一応障害と、新馬戦は除外することでお願いします
> ただし、結果は集積します
> （本人の指示・2026-09-22）

予想の対象は **9-12R かつ 障害・新馬でないレース** である。

**除外するのは予想・買い目だけで、収集は一切絞らない。**
`keiba.cli collect` は全レースを取り続け、コーパスは今までどおり育つ
（`horse_records_corpus.csv` / `base_times.json` などの実測表は
1-12R 全部から作る。CLAUDE.md「前走の47.6%は1-8Rにある」）。

## 除外の根拠は「当たらない」ではなく「採点できていない」
| 区分 | 何が欠けるか |
|---|---|
| 障害 | `mochidokei.index_of_record` が芝ダ以外を除くので**持ち時計が作れない**。上がり3Fも `models.parse_agari_3f` の 30.0〜48.0秒の外に出て欠損 |
| 新馬 | 過去走が無いので**前走内容が全馬同点**・持ち時計も作れない |
| 1-8R | 半分が未勝利（50.5%）で、そこは**持ち時計の発火が42%**。9-12Rの未勝利は68%・条件戦は76% |

どちらも基礎能力25点と前走内容20点——スコアが実際に動かしている
45点——の入力が無い状態で、残りの項目は中立に倒れる。
実測は `scripts/taisho.py` で再現する。

## 帯の既定は `racefiles.DEFAULT_RACES`（9-12R）から引く
**帯の定義を2か所に書かない。** 集計側（`keiba/racefiles.py`）と
予想側でずれると、実測表を作った帯と予想する帯が静かに食い違う
（CLAUDE.mdが一軍騎手の閾値・`horse_records` の列で繰り返し踏んだ失敗）。

レース番号が読めない設定は**除外して注記に出す**（通すと絞ったつもりで
絞れていない状態になる。`racefiles` と同じ判断）。

## 障害の判定は「馬場種別」で行う。レース名は当てにならない
コーパスの障害330レースのうち**45本（14%）は名前に「障害」が入らない**
（中山グランドジャンプ・新潟JS・東京ハイジャンプ・阪神スプリングJ…）。
逆に `JS`/`SJ` を拾うと **WASJ第1戦・ヤングJSFR**（どちらも平地）が
16本引っかかる。**名前のパターンでは両方向に外す**ので、
`surface`（設定JSONの `障2880m` や `race_info.csv` の `馬場種別`）を
唯一の権威にする。名前は「障害」の語だけを補助に使う。
"""
from __future__ import annotations

import re

from .racefiles import DEFAULT_RACES, parse_races

# 除外の理由（表示にもそのまま使う）
JUMP = "障害"
DEBUT = "新馬"

# 設定JSONの `race_no` は "9R" の形
RACE_NO_RE = re.compile(r"(\d{1,2})\s*R", re.I)


def band_label(races: str | None = None) -> str:
    """帯から外れた理由の表示（`9-12R外`）。"""
    return f"{races or DEFAULT_RACES}R外"


def race_number(race_no: str | int | None) -> int | None:
    """設定JSONの `race_no` からレース番号を取る。読めなければ None。"""
    if isinstance(race_no, int):
        return race_no
    m = RACE_NO_RE.search(str(race_no or ""))
    return int(m.group(1)) if m else None


def in_band(race_no: str | int | None,
            races: str | None = DEFAULT_RACES) -> bool:
    """予想の対象帯（既定9-12R）に入っているか。

    **`races=None` は「帯で絞らない」**。既定値を `None` にして
    `races or DEFAULT_RACES` と書くと意味が反転するので、既定は
    文字列で持つ（テストで固定した）。

    **番号が読めないレースは対象外**にする（注記に出るので黙って
    落ちるわけではない）。
    """
    if races is None:
        return True
    wanted = parse_races(races)
    if wanted is None:
        return True
    n = race_number(race_no)
    return n is not None and n in wanted


def is_jump(surface: str | None = None, name: str | None = None) -> bool:
    """障害戦か。**判定は surface が本命で、名前は補助**（上の docstring 参照）。

    surface は `障`・`障2880m`・`馬場種別` 列のいずれでも読める。
    """
    if surface and surface.strip().startswith("障"):
        return True
    return bool(name and "障害" in name)


def is_debut(name: str | None = None) -> bool:
    """新馬戦か。`新馬` は新馬戦にしか付かないので名前で確定できる
    （コーパス766本すべて平地。障害の新馬戦は存在しない）。"""
    return bool(name and "新馬" in name)


def excluded_reason(name: str | None = None,
                    surface: str | None = None,
                    race_no: str | int | None = None,
                    races: str | None = DEFAULT_RACES) -> str | None:
    """予想の対象外なら理由（`9-12R外` / `障害` / `新馬`）、対象なら None。

    `race_no` を渡さなければ帯は見ない（クラスだけで判定する）。
    `races=None` は帯で絞らない。
    """
    if race_no is not None and races is not None \
            and not in_band(race_no, races):
        return band_label(races)
    if is_jump(surface, name):
        return JUMP
    if is_debut(name):
        return DEBUT
    return None


def is_target(name: str | None = None, surface: str | None = None,
              race_no: str | int | None = None,
              races: str | None = DEFAULT_RACES) -> bool:
    """予想（買い目）を出すレースか。"""
    return excluded_reason(name, surface, race_no, races) is None


def race_class(name: str | None = None, surface: str | None = None) -> str:
    """レース区分。集計の見出しに使う（スコアには入れない）。"""
    if is_jump(surface, name):
        return "障害"
    if is_debut(name):
        return "新馬"
    n = name or ""
    if "未勝利" in n:
        return "未勝利"
    for k in ("1勝クラス", "2勝クラス", "3勝クラス"):
        if k in n:
            return "条件(1-3勝)"
    return "固有名(特別〜G1)"


def split_races(entries: list[dict],
                races: str | None = DEFAULT_RACES,
                ) -> tuple[list[dict], list[tuple[dict, str]]]:
    """設定JSONのレース一覧を、予想対象と除外（理由つき）に分ける。

    **4つの出力経路（テキスト・新聞・一覧・カード）がここを通る。**
    経路ごとに条件を書くと静かにずれる（CLAUDE.mdが一軍騎手の閾値・
    `horse_records` の列・印の並びで繰り返し踏んだ失敗）。

    `races` は予想の対象帯（既定9-12R）。`None` なら帯で絞らない。
    """
    kept, dropped = [], []
    for r in entries:
        why = excluded_reason(r.get("name"), r.get("surface"),
                              r.get("race_no"), races)
        (dropped.append((r, why)) if why else kept.append(r))
    return kept, dropped


def excluded_note(dropped: list[tuple[dict, str]]) -> str:
    """除外したレースの一言。**黙って落とさない**ため見出しに添える。
    該当が無ければ空文字（参考注記と同じく「行が無いこと」で伝える）。"""
    if not dropped:
        return ""
    counts: dict[str, int] = {}
    for _, why in dropped:
        counts[why] = counts.get(why, 0) + 1
    inner = "・".join(f"{k}{v}" for k, v in counts.items())
    return f"対象外 {len(dropped)}レース（{inner}）"
