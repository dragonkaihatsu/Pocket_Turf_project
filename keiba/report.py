"""HTML出力（CLAUDE.md 出力形式の1・2・3・4をまとめた単一HTMLファイル）。

スマホ対応・ダークテーマ・タップで詳細展開・馬番順/スコア順トグルを持つ、
外部依存なしの自己完結HTMLを生成する。
"""
from __future__ import annotations

import html
from datetime import date

from .betting import BettingPlan, Ticket
from .boxes import build_options
from .expectation import Expectation
from .marks import MarkedHorse
from .pace import PaceForecast
from .scoring import HorseScore

_STYLE = """
:root{color-scheme:dark;--bg:#0f1115;--card:#1a1d24;--card2:#20242c;--fg:#e8e8ec;
--muted:#9aa0ac;--accent:#e0563c;--good:#4caf7d;--bad:#e0563c;--border:#2a2e37;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif;padding:12px 12px 48px}
h1{font-size:1.15rem;margin:4px 0 2px}
h2{font-size:1rem;margin:28px 0 10px;border-left:4px solid var(--accent);padding-left:8px}
.sub{color:var(--muted);font-size:.8rem;margin-bottom:16px}
.toggle-row{display:flex;gap:8px;margin-bottom:12px}
.toggle-row button{flex:1;padding:8px;border-radius:8px;border:1px solid var(--border);
background:var(--card2);color:var(--fg);font-size:.85rem}
.toggle-row button.active{background:var(--accent);border-color:var(--accent);color:#fff}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;
margin-bottom:8px;overflow:hidden}
.card summary{list-style:none;padding:10px 12px;display:flex;align-items:center;gap:10px;cursor:pointer}
.card summary::-webkit-details-marker{display:none}
.mark{font-weight:700;width:1.6em;text-align:center;color:var(--accent)}
.umaban{background:var(--card2);border-radius:6px;padding:1px 7px;font-size:.8rem;color:var(--muted)}
.name{flex:1;font-weight:600}
.score{font-weight:700}
.score .sub-score{font-size:.72rem;color:var(--muted);font-weight:400;display:block}
.detail{padding:0 12px 12px;font-size:.82rem;color:var(--muted)}
.detail table{width:100%;border-collapse:collapse;margin-top:4px}
.detail td{padding:2px 4px;border-bottom:1px solid var(--border)}
.detail td.pt{text-align:right;font-variant-numeric:tabular-nums}
.pos{color:var(--good)} .neg{color:var(--bad)}
table.wide{width:100%;border-collapse:collapse;font-size:.82rem;overflow-x:auto;display:block}
table.wide th,table.wide td{padding:6px 8px;border-bottom:1px solid var(--border);white-space:nowrap;text-align:right}
table.wide th:first-child,table.wide td:first-child{text-align:left}
.note{font-size:.78rem;color:var(--muted);margin-top:6px}
.pace-bar{display:flex;height:22px;border-radius:6px;overflow:hidden;margin:8px 0}
.pace-bar span{display:flex;align-items:center;justify-content:center;font-size:.72rem;color:#fff}
.tickets{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.tickets .t{background:var(--card2);border:1px solid var(--border);border-radius:6px;padding:4px 8px;font-size:.8rem}
"""

_SCRIPT = """
function switchOrder(order){
  document.getElementById('cards-umaban').hidden = (order !== 'umaban');
  document.getElementById('cards-score').hidden = (order !== 'score');
  document.getElementById('btn-umaban').classList.toggle('active', order==='umaban');
  document.getElementById('btn-score').classList.toggle('active', order==='score');
}
"""


def _fmt(n: float) -> str:
    return f"{n:+.1f}" if n else "0.0"


def _cls(n: float) -> str:
    return "pos" if n > 0 else ("neg" if n < 0 else "")


