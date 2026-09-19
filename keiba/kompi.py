"""コンピ指数風の一覧表（1行=1レース・1列=スコア順位）。

本人が日刊スポーツ「コンピ指数」の紙面を示して「レイアウトをこれみたいに
して」と指示した形。紙面の構造をそのまま借りる:

    行   … レース（1R…12R）
    列   … 馬番能力順位（1…18）
    セル … 丸囲みの馬番（上）＋ 指数（下）
    5列ごとに朱の縦罫
    表の下に順位別の連対率（3ヶ月/1年/総合）

当システムへの対応は素直につく:

| 紙面 | 当システム |
|---|---|
| 馬番能力順位 | スコア順位（`assign_marks` と同じ軸＝良馬場なら良スコア、他は重スコア） |
| コンピ指数 | スコア（75点満点。`--metric hensachi` でレース内偏差値に切替） |
| 連対率 3ヶ月/1年/総合 | `calibration.json` の順位別 勝率／複勝率（中央9-12R の実測） |
| ウマ数字＝推奨馬 | 印（◎○▲） |

**最下段の実測は既定で出さない**（`calibration` を渡さない）。本人の指示
「勝率は入れないでいいです あくまで参考」。`--rates` を付けたときだけ
紙面と同じ位置に敷く。渡さなければ最下段2行も、それを説明する凡例の文も
出ない（存在しない行を説明しないため）。

## 貼り先の制約を最初から満たす（CLAUDE.md「アメブロに貼るには変換が要る」）
出力は `<style>` と表だけで、**アメブロの禁止タグを一切使わない**
（script / button / html / head / body / title / svg / input / form …）。
CSSは `.kompi` の下にスコープするのでブログ全体に漏れない。
`--title` を渡したときだけ `<title>` を足す（Artifact 用。貼る用には付けない）。

`daily` のカード形式は1日分で289,305バイト＝上限60,000の4.8倍だったが、
この様式は**表なので1日分が19,801バイト（上限の33%）で収まる**。

**ただしこれは内訳を含まない一覧である。** カード形式が太るのは配点内訳が
1頭2,118バイトあるためで、この表はそれを載せていない。CLAUDE.mdの
「スコア算出根拠（内訳）は必ず馬ごとに表示し、ブラックボックス化しない」は
**内訳を出す側（`daily` のカード／レースごとの記事）で守る**。この表は
一覧であって、カードの置き換えではない。
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

from .hensachi import deviations
from .marks import assign_marks
from .shinbun import config_date, config_venue, load_by_name
from .models import load_history, load_horses
from .notice import MARK_NOTICE
from .scoring import score_race

# JRAの枠色は 1白 2黒 3赤 4青 5黄 6緑 7橙 8桃。**地色はCSSの .w1〜.w8 に
# 1か所だけ置く**（セルごとの inline style にすると1日分で数キロバイト太る）。
# ここは「その枠番に色があるか」の判定にだけ使う
WAKU = frozenset(range(1, 9))
GROUP = 5          # 何列ごとに朱の縦罫を引くか（紙面と同じ5列）
MARKS = ("◎", "○", "▲")   # 紙面の「ウマ数字＝推奨馬」に当たる強調
# 脚質は1文字で入れる（本人の指示・2026-09-14「脚質は要ります」）。
# 一覧に詰め込む情報は絞る方針だが、脚質は無駄な情報ではない
# （大井では4角の位置が着順をほぼ支配し、中央でも先行と追込で勝率が3倍違う）
KYAKUSHITSU = ("逃", "先", "差", "追")

FONTS = (
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=Barlow+Condensed:wght@600;700&"
    "family=Noto+Sans+JP:wght@400;500;700&"
    "family=Zen+Kaku+Gothic+New:wght@700;900&display=swap\">"
)

CSS = """
.kompi{
  --paper:#EAE4D3; --paper-2:#F3EEE1; --paper-3:#DED7C4;
  --ink:#23211C; --ink-2:#6B675C; --ink-3:#9A9588;
  --navy:#1B3A6B; --vermilion:#C0362B;
  --f-disp:"Zen Kaku Gothic New","Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif;
  --f-body:"Noto Sans JP","Hiragino Sans","Yu Gothic",sans-serif;
  --f-num:"Barlow Condensed","Roboto Condensed",Helvetica,Arial,sans-serif;
  background:var(--paper); color:var(--ink);
  font-family:var(--f-body); font-size:14px; line-height:1.6;
  padding:14px 12px 18px; border:2px solid var(--ink);
  max-width:100%;
}
.kompi *{box-sizing:border-box}

