"""予想（買い目）の対象レースを決める1か所。

> レース数を絞る重要性が今日わかりました
> 一応障害と、新馬戦は除外することでお願いします
> ただし、結果は集積します
> （本人の指示・2026-09-22）

**除外するのは予想・買い目だけで、収集は一切絞らない。**
`keiba.cli collect` は全レースを取り続け、コーパスは今までどおり育つ
（`horse_records_corpus.csv` / `base_times.json` などの実測表は
1-12R 全部から作る。CLAUDE.md「前走の47.6%は1-8Rにある」）。

## 除外の根拠は「当たらない」ではなく「採点できていない」
| 区分 | 何が欠けるか |
|---|---|
| 障害 | `mochidokei.index_of_record` が芝ダ以外を除くので**持ち時計が作れない**。上がり3Fも `models.parse_agari_3f` の 30.0〜48.0秒の外に出て欠損 |
| 新馬 | 過去走が無いので**前走内容が全馬同点**・持ち時計も作れない |

どちらも基礎能力25点と前走内容20点——スコアが実際に動かしている
45点——の入力が無い状態で、残りの項目は中立に倒れる。
実測は `scripts/taisho.py` で再現する。

## 障害の判定は「馬場種別」で行う。レース名は当てにならない
コーパスの障害330レースのうち**45本（14%）は名前に「障害」が入らない**
（中山グランドジャンプ・新潟JS・東京ハイジャンプ・阪神スプリングJ…）。
逆に `JS`/`SJ` を拾うと **WASJ第1戦・ヤングJSFR**（どちらも平地）が
16本引っかかる。**名前のパターンでは両方向に外す**ので、
`surface`（設定JSONの `障2880m` や `race_info.csv` の `馬場種別`）を
唯一の権威にする。名前は「障害」の語だけを補助に使う。
"""
from __future__ import annotations

# 除外の理由（表示にもそのまま使う）
JUMP = "障害"
DEBUT = "新馬"


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
                    surface: str | None = None) -> str | None:
    """予想の対象外なら理由（`障害` / `新馬`）、対象なら None。"""
    if is_jump(surface, name):
        return JUMP
    if is_debut(name):
        return DEBUT
    return None


def is_target(name: str | None = None, surface: str | None = None) -> bool:
    """予想（買い目）を出すレースか。"""
    return excluded_reason(name, surface) is None


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


def split_races(races: list[dict]) -> tuple[list[dict], list[tuple[dict, str]]]:
    """設定JSONのレース一覧を、予想対象と除外（理由つき）に分ける。

    **4つの出力経路（テキスト・新聞・一覧・カード）がここを通る。**
    経路ごとに条件を書くと静かにずれる（CLAUDE.mdが一軍騎手の閾値・
    `horse_records` の列・印の並びで繰り返し踏んだ失敗）。
    """
    kept, dropped = [], []
    for r in races:
        why = excluded_reason(r.get("name"), r.get("surface"))
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