def _breakdown_table(score: HorseScore) -> str:
    rows = []
    for item in score.base_items:
        rows.append(f"<tr><td>{html.escape(item.label)}</td><td class='pt'>{item.points:.1f}</td>"
                     f"<td>{html.escape(item.note)}</td></tr>")
    rows.append(f"<tr><td><b>小計(85点満点)</b></td><td class='pt'><b>{score.base_subtotal:.1f}</b></td><td></td></tr>")
    for item in score.corrections:
        rows.append(f"<tr><td>{html.escape(item.label)}</td>"
                     f"<td class='pt {_cls(item.points)}'>{_fmt(item.points)}</td>"
                     f"<td>{html.escape(item.note)}</td></tr>")
    rows.append(f"<tr><td>馬場状態補正レイヤー(重馬場側)</td>"
                f"<td class='pt {_cls(score._baba_delta)}'>{_fmt(score._baba_delta)}</td>"
                f"<td>{html.escape(score.baba_note)}</td></tr>")
    rows.append(f"<tr><td><b>良馬場スコア</b></td><td class='pt'><b>{score.total_yoi:.1f}</b></td><td></td></tr>")
    rows.append(f"<tr><td><b>重馬場スコア</b></td><td class='pt'><b>{score.total_omoi:.1f}</b></td><td></td></tr>")
    return "<table>" + "".join(rows) + "</table>"


def _mark_of(umaban: int, marked: list[MarkedHorse]) -> str:
    for m in marked:
        if m.score.horse.umaban == umaban:
            return m.mark
    return ""


def _card(score: HorseScore, marked: list[MarkedHorse]) -> str:
    mark = _mark_of(score.horse.umaban, marked)
    return (
        f"<details class='card'><summary>"
        f"<span class='mark'>{mark}</span>"
        f"<span class='umaban'>{score.horse.umaban}</span>"
        f"<span class='name'>{html.escape(score.horse.name)}</span>"
        f"<span class='score'>{score.total_yoi:.1f}<span class='sub-score'>重{score.total_omoi:.1f}</span></span>"
        f"</summary><div class='detail'>{_breakdown_table(score)}</div></details>"
    )


def _score_table(scores: list[HorseScore], marked: list[MarkedHorse],
                 exp: Expectation) -> str:
    header = ("<tr><th>順位</th><th>印</th><th>馬番</th><th>馬名</th><th>基礎能力</th><th>前走内容</th>"
              "<th>コース適性</th><th>距離適性</th><th>調教</th><th>小計85</th>"
              "<th>補正計</th><th>良馬場</th><th>重馬場</th>"
              "<th>1着期待度</th><th>着内期待度</th></tr>")
    rows = []
    for rank, s in enumerate(sorted(scores, key=lambda s: s.total_yoi, reverse=True), start=1):
        cells = [f"<td>{i.points:.1f}</td>" for i in s.base_items]
        win_pct, place_pct = exp.format(rank)
        rows.append(
            f"<tr><td>{rank}</td><td>{_mark_of(s.horse.umaban, marked) or '—'}</td>"
            f"<td>{s.horse.umaban}</td>"
            f"<td style='text-align:left'>{html.escape(s.horse.name)}</td>{''.join(cells)}"
            f"<td><b>{s.base_subtotal:.1f}</b></td>"
            f"<td class='{_cls(s.correction_subtotal)}'>{_fmt(s.correction_subtotal)}</td>"
            f"<td><b>{s.total_yoi:.1f}</b></td><td><b>{s.total_omoi:.1f}</b></td>"
            f"<td>{win_pct}</td><td>{place_pct}</td></tr>"
        )
    return (f"<table class='wide'>{header}{''.join(rows)}</table>"
            f"<div class='note'>{html.escape(exp.source_note)}</div>")


def _pace_section(pace: PaceForecast) -> str:
    colors = {"ハイ": "#e0563c", "ミドル": "#d8a83c", "スロー": "#4caf7d"}
    bar = "".join(
        f"<span style='width:{p*100:.0f}%;background:{colors[k]}'>{k}{p:.0%}</span>"
        for k, p in pace.probabilities.items() if p > 0
    )
    favored_lines = []
    for k, hs in pace.favored.items():
        names = "、".join(html.escape(h.name) for h in hs) or "該当なし"
        favored_lines.append(f"<div><b>{k}ペース想定時に浮上:</b> {names}</div>")
    counts = "・".join(f"{k}{v}頭" for k, v in pace.counts.items())
    return (
        f"<div class='pace-bar'>{bar}</div>"
        f"<div class='note'>脚質構成: {counts}</div>"
        f"<div class='note'>{html.escape(pace.note)}</div>"
        + "".join(favored_lines)
    )


def _tickets_html(tickets: list[Ticket]) -> str:
    return "<div class='tickets'>" + "".join(f"<span class='t'>{html.escape(t.label)}</span>" for t in tickets) + "</div>"