/* 題字帯 — 左に紙名、右に開催（紙面と同じ配置） */
.kompi .mast{display:flex;flex-wrap:wrap;align-items:stretch;gap:8px;margin-bottom:12px}
.kompi .logo{
  flex:1 1 auto;min-width:200px;background:var(--navy);color:#F3EEE1;
  padding:7px 12px;display:flex;align-items:baseline;gap:10px;
}
.kompi .logo b{font-family:var(--f-disp);font-weight:900;font-size:1.25rem;letter-spacing:.04em}
.kompi .logo span{
  font-family:var(--f-body);font-weight:500;font-size:.72rem;
  letter-spacing:.22em;color:#B9C8E0;
}
.kompi .kaisai{
  background:var(--vermilion);color:#FFF;padding:6px 11px;text-align:center;
  font-family:var(--f-disp);font-weight:700;line-height:1.3;
}
.kompi .kaisai i{display:block;font-style:normal;font-size:1rem}
.kompi .kaisai u{display:block;text-decoration:none;font-size:.74rem;opacity:.9}

/* 表 — 横に18列あるので、はみ出す分はこの箱の中だけでスクロールさせる */
.kompi .scroll{overflow-x:auto;border-top:2px solid var(--ink);border-bottom:2px solid var(--ink)}
.kompi table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
.kompi caption{
  caption-side:top;text-align:left;padding:7px 2px 5px;
  font-family:var(--f-disp);font-weight:700;font-size:.95rem;letter-spacing:.02em;
}
.kompi caption em{
  font-style:normal;font-weight:500;font-size:.76rem;color:var(--ink-2);
  margin-left:8px;letter-spacing:.06em;
}
.kompi th,.kompi td{border:1px solid var(--ink-3);padding:0}
.kompi thead th{
  background:var(--paper-3);font-family:var(--f-num);font-weight:700;font-size:.9rem;
  padding:3px 0;min-width:34px;
}
.kompi thead th.corner{
  font-family:var(--f-body);font-size:.66rem;font-weight:700;letter-spacing:.02em;
  padding:3px 6px;text-align:right;line-height:1.25;white-space:nowrap;
}
.kompi td.rno,.kompi th.rno{
  background:var(--paper-3);text-align:right;padding:3px 7px;white-space:nowrap;
  border-right:2px solid var(--ink);
}
.kompi td.rno b{font-family:var(--f-num);font-weight:700;font-size:1.05rem;letter-spacing:.02em}
.kompi td.rno u{
  display:block;text-decoration:none;font-size:.62rem;color:var(--ink-2);
  letter-spacing:.02em;
}
.kompi td.cell{background:var(--paper-2);text-align:center;padding:2px 0 3px;vertical-align:top}
.kompi td.cell.blank{background:var(--paper)}
.kompi .g{border-right:2px solid var(--vermilion)}

