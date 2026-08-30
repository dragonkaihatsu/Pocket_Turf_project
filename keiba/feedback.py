"""レース後のフィードバック（CLAUDE.md 出力形式の5番目）。

予測（印・スコア）と実際の着順を突き合わせ、買い目プランの回収率を計算する。

入力:
    結果CSV: 馬番,着順
    配当CSV（任意）: 券種,組み合わせ,配当
        - 組み合わせは単勝なら馬番1つ、ワイド/馬連は "馬番-馬番"（順不同で照合）
        - 配当は100円あたりの払戻金（円）
        - 的中しなかった組み合わせは記載不要（総払戻には0として扱われる）
"""
from __future__ import annotations

import csv
import html
from dataclasses import dataclass
from pathlib import Path

from .betting import BettingPlan, Ticket
from .marks import MarkedHorse

STAKE_PER_TICKET = 100  # 円


@dataclass
class RaceResult:
    umaban_to_chakujun: dict[int, int]

    @classmethod
    def from_csv(cls, path: str | Path) -> "RaceResult":
        with open(path, encoding="utf-8-sig", newline="") as f:
            m = {}
            for row in csv.DictReader(f):
                try:
                    m[int(row["馬番"])] = int(row["着順"])
                except (KeyError, ValueError, TypeError):
                    continue
        return cls(m)


@dataclass
class Payout:
    kind: str
    combo: frozenset
    amount: int


def load_payouts(path: str | Path) -> list[Payout]:
    payouts = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            combo = frozenset(int(x) for x in row["組み合わせ"].replace("_", "-").split("-") if x.strip())
            payouts.append(Payout(row["券種"], combo, int(row["配当"])))
    return payouts


def _ticket_umaban(ticket) -> frozenset:
    if isinstance(ticket, MarkedHorse):
        return frozenset({ticket.score.horse.umaban})
    return frozenset(m.score.horse.umaban for m in ticket.horses)


def _settle(tickets, kind: str, payouts: list[Payout]) -> tuple[int, int, list[tuple[str, int]]]:
    """(投資額, 払戻額, [(表示ラベル, 払戻額), ...]) を返す。"""
    invest = 0
    payout_total = 0
    detail = []
    for t in tickets:
        invest += STAKE_PER_TICKET
        combo = _ticket_umaban(t)
        hit = next((p for p in payouts if p.kind == kind and p.combo == combo), None)
        amount = hit.amount if hit else 0
        payout_total += amount
        label = t.score.horse.name if isinstance(t, MarkedHorse) else t.label
        detail.append((label, amount))
    return invest, payout_total, detail


def generate_feedback_report(
    race_name: str,
    marked: list[MarkedHorse],
    plan: BettingPlan,
    result: RaceResult,
    payouts: list[Payout] | None,
) -> str:
    payouts = payouts or []

    rows = []
    for m in marked:
        actual = result.umaban_to_chakujun.get(m.score.horse.umaban)
        hit = actual is not None and actual <= 3
        rows.append(
            f"<tr><td>{m.mark}</td><td>{m.score.horse.umaban}</td>"
            f"<td style='text-align:left'>{html.escape(m.score.horse.name)}</td>"
            f"<td>{m.score.total_yoi:.1f}</td>"
            f"<td>{actual if actual is not None else '-'}着</td>"
            f"<td>{'○' if hit else ''}</td></tr>"
        )

    sections = []
    total_invest = total_return = 0
    for kind, tickets in (("単勝", plan.tansho), ("ワイド", plan.wide), ("馬連", plan.umaren)):
        invest, ret, detail = _settle(tickets, kind, payouts)
        total_invest += invest
        total_return += ret
        detail_rows = "".join(
            f"<tr><td>{html.escape(label)}</td><td>{amt:,}円</td></tr>" for label, amt in detail
        )
        rate = (ret / invest * 100) if invest else 0
        sections.append(
            f"<h3 style='font-size:.9rem;margin:14px 0 4px'>{kind}（投資{invest:,}円 / 払戻{ret:,}円 / "
            f"回収率{rate:.0f}%）</h3><table class='wide'>{detail_rows}</table>"
        )

    overall_rate = (total_return / total_invest * 100) if total_invest else 0

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(race_name)} フィードバック</title>
<style>
:root{{color-scheme:dark;--bg:#0f1115;--card:#1a1d24;--fg:#e8e8ec;--muted:#9aa0ac;
--accent:#e0563c;--border:#2a2e37;}}
body{{margin:0;background:var(--bg);color:var(--fg);
font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;padding:12px 12px 48px}}
h1{{font-size:1.15rem}} h2{{font-size:1rem;border-left:4px solid var(--accent);padding-left:8px;margin-top:26px}}
table.wide{{width:100%;border-collapse:collapse;font-size:.85rem}}
table.wide th,table.wide td{{padding:6px 8px;border-bottom:1px solid var(--border);text-align:right}}
table.wide th:nth-child(3),table.wide td:nth-child(3){{text-align:left}}
.summary{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px;margin-top:10px}}
.big{{font-size:1.4rem;font-weight:700}}
</style>
</head>
<body>
<h1>{html.escape(race_name)} レース後フィードバック</h1>

<h2>予測 vs 実際の着順</h2>
<table class="wide"><tr><th>印</th><th>馬番</th><th>馬名</th><th>予測スコア</th><th>実着順</th><th>3着内</th></tr>
{''.join(rows)}</table>

<h2>回収率</h2>
{''.join(sections)}

<div class="summary">
総投資: {total_invest:,}円 ／ 総払戻: {total_return:,}円<br>
<span class="big">回収率 {overall_rate:.0f}%</span>
</div>
</body>
</html>
"""
