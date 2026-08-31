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


def _confirmed_outside_top_n(result: RaceResult, umaban: int, n: int) -> bool:
    """umaban の着順が n位以内ではないと確定できるか。

    結果CSVには「上位n頭のうち何頭か」しか記載されていないケースがある
    （例: 1〜3着だけ分かっていて、他馬の着順は空欄）。その場合でも、
    1位〜n位の枠が既に他の馬で全て埋まっていれば、この馬はそこに入り
    得ない＝n位以内ではないと確定できる（クローズドワールド推論）。
    """
    c = result.umaban_to_chakujun.get(umaban)
    if c is not None:
        return c > n
    ranks_taken_by_others = {
        rc for u, rc in result.umaban_to_chakujun.items()
        if u != umaban and rc is not None and rc <= n
    }
    return ranks_taken_by_others == set(range(1, n + 1))


def _is_hit(kind: str, combo: frozenset, result: RaceResult) -> bool | None:
    """実際の着順から、配当データなしでも的中/不的中を判定する。
    判定に必要な着順情報が欠けている場合は None（判定不能）を返す。
    """
    chakujun = {u: result.umaban_to_chakujun.get(u) for u in combo}

    if kind == "単勝":
        (u,) = tuple(combo)
        c = chakujun[u]
        if c is not None:
            return c == 1
        return False if _confirmed_outside_top_n(result, u, 1) else None

    if kind in ("ワイド", "馬連"):
        n = 3 if kind == "ワイド" else 2
        for u in combo:
            c = chakujun[u]
            if c is not None and c > n:
                return False  # 明示的に n位より下→外れ確定
            if c is None and _confirmed_outside_top_n(result, u, n):
                return False  # 他馬で n位までの枠が埋まっている→この馬は入れない＝外れ確定
        if all(chakujun[u] is not None and chakujun[u] <= n for u in combo):
            if kind == "ワイド":
                return True
            return sorted(chakujun[u] for u in combo) == [1, 2]
        return None  # 的中/不的中を確定できない

    return None


def _settle(
    tickets, kind: str, payouts: list[Payout], result: RaceResult
) -> tuple[int, int | None, list[tuple[str, bool | None, int | None]]]:
    """(投資額, 払戻額(不明なら None), [(表示ラベル, 的中?, 配当円 or None), ...]) を返す。"""
    invest = 0
    payout_total = 0
    payout_unknown = False
    detail = []
    for t in tickets:
        invest += STAKE_PER_TICKET
        combo = _ticket_umaban(t)
        hit = _is_hit(kind, combo, result)
        matched_payout = next((p for p in payouts if p.kind == kind and p.combo == combo), None)
        amount = matched_payout.amount if matched_payout else None
        if hit is None:
            payout_unknown = True  # 的中したかどうか自体が不明→総払戻も不明
        elif hit:
            if amount is None:
                payout_unknown = True
            else:
                payout_total += amount
        label = t.score.horse.name if isinstance(t, MarkedHorse) else t.label
        detail.append((label, hit, amount))
    return invest, (None if payout_unknown else payout_total), detail


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
    total_invest = 0
    total_return = 0
    rate_unknown = False
    for kind, tickets in (("単勝", plan.tansho), ("ワイド", plan.wide), ("馬連", plan.umaren)):
        invest, ret, detail = _settle(tickets, kind, payouts, result)
        total_invest += invest
        if ret is None:
            rate_unknown = True
        else:
            total_return += ret

        def _hit_label(hit: bool | None) -> str:
            return "○的中" if hit else ("？判定不能" if hit is None else "✕ハズレ")

        detail_rows = "".join(
            f"<tr><td>{html.escape(label)}</td><td>{_hit_label(hit)}</td>"
            f"<td>{f'{amt:,}円' if amt is not None else ('-' if not hit else '配当不明')}</td></tr>"
            for label, hit, amt in detail
        )
        rate_str = f"{ret / invest * 100:.0f}%" if (ret is not None and invest) else "配当データ不足のため不明"
        sections.append(
            f"<h3 style='font-size:.9rem;margin:14px 0 4px'>{kind}（投資{invest:,}円 / "
            f"払戻{f'{ret:,}円' if ret is not None else '不明'} / 回収率{rate_str}）</h3>"
            f"<table class='wide'><tr><th>買い目</th><th>結果</th><th>配当</th></tr>{detail_rows}</table>"
        )

    overall_rate_str = (
        f"{total_return / total_invest * 100:.0f}%"
        if (not rate_unknown and total_invest)
        else "一部配当データ不足のため算出不可"
    )

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
総投資: {total_invest:,}円 ／ 総払戻: {f'{total_return:,}円' if not rate_unknown else '一部不明'}<br>
<span class="big">回収率 {overall_rate_str}</span>
</div>
</body>
</html>
"""