/* セル — 枠色の丸に馬番、その下に指数 */
.kompi .u{
  display:inline-flex;align-items:center;justify-content:center;
  width:19px;height:19px;border-radius:50%;border:1px solid var(--ink);
  font-family:var(--f-num);font-weight:700;font-size:.82rem;line-height:1;
}
.kompi .v{
  display:block;font-family:var(--f-num);font-weight:600;font-size:.88rem;
  line-height:1.1;color:var(--ink);
}
.kompi .mk{
  display:block;font-size:.62rem;line-height:1;color:var(--vermilion);
  font-weight:700;height:.72em;white-space:nowrap;
}
.kompi .mk:empty{visibility:hidden}
.kompi .mk i{font-style:normal;font-weight:600;color:var(--ink-2);margin-left:1px}
.kompi td.osusume .v{color:var(--vermilion);font-weight:700}
.kompi .w1{background:#F7F5EF;color:#23211C}
.kompi .w2{background:#23211C;color:#F2EDE0}
.kompi .w3{background:#C0362B;color:#FFFFFF}
.kompi .w4{background:#1F5FA8;color:#FFFFFF}
.kompi .w5{background:#E4B93C;color:#23211C}
.kompi .w6{background:#2E8B57;color:#FFFFFF}
.kompi .w7{background:#E07B39;color:#23211C}
.kompi .w8{background:#E29AB0;color:#23211C}
.kompi .w0{background:#F3EEE1;color:#23211C}

/* 表の下 — 順位別の実測（紙面の連対率3行に当たる） */
.kompi tfoot td{background:var(--paper-3);text-align:center;padding:3px 0;
  font-family:var(--f-num);font-weight:600;font-size:.8rem}
.kompi tfoot td.rate-lbl{
  background:var(--paper-3);text-align:right;padding:3px 7px;
  font-family:var(--f-body);font-weight:700;font-size:.68rem;white-space:nowrap;
  border-right:2px solid var(--ink);
}
.kompi tfoot td.bucket{color:var(--ink-2)}

.kompi .legend{
  margin:10px 0 0;padding:8px 10px;background:var(--paper-2);
  border-left:3px solid var(--navy);font-size:.72rem;line-height:1.75;color:var(--ink-2);
}
.kompi .legend b{color:var(--ink)}
.kompi .legend ul{margin:4px 0 0;padding-left:1.1em}
@media (max-width:420px){
  .kompi{padding:10px 8px 14px}
  .kompi thead th{min-width:30px}
}
"""


@dataclass
class Cell:
    rank: int
    umaban: int
    wakuban: int
    value: float
    mark: str
    kyaku: str = ""      # 逃／先／差／追（読めなければ空）


@dataclass
class RaceGrid:
    venue: str
    race_no: str
    name: str
    surface: str
    baba: str
    post_time: str
    cells: list[Cell]

    @property
    def n(self) -> int:
        return len(self.cells)


def _esc(s) -> str:
    return html.escape(str(s))


def _kyaku(value: str | None) -> str:
    """「先行」→「先」。読めない値は空にする（それらしい文字を作らない）。"""
    head = (value or "").strip()[:1]
    return head if head in KYAKUSHITSU else ""


def race_grid(r: dict, metric: str = "score",
              records=None, as_of=None) -> RaceGrid:
    """1レースを順位順のセルに畳む。並べる軸は `assign_marks` と揃える。"""
    horses = load_horses(r["entries"])
    history = load_history(r["history"]) if r.get("history") else None
    scores = score_race(horses, history, kyori=r.get("kyori"),
                        records=records, as_of=as_of, venue=r.get("venue"))
    baba = r.get("baba") or "良"
    key = (lambda s: s.total_yoi) if baba == "良" else (lambda s: s.total_omoi)
    ranked = sorted(scores, key=key, reverse=True)
    mark_of = {m.score.horse.umaban: m.mark
               for m in assign_marks(scores, baba=baba)}
    vals = ([round(d, 1) for d in deviations([key(s) for s in ranked])]
            if metric == "hensachi" else [key(s) for s in ranked])
    return RaceGrid(
        venue=r.get("venue", ""), race_no=r.get("race_no", ""),
        name=r.get("name", ""), surface=r.get("surface", ""),
        baba=baba, post_time=r.get("post_time", ""),
        cells=[Cell(rank=i, umaban=s.horse.umaban, wakuban=s.horse.wakuban,
                    value=v, mark=mark_of.get(s.horse.umaban, ""),
                    kyaku=_kyaku(s.horse.kyakushitsu))
               for i, (s, v) in enumerate(zip(ranked, vals), start=1)],
    )


def _cell(c: Cell, group_edge: bool) -> str:
    w = c.wakuban if c.wakuban in WAKU else 0
    cls = "cell osusume" if c.mark in MARKS else "cell"
    return (
        f'<td class="{cls}{" g" if group_edge else ""}">'
        f'<span class="mk">{_esc(c.mark)}'
        f'{f"<i>{_esc(c.kyaku)}</i>" if c.kyaku else ""}</span>'
        f'<span class="u w{w}">{c.umaban}</span>'
        f'<span class="v">{c.value:.0f}</span></td>'
    )


def _venue_table(venue: str, grids: list[RaceGrid], cal: dict | None,
                 metric: str) -> str:
    cols = max(g.n for g in grids)
    edge = {i for i in range(GROUP, cols, GROUP)}
    label = "偏差値" if metric == "hensachi" else "スコア"

    head = "".join(
        f'<th class="{"g" if i in edge else ""}">{i}</th>'
        for i in range(1, cols + 1))
    rows = []
    for g in grids:
        tds = []
        for i in range(1, cols + 1):
            if i <= g.n:
                tds.append(_cell(g.cells[i - 1], i in edge))
            else:
                tds.append(f'<td class="cell blank{" g" if i in edge else ""}"></td>')
        rows.append(
            f'<tr><td class="rno"><b>{_esc(g.race_no)}</b>'
            f'<u>{_esc(g.surface)} {_esc(g.baba)}</u></td>{"".join(tds)}</tr>')

    foot = ""
    if cal:
        per = cal.get("順位別", {})
        bucket = per.get("9位以下")
        for key, lbl in (("勝率", "勝率"), ("複勝率", "複勝率")):
            tds = []
            for i in range(1, cols + 1):
                d = per.get(str(i))
                cls = "g" if i in edge else ""
                if d:
                    tds.append(f'<td class="{cls}">{d[key] * 100:.0f}</td>')
                elif bucket:
                    tds.append(f'<td class="bucket {cls}">{bucket[key] * 100:.0f}</td>')
                else:
                    tds.append(f'<td class="{cls}">—</td>')
            foot += (f'<tr><td class="rate-lbl">実測 {lbl}%</td>'
                     f'{"".join(tds)}</tr>')
        foot = f"<tfoot>{foot}</tfoot>"

    meta = f"{len(grids)}レース ・ 列は{label}の高い順"
    return (
        f'<div class="scroll"><table>'
        f'<caption>{_esc(venue)}<em>{_esc(meta)}</em></caption>'
        f'<thead><tr><th class="corner rno">馬番<br>{_esc(label)}順位</th>{head}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>{foot}</table></div>'
    )


def build_sheet(config: dict, calibration: dict | None = None,
                metric: str = "score", title: str | None = None,
                records: str | None = None) -> str:
    """設定JSONから紙面1枚を組む。`title` を渡すとArtifact用に<title>を足す。"""
    by_name = load_by_name(records, config_venue(config))
    as_of = config_date(config)
    grids = [race_grid(r, metric, by_name, as_of) for r in config["races"]]
    by_venue: dict[str, list[RaceGrid]] = {}
    for g in grids:
        by_venue.setdefault(g.venue or "—", []).append(g)

    tables = "".join(_venue_table(v, gs, calibration, metric)
                     for v, gs in by_venue.items())
    heading = config.get("heading", config.get("title", ""))
    venues = "・".join(by_venue)

    # 凡例は**読み方の解説をやめ、印の意味と免責だけ**にした（本人の指示・
    # 2026-09-14「記事の末尾の言葉はこれにする」「説明しすぎない」）。
    # 文言は `keiba/notice.py` に1か所だけ置く
    legend = f'<p class="legend">{_esc(MARK_NOTICE)}</p>'
    body = (
        f'<div class="kompi">'
        f'<div class="mast">'
        f'<div class="logo"><b>ポケットターフ</b><span>SCORE INDEX</span></div>'
        f'<div class="kaisai"><i>{_esc(heading)}</i><u>{_esc(venues)}</u></div>'
        f'</div>{tables}{legend}</div>'
    )
    parts = []
    if title:
        parts += [f"<title>{_esc(title)}</title>", FONTS,
                  "<style>body{margin:0;background:#D8D2C2;padding:18px 14px}"
                  f"{CSS}</style>"]
    else:
        parts.append(f"<style>{CSS}</style>")
    return "\n".join(parts) + "\n" + body + "\n"


def load_calibration(path: str | Path) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    with open(p, encoding="utf-8-sig") as f:
        return json.load(f)
