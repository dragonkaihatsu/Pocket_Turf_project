"""開催日単位のArtifact向けページ生成。

CLAUDE.md の出力形式1〜5を1ページにまとめた、共有用の自己完結HTMLを作る。
Artifact として publish する前提のため、<!doctype>/<html>/<head>/<body> は
出力しない（publish時にラップされる）。

デザイン方針:
- CLAUDE.md が指定する「ダークテーマ・スマホ対応・タップで詳細展開・
  馬番順/スコア順トグル」を満たす
- 配色は大井のナイター開催（トゥインクルレース）から: 夜空の紺地に、
  照明に照らされたダートの砂色をアクセントに置く
- 枠番は実際の枠色（1白・2黒・3赤・4青・5黄・6緑・7橙・8桃）で表示する
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

from .betting import BettingPlan, make_betting_plan
from .feedback import RaceResult, ticket_hit
from .marks import MarkedHorse, assign_marks
from .models import Horse, load_history, load_horses
from .pace import PaceForecast, forecast_pace
from .scoring import HorseScore, score_race

FONTS = (
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=Barlow+Condensed:wght@500;600;700&"
    "family=Noto+Sans+JP:wght@400;500;700&"
    "family=Zen+Kaku+Gothic+New:wght@700;900&display=swap\">"
)

CSS = """
:root{
  --ground:#0E1420; --surface:#172032; --surface-2:#1F2A3F; --line:#2A3852;
  --ink:#E8EDF5; --ink-dim:#93A2BC; --ink-faint:#63748F;
  --sand:#E0A84A; --sand-wash:rgba(224,168,74,.13); --sand-line:rgba(224,168,74,.35);
  --up:#4FB783; --down:#E4685D;
  --f-display:"Zen Kaku Gothic New","Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif;
  --f-body:"Noto Sans JP","Hiragino Sans","Yu Gothic",sans-serif;
  --f-num:"Barlow Condensed","Roboto Condensed",system-ui,sans-serif;
  color-scheme:dark;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:var(--f-body); font-size:15px; line-height:1.7;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:760px;margin:0 auto;padding:28px 16px 64px;display:flex;flex-direction:column;gap:28px}

/* --- masthead --- */
.masthead{display:flex;flex-direction:column;gap:6px}
.eyebrow{
  margin:0;font-family:var(--f-num);font-size:.8rem;font-weight:600;
  letter-spacing:.18em;text-transform:uppercase;color:var(--sand);
}
.masthead h1{
  margin:0;font-family:var(--f-display);font-weight:900;font-size:2rem;
  line-height:1.2;text-wrap:balance;letter-spacing:.01em;
}
.lede{margin:2px 0 0;color:var(--ink-dim);font-size:.9rem;max-width:60ch}

/* --- race switcher --- */
.tabs{
  position:sticky;top:0;z-index:5;display:flex;gap:6px;padding:8px 0;
  background:linear-gradient(var(--ground) 72%,rgba(14,20,32,0));
}
.tab{
  flex:1;padding:9px 6px;border:1px solid var(--line);border-radius:9px;
  background:var(--surface);color:var(--ink-dim);
  font-family:var(--f-num);font-size:1rem;font-weight:600;letter-spacing:.04em;
  cursor:pointer;transition:background .15s,color .15s,border-color .15s;
}
.tab:hover{color:var(--ink)}
.tab[aria-selected="true"]{
  background:var(--sand-wash);border-color:var(--sand-line);color:var(--sand);
}
.tab .tab-name{display:block;font-family:var(--f-body);font-size:.68rem;font-weight:500;letter-spacing:0}

/* --- race section --- */
.race{display:flex;flex-direction:column;gap:18px}
.race-head{display:flex;align-items:baseline;gap:12px;border-bottom:1px solid var(--line);padding-bottom:12px}
.rno{font-family:var(--f-num);font-size:2.1rem;font-weight:700;color:var(--sand);line-height:1}
.race-head h2{margin:0;font-family:var(--f-display);font-weight:700;font-size:1.25rem;line-height:1.3}
.meta{margin:2px 0 0;color:var(--ink-dim);font-size:.8rem}
.meta b{font-family:var(--f-num);font-weight:600;color:var(--ink);font-size:.9rem}