def _betting_section(plan: BettingPlan) -> str:
    parts = [
        f"<div class='note'>買い目タイプ: <b>{html.escape(plan.strategy)}型</b>"
        f"（計{plan.total_points}点）</div>"
    ]
    if plan.tansho:
        tansho = "、".join(
            f"{m.score.horse.umaban}{m.mark}{html.escape(m.score.horse.name)}" for m in plan.tansho
        )
        parts.append(f"<h3 style='font-size:.9rem;margin:14px 0 4px'>単勝（{len(plan.tansho)}点）</h3>"
                     f"<div class='note'>{tansho}</div>")
    if plan.wide:
        parts.append(f"<h3 style='font-size:.9rem;margin:14px 0 4px'>ワイド（{len(plan.wide)}点）</h3>"
                     f"{_tickets_html(plan.wide)}")
    if plan.umaren:
        parts.append(f"<h3 style='font-size:.9rem;margin:14px 0 4px'>馬連（{len(plan.umaren)}点）</h3>"
                     f"{_tickets_html(plan.umaren)}")
    parts.append(f"<div class='note'>{html.escape(plan.note)}</div>")
    return "".join(parts)


def _box_options_section(marked: list[MarkedHorse], plan: BettingPlan) -> str:
    """点数別の買い目候補。広げるかどうかは買う人が決めるため、実測値を併記する。"""
    order = [m.score.horse.umaban for m in marked]
    rec = ("ワイド", 3) if plan.wide else ("馬連", 4)
    options = build_options(order, favorite_odds=plan.favorite_odds, recommended=rec)
    if not options:
        return ""
    rows = []
    for o in options:
        st = o.stats
        nums = "-".join(str(u) for u in o.umaban)
        cells = (f"<td>{o.stats['的中率']:.0%}</td><td>{st['回収率']:.0%}</td>"
                 f"<td>{st['区間下']:.0%}〜{st['区間上']:.0%}</td>"
                 f"<td>{st['黒字確率']:.0%}</td>" if st
                 else "<td>—</td><td>—</td><td>—</td><td>—</td>")
        mark = "★" if o.recommended else ""
        style = " style='background:var(--card2)'" if o.recommended else ""
        rows.append(f"<tr{style}><td style='text-align:left'>{mark}{html.escape(o.kind)}"
                    f" 上位{o.width}頭</td><td>{o.points}点</td>"
                    f"<td style='text-align:left'>{nums}</td>{cells}</tr>")
    return (
        "<table class='wide'><tr><th>買い方</th><th>点数</th><th>馬番</th>"
        "<th>的中率</th><th>回収率</th><th>90%区間</th><th>黒字確率</th></tr>"
        + "".join(rows) + "</table>"
        "<div class='note'>★がシステムの推奨。数字は大井9-12Rの実測（同じ1番人気オッズ帯）。"
        "頭数を増やすと的中率は上がるが回収率は下がる。どこまで広げるかは買う人が決める。</div>"
    )


def generate_report(
    race_name: str,
    scores: list[HorseScore],
    marked: list[MarkedHorse],
    pace: PaceForecast,
    plan: BettingPlan,
    baba: str,
    exp: Expectation | None = None,
) -> str:
    exp = exp if exp is not None else Expectation()
    by_umaban = sorted(scores, key=lambda s: s.horse.umaban)
    by_score = sorted(scores, key=lambda s: s.total_yoi, reverse=True)

    cards_umaban = "".join(_card(s, marked) for s in by_umaban)
    cards_score = "".join(_card(s, marked) for s in by_score)

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(race_name)} 予想</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>{html.escape(race_name)} 予想スコアリング</h1>
<div class="sub">出力日: {date.today().isoformat()} ／ 当日馬場想定: {html.escape(baba)}</div>

<h2>1. 100点スコアリング表（良馬場・重馬場併記）</h2>
{_score_table(scores, marked, exp)}

<h2>2. 出走馬カード</h2>
<div class="toggle-row">
  <button id="btn-umaban" class="active" onclick="switchOrder('umaban')">馬番順</button>
  <button id="btn-score" onclick="switchOrder('score')">スコア順</button>
</div>
<div id="cards-umaban">{cards_umaban}</div>
<div id="cards-score" hidden>{cards_score}</div>

<h2>3. ペース別展開予想</h2>
{_pace_section(pace)}

<h2>4. 買い目プラン</h2>
{_betting_section(plan)}

<h2>5. 点数別の買い目候補（参考）</h2>
{_box_options_section(marked, plan)}

<script>{_SCRIPT}</script>
</body>
</html>
"""
