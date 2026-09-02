"""収集した結果コーパスからコース傾向を集計する。

`stats` が「自分の予想が当たったか」を見るのに対し、こちらは
「そのコースがどういう性質か」を見る。CLAUDE.md が求める
「過去データの枠別・年齢別などの統計的裏付け」を用意するための機能。

集計軸:
  1. 人気別成績     … 市場評価の効き方（人気が堅いコースかどうか）
  2. 枠番別成績     … 枠順補正の根拠
  3. 4角通過順位別  … 前残りか差し決着か。脚質評価の根拠
  4. 距離別の前残り度 … 同じ競馬場でも距離で傾向が変わるため

母数が小さい区分は結論に使わないこと。各表に必ず頭数を併記する。
"""
from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

MIN_SAMPLE = 30  # この頭数を下回る区分は参考値として扱う


def parse_passing_order(text: str) -> dict[int, int]:
    """コーナー通過順位の文字列を {馬番: 通過順位} に変換する。

    '2,6,(5,12),(3,8),1' のように、括弧でくくられた馬は同じ位置（横並び）を
    表すため、同一順位として扱う。
    """
    positions: dict[int, int] = {}
    rank = 0
    for token in re.findall(r"\((?:\d+,?)+\)|\d+", text):
        rank += 1
        for n in re.findall(r"\d+", token):
            positions[int(n)] = rank
    return positions


@dataclass
class Runner:
    chakujun: int
    umaban: int
    wakuban: int | None
    ninki: int | None
    corner4: int | None
    field_size: int
    race: str
    kyori: int | None = None


@dataclass
class Corpus:
    runners: list[Runner] = field(default_factory=list)
    races: set[str] = field(default_factory=set)

    def __len__(self) -> int:
        return len(self.runners)


def _to_int(v: str | None) -> int | None:
    return int(v) if v and v.strip().isdigit() else None


def load_corpus(directory: str | Path, kyori: int | None = None) -> Corpus:
    """`collect` が書き出したCSV群を読み込む。kyori を指定すると距離で絞る。"""
    directory = Path(directory)
    corpus = Corpus()

    for result_path in sorted(directory.glob("*_結果.csv")):
        stem = result_path.name.replace("_結果.csv", "")

        corner_path = directory / f"{stem}_通過順.csv"
        corner4: dict[int, int] = {}
        if corner_path.exists():
            with open(corner_path, encoding="utf-8") as f:
                corners = {r["コーナー"]: r["通過順"] for r in csv.DictReader(f)}
            text = corners.get("4コーナー") or corners.get("3コーナー")
            if text:
                corner4 = parse_passing_order(text)

        with open(result_path, encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if _to_int(r.get("着順"))]
        if not rows:
            continue

        race_kyori = None
        if m := re.search(r"(\d{3,4})m", stem):
            race_kyori = int(m.group(1))
        if kyori is not None and race_kyori is not None and race_kyori != kyori:
            continue

        corpus.races.add(stem)
        for r in rows:
            umaban = _to_int(r.get("馬番"))
            if umaban is None:
                continue
            corpus.runners.append(Runner(
                chakujun=_to_int(r["着順"]),
                umaban=umaban,
                wakuban=_to_int(r.get("枠番")),
                ninki=_to_int(r.get("人気")),
                corner4=corner4.get(umaban),
                field_size=len(rows),
                race=stem,
                kyori=race_kyori,
            ))
    return corpus


def _rates(runners: list[Runner]) -> dict:
    n = len(runners)
    if n == 0:
        return {"頭数": 0, "勝率": None, "連対率": None, "複勝率": None}
    return {
        "頭数": n,
        "勝率": sum(1 for r in runners if r.chakujun == 1) / n,
        "連対率": sum(1 for r in runners if r.chakujun <= 2) / n,
        "複勝率": sum(1 for r in runners if r.chakujun <= 3) / n,
    }


def tally_by_ninki(corpus: Corpus, upto: int = 10) -> dict[int, dict]:
    buckets = defaultdict(list)
    for r in corpus.runners:
        if r.ninki and r.ninki <= upto:
            buckets[r.ninki].append(r)
    return {k: _rates(v) for k, v in sorted(buckets.items())}


