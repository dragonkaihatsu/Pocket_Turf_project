"""予想成績のレース横断集計。

`feedback` は1レース単位の振り返りだが、こちらは結果が判明している
全レースをまたいで集計する。学習事項を「1レースの印象」ではなく
数字で裏付けるための土台。

集計する軸:
  1. 印別成績   … ◎○▲△注／無印ごとの勝率・連対率・複勝率
  2. スコア帯別 … 良馬場スコアの帯ごとの複勝率（配点が効いているかの検証）
  3. 券種別収支 … 単勝・ワイド・馬連の的中点数と回収率
  4. レース別   … ◎の着順と、券種ごとの的中状況

入力は `daily` コマンドと同じ開催日設定JSON。`result` が指定された
レースだけが集計対象になる。

母数が小さいうちは結論を出さないこと。各表に必ず母数(頭数・レース数)を
併記し、レース数が少ない場合は警告を出す。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .betting import BettingPlan, make_betting_plan
from .daily import RaceEntry
from .feedback import (
    STAKE_PER_TICKET,
    Payout,
    RaceResult,
    is_outside_top,
    load_payouts,
    ticket_hit,
)
from .marks import MarkedHorse, assign_marks
from .models import load_history, load_horses
from .scoring import HorseScore, score_race

MARK_ORDER = ["◎", "○", "▲", "△", "注", "無印"]
SCORE_BANDS = [(65, None), (60, 65), (55, 60), (50, 55), (45, 50), (None, 45)]
MIN_RACES_FOR_CONCLUSION = 20


@dataclass
class RaceRecord:
    """結果が判明している1レース分の記録。"""

    label: str
    scores: list[HorseScore]
    marked: list[MarkedHorse]
    plan: BettingPlan
    result: RaceResult
    payouts: list[Payout] = field(default_factory=list)

    def mark_of(self, umaban: int) -> str:
        for m in self.marked:
            if m.score.horse.umaban == umaban:
                return m.mark
        return "無印"

    def position_of(self, umaban: int) -> int | None:
        """着順。3着以内が全て判明していれば、圏外の馬は 4 として扱う。
        判定できない場合は None（集計の母数から除外する）。
        """
        pos = self.result.umaban_to_chakujun.get(umaban)
        if pos is not None:
            return pos
        return 4 if is_outside_top(self.result, umaban, 3) else None


def load_records(config_paths: list[str | Path]) -> tuple[list[RaceRecord], list[str]]:
    """設定JSONを読み、結果があるレースだけ RaceRecord にする。
    戻り値は (記録, スキップしたレースの説明)。
    """
    records: list[RaceRecord] = []
    skipped: list[str] = []

    for path in config_paths:
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
        day = config.get("heading") or config.get("title") or str(path)

        for raw in config["races"]:
            race = RaceEntry.from_dict(raw)
            label = f"{day} {race.race_no} {race.name}"
            if not race.result:
                skipped.append(f"{label}（結果未入力）")
                continue

            horses = load_horses(race.entries)
            history = load_history(race.history) if race.history else None
            scores = score_race(horses, history, kyori=race.kyori)
            marked = assign_marks(scores, baba=race.baba)
            records.append(
                RaceRecord(
                    label=label,
                    scores=scores,
                    marked=marked,
                    plan=make_betting_plan(marked, baba=race.baba),
                    result=RaceResult.from_csv(race.result),
                    payouts=load_payouts(race.payouts) if race.payouts else [],
                )
            )
    return records, skipped


def _rate_row(positions: list[int]) -> dict:
    n = len(positions)
    if n == 0:
        return {"出走": 0, "1着": 0, "2着": 0, "3着": 0, "着外": 0,
                "勝率": None, "連対率": None, "複勝率": None}
    first = sum(1 for p in positions if p == 1)
    second = sum(1 for p in positions if p == 2)
    third = sum(1 for p in positions if p == 3)
    return {
        "出走": n, "1着": first, "2着": second, "3着": third,
        "着外": n - first - second - third,
        "勝率": first / n,
        "連対率": (first + second) / n,
        "複勝率": (first + second + third) / n,
    }


def tally_by_mark(records: list[RaceRecord]) -> dict[str, dict]:
    buckets: dict[str, list[int]] = {m: [] for m in MARK_ORDER}
    for rec in records:
        for s in rec.scores:
            pos = rec.position_of(s.horse.umaban)
            if pos is None:
                continue
            buckets[rec.mark_of(s.horse.umaban)].append(pos)
    return {m: _rate_row(ps) for m, ps in buckets.items()}


def _band_label(lo: float | None, hi: float | None) -> str:
    if lo is None:
        return f"〜{hi:.0f}点"
    if hi is None:
        return f"{lo:.0f}点〜"
    return f"{lo:.0f}〜{hi:.0f}点"


def tally_by_score_band(records: list[RaceRecord]) -> dict[str, dict]:
    buckets: dict[str, list[int]] = {_band_label(lo, hi): [] for lo, hi in SCORE_BANDS}
    for rec in records:
        for s in rec.scores:
            pos = rec.position_of(s.horse.umaban)
            if pos is None:
                continue
            for lo, hi in SCORE_BANDS:
                if (lo is None or s.total_yoi >= lo) and (hi is None or s.total_yoi < hi):
                    buckets[_band_label(lo, hi)].append(pos)
                    break
    return {b: _rate_row(ps) for b, ps in buckets.items()}


def tally_by_ticket(records: list[RaceRecord]) -> dict[str, dict]:
    out = {}
    for kind in ("単勝", "ワイド", "馬連"):
        points = hits = unknown = 0
        invest = 0
        payout = 0
        payout_unknown = False
        for rec in records:
            tickets = {"単勝": rec.plan.tansho, "ワイド": rec.plan.wide,
                       "馬連": rec.plan.umaren}[kind]
            for t in tickets:
                points += 1
                invest += STAKE_PER_TICKET
                hit = ticket_hit(kind, t, rec.result)
                if hit is None:
                    unknown += 1
                    payout_unknown = True
                elif hit:
                    hits += 1
                    combo = frozenset(
                        {t.score.horse.umaban} if isinstance(t, MarkedHorse)
                        else {mh.score.horse.umaban for mh in t.horses}
                    )
                    match = next(
                        (p for p in rec.payouts if p.kind == kind and p.combo == combo), None
                    )
                    if match:
                        payout += match.amount
                    else:
                        payout_unknown = True
        out[kind] = {
            "点数": points, "的中": hits, "判定不能": unknown,
            "投資": invest,
            "払戻": None if payout_unknown else payout,
            "回収率": None if (payout_unknown or not invest) else payout / invest,
        }
    return out


def tally_by_race(records: list[RaceRecord]) -> list[dict]:
    rows = []
    for rec in records:
        honmei = next((m for m in rec.marked if m.mark == "◎"), None)
        row = {
            "レース": rec.label,
            "◎": f"{honmei.score.horse.umaban}{honmei.score.horse.name}" if honmei else "-",
            "◎着順": rec.position_of(honmei.score.horse.umaban) if honmei else None,
        }
        for kind in ("単勝", "ワイド", "馬連"):
            tickets = {"単勝": rec.plan.tansho, "ワイド": rec.plan.wide,
                       "馬連": rec.plan.umaren}[kind]
            results = [ticket_hit(kind, t, rec.result) for t in tickets]
            row[kind] = (
                "的中" if any(r is True for r in results)
                else ("判定不能" if any(r is None for r in results) else "ハズレ")
            )
        rows.append(row)
    return rows


def aggregate(records: list[RaceRecord]) -> dict:
    return {
        "レース数": len(records),
        "印別成績": tally_by_mark(records),
        "スコア帯別成績": tally_by_score_band(records),
        "券種別収支": tally_by_ticket(records),
        "レース別": tally_by_race(records),
    }


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{v * 100:5.1f}%"


def format_report(agg: dict, skipped: list[str]) -> str:
    n_races = agg["レース数"]
    lines = ["=" * 66, f" 予想成績の集計（対象 {n_races} レース）", "=" * 66]

    if n_races == 0:
        lines.append("\n結果が入力されたレースがありません。")
        if skipped:
            lines.append("スキップ: " + " / ".join(skipped))
        return "\n".join(lines)

    if n_races < MIN_RACES_FOR_CONCLUSION:
        lines += [
            "",
            f"【注意】母数が {n_races} レースしかありません。",
            f"      印別・スコア帯別の率は偶然の影響が大きく、"
            f"配点変更の根拠には使えません",
            f"      （目安として {MIN_RACES_FOR_CONCLUSION} レース以上）。",
        ]

    lines += ["", "── 印別成績 " + "─" * 52,
              f"{'印':<4}{'出走':>5}{'1着':>5}{'2着':>5}{'3着':>5}{'着外':>5}"
              f"{'勝率':>8}{'連対率':>9}{'複勝率':>9}"]
    for mark, r in agg["印別成績"].items():
        if r["出走"] == 0:
            continue
        lines.append(
            f"{mark:<4}{r['出走']:>5}{r['1着']:>5}{r['2着']:>5}{r['3着']:>5}{r['着外']:>5}"
            f"{_pct(r['勝率']):>9}{_pct(r['連対率']):>10}{_pct(r['複勝率']):>10}"
        )

    lines += ["", "── スコア帯別成績（良馬場スコア） " + "─" * 31,
              f"{'帯':<12}{'頭数':>5}{'1着':>5}{'2着':>5}{'3着':>5}{'複勝率':>10}"]
    for band, r in agg["スコア帯別成績"].items():
        if r["出走"] == 0:
            continue
        lines.append(
            f"{band:<12}{r['出走']:>5}{r['1着']:>5}{r['2着']:>5}{r['3着']:>5}"
            f"{_pct(r['複勝率']):>11}"
        )

    lines += ["", "── 券種別収支（1点100円） " + "─" * 39,
              f"{'券種':<7}{'点数':>5}{'的中':>5}{'投資':>9}{'払戻':>10}{'回収率':>10}"]
    for kind, r in agg["券種別収支"].items():
        payout = "不明" if r["払戻"] is None else f"{r['払戻']:,}円"
        rate = "-" if r["回収率"] is None else f"{r['回収率'] * 100:.0f}%"
        note = f"  ※判定不能{r['判定不能']}点" if r["判定不能"] else ""
        lines.append(
            f"{kind:<7}{r['点数']:>5}{r['的中']:>5}{r['投資']:>8,}円{payout:>11}{rate:>10}{note}"
        )
    if any(r["払戻"] is None for r in agg["券種別収支"].values()):
        lines.append("  ※ 配当CSVが無いレースがあるため、回収率は算出していません。")

    lines += ["", "── レース別 " + "─" * 52]
    for row in agg["レース別"]:
        pos = f"{row['◎着順']}着" if row["◎着順"] else "不明"
        lines.append(
            f"{row['レース']}\n"
            f"    ◎{row['◎']} → {pos}   "
            f"単勝:{row['単勝']} / ワイド:{row['ワイド']} / 馬連:{row['馬連']}"
        )

    if skipped:
        lines += ["", "── 集計対象外 " + "─" * 50]
        lines += [f"  {s}" for s in skipped]

    return "\n".join(lines)