/* --- result strip --- */
.verdict{
  background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--sand);
  border-radius:10px;padding:14px 16px;display:flex;flex-direction:column;gap:8px;
}
.verdict-title{
  font-family:var(--f-num);font-size:.78rem;font-weight:600;letter-spacing:.14em;
  text-transform:uppercase;color:var(--sand);
}
.finish{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:.9rem}
.finish .arrow{color:var(--ink-faint)}
.verdict-note{font-size:.85rem;color:var(--ink-dim);margin:0}
.tag{
  display:inline-block;padding:1px 8px;border-radius:999px;font-size:.75rem;font-weight:500;
}
.tag.hit{background:rgba(79,183,131,.16);color:var(--up)}
.tag.miss{background:rgba(228,104,93,.14);color:var(--down)}

/* --- toolbar --- */
.toolbar{display:flex;align-items:center;justify-content:space-between;gap:10px}
.tb-label{font-size:.78rem;color:var(--ink-faint);letter-spacing:.06em}
.seg{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg-btn{
  padding:6px 14px;border:0;background:transparent;color:var(--ink-dim);
  font-family:var(--f-body);font-size:.8rem;cursor:pointer;
}
.seg-btn[aria-pressed="true"]{background:var(--surface-2);color:var(--ink)}

/* --- horse cards --- */
.cards{display:flex;flex-direction:column;gap:6px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.card[data-marked="1"]{border-color:rgba(224,168,74,.28)}
.card summary{
  list-style:none;cursor:pointer;padding:11px 13px;
  display:grid;grid-template-columns:26px 24px 1fr auto;align-items:center;gap:10px;
}
.card summary::-webkit-details-marker{display:none}
.card summary:focus-visible{outline:2px solid var(--sand);outline-offset:-2px}
.mark{
  font-family:var(--f-display);font-weight:700;font-size:1.1rem;text-align:center;
  color:var(--ink-dim);line-height:1;
}
.mark.m1{color:var(--sand);font-size:1.25rem}
.mark.none{color:var(--ink-faint);font-size:.9rem}
.waku{
  width:24px;height:24px;border-radius:4px;display:grid;place-items:center;
  font-family:var(--f-num);font-weight:700;font-size:.95rem;line-height:1;
}
.w1{background:#F2F4F7;color:#111}      .w2{background:#15181D;color:#F2F4F7;box-shadow:inset 0 0 0 1px #3A4358}
.w3{background:#D33A34;color:#fff}      .w4{background:#2A5CB8;color:#fff}
.w5{background:#E8C63E;color:#231C05}   .w6{background:#2E9B5B;color:#fff}
.w7{background:#E5762E;color:#fff}      .w8{background:#E88BA8;color:#2A1119}
.who{min-width:0}
.hname{font-weight:500;font-size:.95rem;line-height:1.35;overflow-wrap:anywhere}
.hsub{font-size:.74rem;color:var(--ink-faint);line-height:1.35}
.pts{text-align:right;font-family:var(--f-num);font-variant-numeric:tabular-nums;line-height:1.1}
.pts .good{font-size:1.35rem;font-weight:700}
.pts .heavy{display:block;font-size:.72rem;font-weight:500;color:var(--ink-faint)}
.finish-badge{
  font-family:var(--f-num);font-size:.72rem;font-weight:700;padding:1px 6px;border-radius:4px;
  background:var(--sand);color:#1A1206;margin-left:6px;vertical-align:2px;
}

/* --- breakdown --- */
.bd{padding:0 13px 13px;border-top:1px solid var(--line);margin-top:-1px}
.bd table{width:100%;border-collapse:collapse;font-size:.78rem}
.bd td{padding:5px 0;border-bottom:1px solid rgba(42,56,82,.6);vertical-align:top}
.bd td.lbl{color:var(--ink-dim);white-space:nowrap;padding-right:8px}
.bd td.val{
  font-family:var(--f-num);font-variant-numeric:tabular-nums;font-weight:600;
  text-align:right;width:3.4em;white-space:nowrap;
}
.bd td.note{color:var(--ink-faint);padding-left:10px;line-height:1.5}
.bd tr.total td{border-bottom:0;color:var(--ink);font-weight:700}
.bd tr.total td.lbl{color:var(--ink)}
.pos{color:var(--up)} .neg{color:var(--down)}

/* --- pace --- */
.sub{
  margin:0;font-family:var(--f-num);font-size:.82rem;font-weight:600;
  letter-spacing:.14em;text-transform:uppercase;color:var(--ink-faint);
}
.pace-bar{display:flex;height:30px;border-radius:7px;overflow:hidden;margin:8px 0 10px}
.pace-bar span{
  display:grid;place-items:center;font-family:var(--f-num);font-size:.82rem;font-weight:600;
  color:#12161F;min-width:0;white-space:nowrap;
}
.pace-hi{background:#E4685D} .pace-mid{background:var(--sand)} .pace-slow{background:var(--up)}
.pace-note{margin:0;font-size:.85rem;color:var(--ink-dim)}
.pace-list{margin:8px 0 0;padding:0;list-style:none;display:flex;flex-direction:column;gap:4px;font-size:.82rem}
.pace-list b{color:var(--ink);font-weight:500}
.pace-list span{color:var(--ink-dim)}

/* --- bets --- */
.bet-group{margin-top:12px}
.bet-head{display:flex;align-items:baseline;gap:8px;margin-bottom:6px}
.bet-kind{font-weight:700;font-size:.9rem}
.bet-count{font-family:var(--f-num);font-size:.8rem;color:var(--ink-faint)}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chip{
  background:var(--surface-2);border:1px solid var(--line);border-radius:6px;
  padding:4px 9px;font-size:.8rem;font-variant-numeric:tabular-nums;
}
.chip.hit{border-color:var(--up);color:var(--up);background:rgba(79,183,131,.1)}
.chip.miss{opacity:.5}
.bet-note{margin:8px 0 0;font-size:.78rem;color:var(--ink-faint)}

/* --- footer --- */
.foot{border-top:1px solid var(--line);padding-top:18px;font-size:.8rem;color:var(--ink-faint)}
.foot h3{margin:0 0 8px;font-size:.85rem;color:var(--ink-dim);font-weight:500}
.foot ul{margin:0;padding-left:1.1em;display:flex;flex-direction:column;gap:5px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

JS = """
(function(){
  var tabs = document.querySelectorAll('[data-tab]');
  function show(id){
    document.querySelectorAll('[data-race]').forEach(function(s){ s.hidden = (s.dataset.race !== id); });
    tabs.forEach(function(t){ t.setAttribute('aria-selected', String(t.dataset.tab === id)); });
  }
  tabs.forEach(function(t){ t.addEventListener('click', function(){ show(t.dataset.tab); }); });

  document.querySelectorAll('[data-sort]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var box = btn.closest('.race').querySelector('[data-cards]');
      var key = btn.dataset.sort;
      var cards = Array.prototype.slice.call(box.children);
      cards.sort(function(a, b){
        return key === 'umaban'
          ? (+a.dataset.umaban) - (+b.dataset.umaban)
          : (+b.dataset.score) - (+a.dataset.score);
      });
      cards.forEach(function(c){ box.appendChild(c); });
      btn.parentNode.querySelectorAll('[data-sort]').forEach(function(o){
        o.setAttribute('aria-pressed', String(o === btn));
      });
    });
  });
})();
"""


@dataclass
class RaceEntry:
    race_no: str
    name: str
    grade: str
    post_time: str
    surface: str
    kyori: int
    baba: str
    entries: str
    history: str | None = None
    result: str | None = None
    payouts: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "RaceEntry":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})


def _esc(s: str) -> str:
    return html.escape(str(s))


def _fmt_signed(n: float) -> str:
    return f"{n:+.1f}" if n else "0.0"


def _sign_class(n: float) -> str:
    return "pos" if n > 0 else ("neg" if n < 0 else "")


def _breakdown(score: HorseScore) -> str:
    rows = []
    for it in score.base_items:
        rows.append(
            f'<tr><td class="lbl">{_esc(it.label)}</td>'
            f'<td class="val">{it.points:.1f}</td>'
            f'<td class="note">{_esc(it.note)}</td></tr>'
        )
    rows.append(
        f'<tr><td class="lbl">小計</td><td class="val">{score.base_subtotal:.1f}</td>'
        f'<td class="note">85点満点</td></tr>'
    )
    for it in score.corrections:
        rows.append(
            f'<tr><td class="lbl">{_esc(it.label)}</td>'
            f'<td class="val {_sign_class(it.points)}">{_fmt_signed(it.points)}</td>'
            f'<td class="note">{_esc(it.note)}</td></tr>'
        )
    rows.append(
        f'<tr><td class="lbl">馬場補正（重）</td>'
        f'<td class="val {_sign_class(score._baba_delta)}">{_fmt_signed(score._baba_delta)}</td>'
        f'<td class="note">{_esc(score.baba_note)}</td></tr>'
    )
    rows.append(
        f'<tr class="total"><td class="lbl">良馬場 / 重馬場</td>'
        f'<td class="val">{score.total_yoi:.1f}</td>'
        f'<td class="note">重馬場なら {score.total_omoi:.1f} 点</td></tr>'
    )
    return f'<div class="bd"><table>{"".join(rows)}</table></div>'


def _card(score: HorseScore, mark: str, finish: int | None) -> str:
    h = score.horse
    mark_cls = "m1" if mark == "◎" else ("none" if not mark else "")
    badge = f'<span class="finish-badge">{finish}着</span>' if finish and finish <= 3 else ""
    sub = " · ".join(x for x in (h.sex_age, h.jockey, f"{h.kinryo:g}kg", h.kyakushitsu) if x)
    return (
        f'<details class="card" data-umaban="{h.umaban}" data-score="{score.total_yoi:.2f}"'
        f' data-marked="{1 if mark else 0}">'
        f'<summary>'
        f'<span class="mark {mark_cls}">{mark or "·"}</span>'
        f'<span class="waku w{h.wakuban}">{h.umaban}</span>'
        f'<span class="who"><span class="hname">{_esc(h.name)}{badge}</span>'
        f'<span class="hsub">{_esc(sub)}</span></span>'
        f'<span class="pts"><span class="good">{score.total_yoi:.1f}</span>'
        f'<span class="heavy">重 {score.total_omoi:.1f}</span></span>'
        f'</summary>{_breakdown(score)}</details>'
    )


def _pace(pace: PaceForecast) -> str:
    cls = {"ハイ": "pace-hi", "ミドル": "pace-mid", "スロー": "pace-slow"}
    bar = "".join(
        f'<span class="{cls[k]}" style="width:{v*100:.0f}%">{k} {v:.0%}</span>'
        for k, v in pace.probabilities.items() if v > 0
    )
    items = []
    for k, hs in pace.favored.items():
        names = "、".join(f"{h.umaban}{h.name}" for h in hs) or "該当なし"
        items.append(f"<li><b>{k}ペース</b> <span>{_esc(names)}</span></li>")
    counts = " / ".join(f"{k}{v}" for k, v in pace.counts.items())
    return (
        f'<div class="pace-bar">{bar}</div>'
        f'<p class="pace-note">{_esc(pace.note)}</p>'
        f'<p class="pace-note" style="font-size:.78rem">脚質構成: {_esc(counts)}</p>'
        f'<ul class="pace-list">{"".join(items)}</ul>'
    )


def _bets(plan: BettingPlan, result: RaceResult | None) -> str:
    def chip(label: str, kind: str, ticket) -> str:
        hit = ticket_hit(kind, ticket, result) if result else None
        cls = "chip" + (" hit" if hit else (" miss" if hit is False else ""))
        suffix = " ○" if hit else ""
        return f'<span class="{cls}">{_esc(label)}{suffix}</span>'

    groups = []
    if plan.tansho:
        tansho = "".join(
            chip(f"{m.score.horse.umaban} {m.score.horse.name}", "単勝", m) for m in plan.tansho
        )
        groups.append(("単勝", len(plan.tansho), tansho))
    for kind, tickets in (("ワイド", plan.wide), ("馬連", plan.umaren)):
        if not tickets:
            continue
        chips = "".join(
            chip("-".join(str(mh.score.horse.umaban) for mh in t.horses), kind, t) for t in tickets
        )
        groups.append((kind, len(tickets), chips))

    out = [f'<p class="bet-note">買い目タイプ: <b>{_esc(plan.strategy)}型</b>'
           f'（計{plan.total_points}点）</p>']
    for kind, n, chips in groups:
        out.append(
            f'<div class="bet-group"><div class="bet-head"><span class="bet-kind">{kind}</span>'
            f'<span class="bet-count">{n}点</span></div><div class="chips">{chips}</div></div>'
        )
    out.append(f'<p class="bet-note">{_esc(plan.note)}</p>')
    return "".join(out)


def _verdict(race: RaceEntry, marked: list[MarkedHorse], plan: BettingPlan,
             result: RaceResult, horses: list[Horse]) -> str:
    name_of = {h.umaban: h.name for h in horses}
    mark_of = {m.score.horse.umaban: m.mark for m in marked}
    order = sorted(
        ((u, c) for u, c in result.umaban_to_chakujun.items() if c <= 3), key=lambda x: x[1]
    )
    finish = f' <span class="arrow">→</span> '.join(
        f'<b>{u}</b> {_esc(name_of.get(u, ""))}'
        f'<span style="color:var(--sand)"> {mark_of.get(u, "無印")}</span>'
        for u, _ in order
    )

    def summarize(kind: str, tickets) -> str:
        hits = [t for t in tickets if ticket_hit(kind, t, result)]
        if hits:
            return f'<span class="tag hit">{kind} 的中</span>'
        return f'<span class="tag miss">{kind} 不的中</span>'

    tags = " ".join([
        summarize("単勝", plan.tansho),
        summarize("ワイド", plan.wide),
        summarize("馬連", plan.umaren),
    ])
    return (
        f'<div class="verdict"><span class="verdict-title">Result</span>'
        f'<div class="finish">{finish}</div><div>{tags}</div></div>'
    )


def _race_section(race: RaceEntry, first: bool) -> tuple[str, str]:
    horses = load_horses(race.entries)
    history = load_history(race.history) if race.history else None
    scores = score_race(horses, history, kyori=race.kyori)
    marked = assign_marks(scores, baba=race.baba)
    plan = make_betting_plan(marked, baba=race.baba)
    pace = forecast_pace(horses)
    result = RaceResult.from_csv(race.result) if race.result else None

    mark_of = {m.score.horse.umaban: m.mark for m in marked}
    by_umaban = sorted(scores, key=lambda s: s.horse.umaban)
    cards = "".join(
        _card(
            s,
            mark_of.get(s.horse.umaban, ""),
            result.umaban_to_chakujun.get(s.horse.umaban) if result else None,
        )
        for s in by_umaban
    )

    verdict = _verdict(race, marked, plan, result, horses) if result else ""
    tab = (
        f'<button class="tab" data-tab="{_esc(race.race_no)}" role="tab"'
        f' aria-selected="{"true" if first else "false"}">{_esc(race.race_no)}'
        f'<span class="tab-name">{_esc(race.name)}</span></button>'
    )
    section = (
        f'<section class="race" data-race="{_esc(race.race_no)}"{"" if first else " hidden"}>'
        f'<div class="race-head"><span class="rno">{_esc(race.race_no)}</span>'
        f'<div><h2>{_esc(race.name)}</h2><p class="meta">{_esc(race.grade)} ・ '
        f'発走 <b>{_esc(race.post_time)}</b> ・ {_esc(race.surface)} ・ 馬場 {_esc(race.baba)} ・ '
        f'{len(horses)}頭</p></div></div>'
        f'{verdict}'
        f'<div class="toolbar"><span class="tb-label">全{len(horses)}頭 ・ タップで配点内訳</span>'
        f'<div class="seg"><button class="seg-btn" data-sort="umaban" aria-pressed="true">馬番順</button>'
        f'<button class="seg-btn" data-sort="score" aria-pressed="false">スコア順</button></div></div>'
        f'<div class="cards" data-cards>{cards}</div>'
        f'<div><h3 class="sub">ペース想定</h3>{_pace(pace)}</div>'
        f'<div><h3 class="sub">買い目</h3>{_bets(plan, result)}</div>'
        f'</section>'
    )
    return tab, section


def build_daily_page(config: dict) -> str:
    races = [RaceEntry.from_dict(r) for r in config["races"]]
    tabs, sections = [], []
    for i, r in enumerate(races):
        t, s = _race_section(r, first=(i == 0))
        tabs.append(t)
        sections.append(s)

    notes = "".join(f"<li>{_esc(n)}</li>" for n in config.get("notes", []))
    return (
        f'<title>{_esc(config["title"])}</title>\n'
        f"{FONTS}\n<style>{CSS}</style>\n"
        f'<div class="wrap">'
        f'<header class="masthead"><p class="eyebrow">{_esc(config.get("eyebrow", ""))}</p>'
        f'<h1>{_esc(config["heading"])}</h1>'
        f'<p class="lede">{_esc(config.get("lede", ""))}</p></header>'
        f'<nav class="tabs" role="tablist">{"".join(tabs)}</nav>'
        f'<main>{"".join(sections)}</main>'
        f'<footer class="foot"><h3>このスコアリングの前提</h3><ul>{notes}</ul></footer>'
        f'</div>\n<script>{JS}</script>\n'
    )


def build_from_config(config_path: str | Path) -> str:
    with open(config_path, encoding="utf-8") as f:
        return build_daily_page(json.load(f))
