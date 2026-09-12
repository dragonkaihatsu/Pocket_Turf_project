"""結果CSVを「対象レース番号だけ」に絞って列挙する共通ヘルパ。

## なぜ必要か

`data/collected_jra` には当初9-12Rしか入っていなかったため、多くの集計
スクリプトが `glob("*_結果.csv")` で全件を読んでいた。**1-8Rの収集を
始めた時点で、その書き方は静かに壊れる**:

  * 1-8Rの収集は月単位で進むので、途中では**特定の月の1-8Rだけ**が
    混ざる。期間の偏りがそのまま集計に入る
  * 「中央9-12R 1,954レースの実測」としてCLAUDE.mdに載せた数字と、
    同じスクリプトを回した結果が一致しなくなる
  * エラーは出ない。もっともらしい違う数字が出るだけで、これが
    いちばん危ない失敗の仕方（CLAUDE.md「地方版・中央版の分離」と同じ構図）

そこで**レース番号の絞り込みを1か所に集める**。新しく集計スクリプトを
書くときは、`glob` を直接使わずこのモジュールを通すこと。

## 既定は9-12R

CLAUDE.md「対象レース帯は9-12R」に合わせる。1-8Rを含めたいときは
明示的に `races="1-12"` を渡す（材料と検証を分ける用途では
`races="1-8"` のように使う）。
"""
from __future__ import annotations

import re
from pathlib import Path

# CLAUDE.md「対象レース帯は9-12R（2026-09-04以降）」
DEFAULT_RACES = "9-12"

# ファイル名は「日付_場名RR_レース名_結果.csv」。場名を決め打ちにしない
# （CLAUDE.md「集計スクリプトの競馬場決め打ちに注意」）
RACE_NO_RE = re.compile(r"_\D+?(\d{2})R_")


def parse_races(spec: str | None) -> set[int] | None:
    """"9-12" や "1,3,5" を集合にする。None/空文字は「絞らない」。"""
    if not spec:
        return None
    out: set[int] = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = (int(x) for x in part.split("-", 1))
            out.update(range(lo, hi + 1))
        else:
            out.add(int(part))
    return out or None


def race_number(name: str) -> int | None:
    """ファイル名・stem からレース番号を取り出す。取れなければ None。"""
    m = RACE_NO_RE.search(Path(name).name + "_")
    return int(m.group(1)) if m else None


def result_files(directory: str | Path,
                 races: str | None = DEFAULT_RACES) -> list[Path]:
    """対象レース番号の結果CSVを日付順で返す。

    レース番号が取れないファイルは**除外する**。番号が読めないものを
    通すと、絞ったつもりで絞れていない状態になる。
    """
    wanted = parse_races(races)
    out = []
    for p in sorted(Path(directory).glob("*_結果.csv")):
        rn = race_number(p.name)
        if rn is None:
            continue
        if wanted is not None and rn not in wanted:
            continue
        out.append(p)
    return out


def result_paths(directory: str | Path,
                 races: str | None = DEFAULT_RACES) -> list[str]:
    """`result_files` の str 版（glob.glob を置き換えやすい形）。"""
    return [str(p) for p in result_files(directory, races)]
