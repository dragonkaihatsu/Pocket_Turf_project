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

## 期間でも絞れる（`months=`）

レース番号だけ絞っても**期間の偏りは消えない**。1-8Rの収集は月単位で
進むので、途中で `races="1-12"` を渡すと「1-8Rが入っている数ヶ月」と
「9-12Rだけの残り」が混ざった集計になる。1-8Rを足した効果を測りたい
なら、**1-8Rが揃っている月だけに期間を揃えて** 9-12R と 1-12 を
比べる必要がある:

    months = "2025-01..2025-03"
    result_files(d, races="9-12", months=months)   # 対照
    result_files(d, races="1-12", months=months)   # 1-8Rを足した版

`complete_months(d, races)` は「その帯が全レース番号そろっている月」を
返す。どこまで揃っているかを推測せずに調べるために使う。
"""
from __future__ import annotations

import re
from pathlib import Path

# CLAUDE.md「対象レース帯は9-12R（2026-09-04以降）」
DEFAULT_RACES = "9-12"

# ファイル名は「日付_場名RR_レース名_結果.csv」。場名を決め打ちにしない
# （CLAUDE.md「集計スクリプトの競馬場決め打ちに注意」）
RACE_NO_RE = re.compile(r"_\D+?(\d{2})R_")

# 場名とレース番号を両方取る版。`RACE_NO_RE` のグループ1は**レース番号**
# なので、場名が欲しいときにそちらを使うと番号を場名として扱ってしまう
VENUE_NO_RE = re.compile(r"_(\D+?)(\d{2})R_")

# ファイル名の先頭は必ず YYYY-MM-DD
MONTH_RE = re.compile(r"^(\d{4}-\d{2})-\d{2}_")


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


def parse_months(spec: str | None) -> set[str] | None:
    """"2025-01..2025-03" や "2025-01,2026-08" を月の集合にする。

    範囲の区切りは `..`。日付のハイフンとぶつかるので `-` は使わない。
    None/空文字は「絞らない」。
    """
    if not spec:
        return None
    out: set[str] = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if ".." in part:
            lo, hi = (x.strip() for x in part.split("..", 1))
            y, m = (int(x) for x in lo.split("-"))
            ey, em = (int(x) for x in hi.split("-"))
            while (y, m) <= (ey, em):
                out.add(f"{y:04d}-{m:02d}")
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        else:
            out.add(part)
    return out or None


def race_month(name: str) -> str | None:
    """ファイル名・stem から YYYY-MM を取り出す。取れなければ None。"""
    m = MONTH_RE.match(Path(name).name)
    return m.group(1) if m else None


def race_venue(name: str) -> str | None:
    """ファイル名・stem から競馬場名を取り出す。取れなければ None。"""
    m = VENUE_NO_RE.search(Path(name).name + "_")
    return m.group(1) if m else None


def race_number(name: str) -> int | None:
    """ファイル名・stem からレース番号を取り出す。取れなければ None。"""
    m = RACE_NO_RE.search(Path(name).name + "_")
    return int(m.group(1)) if m else None


def result_files(directory: str | Path,
                 races: str | None = DEFAULT_RACES,
                 months: str | None = None) -> list[Path]:
    """対象レース番号（と任意で対象月）の結果CSVを日付順で返す。

    レース番号が取れないファイルは**除外する**。番号が読めないものを
    通すと、絞ったつもりで絞れていない状態になる。月が読めないファイルも
    `months` を指定したときは同じ理由で除外する。
    """
    wanted = parse_races(races)
    want_mo = parse_months(months)
    out = []
    for p in sorted(Path(directory).glob("*_結果.csv")):
        rn = race_number(p.name)
        if rn is None:
            continue
        if wanted is not None and rn not in wanted:
            continue
        if want_mo is not None and race_month(p.name) not in want_mo:
            continue
        out.append(p)
    return out


def result_paths(directory: str | Path,
                 races: str | None = DEFAULT_RACES,
                 months: str | None = None) -> list[str]:
    """`result_files` の str 版（glob.glob を置き換えやすい形）。"""
    return [str(p) for p in result_files(directory, races, months)]


def month_coverage(directory: str | Path,
                   races: str | None = DEFAULT_RACES
                   ) -> dict[str, tuple[int, int]]:
    """月ごとに (その帯で手元にある本数, 開催日から期待される本数) を返す。

    期待本数は「その月の 開催日×場 の数 × 帯のレース番号の個数」。
    開催日は**全帯の結果CSVから数える**ので、1-8Rしか無い日でも
    9-12Rの期待本数に入る（逆も同じ）。

    ## 9-12Rも完全ではない（2026-09-12に判明）

    この関数を書いて初めて分かったが、9-12Rの収集済みコーパスには
    **50本（2.6%）の欠け**がある。9R〜12Rにほぼ均等に散っているので
    「その日は11レースしかなかった」という構造ではなく、収集時に
    落ちた本数と見るのが自然。CLAUDE.mdが「9-12Rは2025-01〜2026-09が
    揃っている」と書いてきた前提は、**97.4%という意味**だった。
    """
    wanted = parse_races(races)
    if wanted is None:
        return {}
    days: dict[str, set[tuple[str, str]]] = {}
    got: dict[str, int] = {}
    for p in Path(directory).glob("*_結果.csv"):
        mo, rn, venue = (race_month(p.name), race_number(p.name),
                         race_venue(p.name))
        if mo is None or rn is None or venue is None:
            continue
        days.setdefault(mo, set()).add((p.name[:10], venue))
        if rn in wanted:
            got[mo] = got.get(mo, 0) + 1
    return {mo: (got.get(mo, 0), len(d) * len(wanted))
            for mo, d in sorted(days.items())}


def complete_months(directory: str | Path,
                    races: str | None = DEFAULT_RACES,
                    ratio: float = 0.9) -> list[str]:
    """その帯が「ほぼ揃っている」月を返す。

    判定は**カバー率**（手元の本数 ÷ 開催日から期待される本数）が
    `ratio` 以上かどうか。最初は「1本でも欠けたら未完了」で書いたが、
    それだと 9-12R でも11ヶ月しか通らなかった（上記の2.6%の欠けに
    引っかかる）。収集途中の月はカバー率が0〜数十%になるので、
    既定の0.9で「収集した月」と「していない月」は明確に分かれる。

    1-8Rの収集が月単位で進むあいだ、**どこまで揃ったかを推測せずに
    調べる**ために使う:

        months = ",".join(complete_months(d, "1-8"))
    """
    return [mo for mo, (got, exp) in month_coverage(directory, races).items()
            if exp and got / exp >= ratio]