def tally_by_wakuban(corpus: Corpus) -> dict[int, dict]:
    buckets = defaultdict(list)
    for r in corpus.runners:
        if r.wakuban:
            buckets[r.wakuban].append(r)
    return {k: _rates(v) for k, v in sorted(buckets.items())}


CORNER_BUCKETS = [("1番手", 1, 1), ("2番手", 2, 2), ("3番手", 3, 3),
                  ("4番手", 4, 4), ("5番手", 5, 5),
                  ("6-8番手", 6, 8), ("9番手以下", 9, 99)]


def tally_by_corner(corpus: Corpus) -> dict[str, dict]:
    buckets = {label: [] for label, _, _ in CORNER_BUCKETS}
    for r in corpus.runners:
        if r.corner4 is None:
            continue
        for label, lo, hi in CORNER_BUCKETS:
            if lo <= r.corner4 <= hi:
                buckets[label].append(r)
                break
    return {k: _rates(v) for k, v in buckets.items()}


def winner_corner_distribution(corpus: Corpus) -> dict:
    """勝ち馬が4コーナーで何番手だったかの分布（前残り度の指標）。"""
    winners = [r.corner4 for r in corpus.runners if r.chakujun == 1 and r.corner4]
    if not winners:
        return {"勝ち馬数": 0}
    c = Counter(winners)
    total = len(winners)
    return {
        "勝ち馬数": total,
        "分布": {p: c[p] for p in sorted(c)},
        "3番手以内の割合": sum(v for k, v in c.items() if k <= 3) / total,
        "5番手以内の割合": sum(v for k, v in c.items() if k <= 5) / total,
    }


def analyze(corpus: Corpus) -> dict:
    return {
        "レース数": len(corpus.races),
        "延べ頭数": len(corpus),
        "人気別": tally_by_ninki(corpus),
        "枠番別": tally_by_wakuban(corpus),
        "4角通過順位別": tally_by_corner(corpus),
        "勝ち馬の4角位置": winner_corner_distribution(corpus),
    }


def _pct(v: float | None) -> str:
    return "    -" if v is None else f"{v:>6.1%}"


def _table(title: str, rows: dict, label_width: int = 10) -> list[str]:
    out = ["", f"── {title} " + "─" * max(2, 56 - len(title))]
    out.append(f"{'':<{label_width}}{'頭数':>6}{'勝率':>8}{'連対率':>8}{'複勝率':>8}")
    for key, r in rows.items():
        if not r["頭数"]:
            continue
        warn = " ※母数少" if r["頭数"] < MIN_SAMPLE else ""
        out.append(f"{str(key):<{label_width}}{r['頭数']:>6}"
                   f"{_pct(r['勝率'])}{_pct(r['連対率'])}{_pct(r['複勝率'])}{warn}")
    return out


def format_report(a: dict) -> str:
    lines = ["=" * 64,
             f" コース傾向の集計（{a['レース数']}レース / 延べ{a['延べ頭数']}頭）",
             "=" * 64]

    lines += _table("人気別成績", a["人気別"], label_width=10)
    lines += _table("枠番別成績", {f"{k}枠": v for k, v in a["枠番別"].items()})
    lines += _table("4コーナー通過順位別成績", a["4角通過順位別"])

    w = a["勝ち馬の4角位置"]
    if w.get("勝ち馬数"):
        lines += ["", "── 勝ち馬は4コーナーで何番手だったか " + "─" * 24]
        total = w["勝ち馬数"]
        cum = 0
        for p, c in w["分布"].items():
            cum += c
            if p <= 8:
                lines.append(f"  {p}番手から勝利: {c:>3}回 ({c/total:>5.1%})  累計 {cum/total:>5.1%}")
        lines += [
            "",
            f"  勝ち馬の {w['3番手以内の割合']:.0%} が4角3番手以内、"
            f"{w['5番手以内の割合']:.0%} が5番手以内",
        ]

    lines += [
        "",
        "─" * 64,
        "注意: 4コーナーの位置はレース結果であって、事前に分かる情報ではない。",
        "      「差し馬を買うな」ではなく「前を取れる馬を評価せよ」と読むこと。",
        f"      頭数が{MIN_SAMPLE}未満の区分は偶然の影響が大きいため参考値。",
        "      枠番別は距離が混在しており、少頭数戦では内枠の頭数自体が少ない点に注意。",
    ]
    return "\n".join(lines)
