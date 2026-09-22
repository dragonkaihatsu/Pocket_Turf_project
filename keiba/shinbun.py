"""新聞レイアウト（1行=1レース・列が 軸／相手／押さえ／結果／配当）。

本人がブログの完成例を示して「軸 抑え 穴みたいに分ける」「もし17時に
レースが終わりましたら、結果として色を塗る形式」と指示した形。
`keiba/kompi.py`（列＝スコア順位）と同じ素材を、**買い方の役割で束ねて**
並べ直したもの。

## 区切りは実測の買い目幅と同じ

前に指示のあった「4頭目に黄色い点線・6頭目に赤線」は、この様式の
グループの境目とちょうど一致する:

| 欄 | スコア順位 | 対応する買い方 |
|---|---|---|
| 軸馬候補 | 1-2位 | ここから軸を採る |
| 相手馬（馬券に絡みそう） | 3-4位 | **上位4頭BOX**＝推奨（黄色い点線で閉じる） |
| 押さえ（手広く買うなら） | 5-8位 | **上位6頭BOX**（6頭目の後ろに赤線）／7-8位は印の残り |

だから線は飾りではなく、**どこまで買うといくつの点数になるか**の目印である。
`assign_marks` の印8頭をそのまま3欄に割るので、印の付かない馬は載らない。

## 結果は「入ったら塗る」

結果CSV・配当CSVが揃ったレースだけ、1着=桃／2着=橙／3着=水色に塗り、
馬番の背面に🥇🥈🥉を薄く敷く。取消・除外は灰色。揃っていないレースは
**空欄のまま**にする（推測して数字を作らない）。同じコマンドを発走前と
発走後に流せば、同じ紙面が予想→結果に変わる。

## 貼り先の制約（CLAUDE.md「アメブロに貼るには変換が要る」）
禁止タグを使わない（script / button / html / head / body / title / svg …）。
CSSは `.shinbun` の下にスコープする。`--title` のときだけ `<title>` を足す。
"""
from __future__ import annotations

import re

import csv
import html
from dataclasses import dataclass, field
from pathlib import Path

from .arare import judge as arare_judge
from . import profile
from .horsedb import load_records
from .marks import assign_marks, mark_sequence
from .models import load_history, load_horses
from .notice import NOTICE_LINES
from .racefiles import DEFAULT_RACES
from .scoring import score_race
from .target import excluded_note, split_races

# 欄の割り当て（スコア順位。終端を含む）。**実測の買い目幅に合わせてある**
GROUPS = (("軸馬候補", "", 1, 2),
          ("相手馬", "馬券に絡みそう", 3, 4),
          ("押さえ", "手広く買うなら", 5, 8))
DOTTED_AFTER = 4   # 黄色い点線＝上位4頭BOX（推奨）の切れ目
SOLID_AFTER = 6    # 赤線＝上位6頭BOX の切れ目
MARKS_SHOWN = 8    # 印の頭数（assign_marks と揃える）

WAKU = frozenset(range(1, 9))
KYAKUSHITSU = ("逃", "先", "差", "追")
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
# 配当の欄。券種名は配当CSVの表記、見出しはブログの紙面に合わせる
TICKETS = (("単勝", "単 勝"), ("馬連", "馬連複"), ("馬単", "馬連単"),
           ("3連複", "三連複"), ("3連単", "三連単"))

FONTS = (
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=Barlow+Condensed:wght@600;700&"
    "family=Noto+Sans+JP:wght@400;500;700&"
    "family=Zen+Kaku+Gothic+New:wght@700;900&display=swap\">"
)

CSS = """
.shinbun{
  --paper:#FFFFFF; --paper-2:#F7F7F5; --rule:#C9C7C1; --rule-2:#8C8A84;
  --ink:#222220; --ink-2:#6E6C66; --ink-3:#A5A29A;
  --navy:#1B3A6B; --vermilion:#C0362B; --dotted:#E0A800;
  --c1:#F9CFE0; --c2:#FBD2A6; --c3:#BFDBF4; --scr:#D9D9D9;
  --yen:#FFFDE7;
  --f-disp:"Zen Kaku Gothic New","Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif;
  --f-body:"Noto Sans JP","Hiragino Sans","Yu Gothic",sans-serif;
  --f-num:"Barlow Condensed","Roboto Condensed",Helvetica,Arial,sans-serif;
  background:var(--paper); color:var(--ink);
  font-family:var(--f-body); font-size:14px; line-height:1.5;
  padding:12px 10px 16px; max-width:100%;
}
.shinbun *{box-sizing:border-box}

.shinbun .mast{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;
  border-bottom:2px solid var(--ink);padding-bottom:6px;margin-bottom:10px}
.shinbun .mast b{font-family:var(--f-disp);font-weight:900;font-size:1.15rem}
.shinbun .mast span{font-size:.78rem;color:var(--ink-2);letter-spacing:.04em}
.shinbun .mast i{margin-left:auto;font-style:normal;font-size:.78rem;color:var(--ink-2)}

.shinbun .scroll{overflow-x:auto}
.shinbun table{border-collapse:collapse;width:100%;
  font-variant-numeric:tabular-nums;min-width:820px}
.shinbun caption{caption-side:top;text-align:left;padding:8px 2px 5px;
  font-family:var(--f-disp);font-weight:700;font-size:.95rem}
.shinbun caption em{font-style:normal;font-weight:500;font-size:.74rem;
  color:var(--ink-2);margin-left:8px}
.shinbun th,.shinbun td{border:1px solid var(--rule);padding:0}
.shinbun thead th{background:var(--paper-2);font-family:var(--f-body);
  font-weight:700;font-size:.72rem;padding:4px 3px;line-height:1.3;color:var(--ink)}
.shinbun thead th small{display:block;font-weight:400;font-size:.62rem;color:var(--ink-2)}
.shinbun thead th.grp{background:#ECEAE4}

.shinbun td.rno{background:var(--paper-2);text-align:center;padding:3px 6px;
  white-space:nowrap;font-family:var(--f-num);font-weight:700;font-size:1rem}
.shinbun td.post{text-align:center;font-family:var(--f-num);font-size:.8rem;
  color:var(--ink-2);padding:0 4px;white-space:nowrap}
.shinbun td.rname{padding:3px 7px;font-size:.78rem;line-height:1.25;min-width:132px}
.shinbun td.rname u{display:block;text-decoration:none;font-size:.64rem;color:var(--ink-2)}
/* 荒れそう／堅そう。率は出さない（区分に付いた一般値であって今日の確率ではない） */
.shinbun td.rname b.ar{font-weight:700;margin-left:6px;padding:0 4px;
  border-radius:2px;background:#ECEAE4;color:var(--ink)}
.shinbun td.kyori{text-align:center;font-family:var(--f-num);font-size:.8rem;
  padding:0 5px;white-space:nowrap;line-height:1.2}
.shinbun td.kyori u{display:block;text-decoration:none;font-size:.62rem;
  font-family:var(--f-body);color:var(--ink-2)}

.shinbun td.cell{text-align:center;padding:2px 0 3px;vertical-align:top;
  position:relative;min-width:31px}
/* メダルは馬番の丸の背面に重ねる。inset:0 のままだと印の行のぶん下に
   ずれて、丸と中心が合わない */
.shinbun td.cell .medal{position:absolute;inset:.7em 0 .15em;display:flex;
  align-items:center;justify-content:center;font-size:1.35rem;opacity:.55;
  pointer-events:none;
  font-family:"Noto Color Emoji","Apple Color Emoji","Segoe UI Emoji",sans-serif}
.shinbun td.cell .mk{display:block;font-size:.6rem;line-height:1;
  color:var(--vermilion);font-weight:700;height:.7em;white-space:nowrap;position:relative}
.shinbun td.cell .mk:empty{visibility:hidden}
.shinbun td.cell .mk i{font-style:normal;font-weight:600;color:var(--ink-2);margin-left:1px}
.shinbun .u{position:relative;display:inline-flex;align-items:center;
  justify-content:center;width:20px;height:20px;border-radius:50%;
  border:1px solid var(--ink);font-family:var(--f-num);font-weight:700;
  font-size:.84rem;line-height:1}
/* JRAの枠色 1白 2黒 3赤 4青 5黄 6緑 7橙 8桃。セルごとの inline style に
   すると1日分で数キロバイト太るので、地色はここに1か所だけ置く */
.shinbun .w1{background:#F7F5EF;color:#23211C}
.shinbun .w2{background:#23211C;color:#F2EDE0}
.shinbun .w3{background:#C0362B;color:#FFFFFF}
.shinbun .w4{background:#1F5FA8;color:#FFFFFF}
.shinbun .w5{background:#E4B93C;color:#23211C}
.shinbun .w6{background:#2E8B57;color:#FFFFFF}
.shinbun .w7{background:#E07B39;color:#23211C}
.shinbun .w8{background:#E29AB0;color:#23211C}
.shinbun .w0{background:#F3EEE1;color:#23211C}
.shinbun td.p1{background:var(--c1)}
.shinbun td.p2{background:var(--c2)}
.shinbun td.p3{background:var(--c3)}
.shinbun td.scr{background:var(--scr)}

/* 買い目の切れ目。点線＝上位4頭BOX、実線＝上位6頭BOX */
.shinbun .dot{border-right:2px dashed var(--dotted)}
.shinbun .sol{border-right:2px solid var(--vermilion)}
.shinbun .edge{border-right:2px solid var(--rule-2)}

.shinbun td.chaku{text-align:center;font-family:var(--f-num);font-weight:700;
  font-size:.92rem;padding:2px 0;min-width:28px}
.shinbun td.yen{text-align:right;font-family:var(--f-num);font-weight:600;
  font-size:.82rem;padding:2px 6px;background:var(--yen);white-space:nowrap;min-width:56px}
.shinbun td.none{color:var(--ink-3);text-align:center;font-size:.72rem}

.shinbun .legend{margin:9px 0 0;padding:7px 10px;background:var(--paper-2);
  border-left:3px solid var(--navy);font-size:.72rem;line-height:1.7;color:var(--ink-2)}
.shinbun .legend b{color:var(--ink)}
.shinbun .keys{margin:6px 0 0;font-size:.68rem;color:var(--ink-2);
  display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.shinbun .keys s{text-decoration:none;display:inline-flex;align-items:center;gap:4px}
.shinbun .keys em{font-style:normal;display:inline-block;width:14px;height:12px;
  border:1px solid var(--rule-2)}
@media (max-width:420px){.shinbun{padding:8px 6px 12px}}
"""


@dataclass
class Cell:
    rank: int
    umaban: int
    wakuban: int
    mark: str
    kyaku: str = ""
    chaku: int | None = None      # 1-3着なら塗る。それ以外は None
    scratched: bool = False


@dataclass
class RaceRow:
    venue: str
    race_no: str
    name: str
    grade: str
    surface: str
    baba: str
    post_time: str
    arare: str
    cells: list[Cell]
    top3: list[int | None] = field(default_factory=list)   # 1-3着の馬番
    payouts: dict[str, str] = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return bool(self.top3)


def _esc(s) -> str:
    return html.escape(str(s))


def _kyaku(value: str | None) -> str:
    head = (value or "").strip()[:1]
    return head if head in KYAKUSHITSU else ""


def result_stem(entries: str) -> tuple[Path, str] | None:
    """出走馬CSVのパスから「その日・その場・そのR」の接頭辞を作る。

    日付を設定から組み直さず**実ファイル名から取る**（CLAUDE.md
    「出走馬CSVは実ファイルを glob で探す」。レース名にクラス名が付く
    ことがあるので、名前を組み立て直すと見つからない）。
    """
    p = Path(entries)
    name = p.name
    if "_" not in name:
        return None
    date, rest = name.split("_", 1)
    if "R_" not in rest:
        return None
    venue_r = rest.split("R_", 1)[0] + "R"
    return p.parent, f"{date}_{venue_r}_"


def load_result(entries: str) -> tuple[dict[int, int], set[int], dict[str, str]]:
    """結果CSV・配当CSVを読む。無ければ空を返す（数字を作らない）。"""
    got = result_stem(entries)
    if not got:
        return {}, set(), {}
    folder, prefix = got
    chaku: dict[int, int] = {}
    scratched: set[int] = set()
    pay: dict[str, str] = {}

    for f in sorted(folder.glob(f"{prefix}*_結果.csv")):
        with open(f, encoding="utf-8-sig") as fp:
            for row in csv.DictReader(fp):
                try:
                    uma = int(row["馬番"])
                except (KeyError, ValueError, TypeError):
                    continue
                try:
                    chaku[uma] = int(row["着順"])
                except (KeyError, ValueError, TypeError):
                    scratched.add(uma)    # 中止・除外・取消
        break

    for f in sorted(folder.glob(f"{prefix}*_配当.csv")):
        with open(f, encoding="utf-8-sig") as fp:
            for row in csv.DictReader(fp):
                k = (row.get("券種") or "").strip()
                if k in pay:
                    continue          # 複勝・ワイドは先頭だけ（欄は1つ）
                v = (row.get("配当") or "").strip().replace(",", "")
                if v.isdigit():
                    pay[k] = f"{int(v):,}"
        break
    return chaku, scratched, pay



# 予想テキスト（`keiba.cli text`）と**同じスコア**で出すために要るもの。
#
# ## 新聞・一覧が旧尺度で出ていた（2026-09-19・本人が画像で気づいた）
#
# `score_race` に `records` を渡していなかったため、持ち時計指数が作れず
# **全馬が上がり3Fの代替に落ちていた**。コース適性・距離適性も中立で、
# 乗り替わり補正も発火しない。結果、同じ日の同じ設定から
#
#   予想テキスト  中山9R  ◎6 ○3 ▲2 △9 …   （持ち時計あり）
#   新聞・一覧    中山9R  ◎6 ○2 ▲9 △3 …   （上がり3Fだけ）
#
# と**2〜4位の並びが違うものが2つ出ていた**。配信の既定は新聞なので、
# 公表していたのは旧尺度のほうだった。
#
# `as_of` も要る。渡さないと戦績の全期間を見てしまい、**当日の結果を
# 含んだ後知恵のスコア**になる（発走後に作り直したとき静かに変わる）。
# 設定JSONの heading/title から日付を拾う。
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def config_venue(config: dict) -> str | None:
    """設定JSONの最初のレースの競馬場。プロファイルをここから決める。"""
    for r in config.get("races", []):
        if v := r.get("venue"):
            return v
    return None


def config_date(config: dict) -> str | None:
    for key in ("heading", "title"):
        if m := DATE_RE.search(str(config.get(key, ""))):
            return m.group(1)
    return None


def load_by_name(records: str | None = None,
                 venue: str | None = None) -> dict[str, list[dict]] | None:
    """馬名 → 戦績。`keiba.cli` の `_load_horse_records` と同じ形にする。

    **パスは競馬場名から決める。** `profile.active()` に頼ると、
    `scripts/build_shinbun.py` のような単体スクリプトは `--profile` を
    受けないので既定（地方）のままになり、**中央のレースに大井の戦績を
    当てる**（＝戦績が空で持ち時計が作れない）。基準表を `for_venue` で
    引くようにしたのと同じ理由で、CLAUDE.mdが繰り返し記録している
    「集計スクリプトがプロファイルを指定していない事故」の型である。
    """
    if records is None and venue:
        records = profile.for_venue(venue).path("horse_records.csv")
    by_id = load_records(records)
    if not by_id:
        return None
    by_name: dict[str, list[dict]] = {}
    for rows in by_id.values():
        if rows and rows[0]["馬名"]:
            by_name.setdefault(rows[0]["馬名"], []).extend(rows)
    for rows in by_name.values():
        rows.sort(key=lambda r: r["日付"])
    return by_name


# ## 公表した並びで結果を塗る（`--published`・2026-09-19）
#
# スコアの不具合を直すと並びが変わるので、**直したあとのスコアで結果を
# 塗ると、実際に公表した紙面とは別のものを検証することになる**。
# `scripts/settle_day.py` が「実際の購入は投票履歴からしか分からない」と
# して `--published` を必須にしたのと同じ理由で、**公表済みの印の並びを
# ファイルから読んでそのまま並べる**経路を用意する。
#
# 形は {"中山9R": [6,2,9,3,8,1,4,7], ...}（スコア順位の順に馬番）。
# 載っていないレースはスコアから作る（混ぜたことが分かるように見出しへ出す）。
def load_published(path: str | Path) -> dict[str, list[int]]:
    import json
    with open(path, encoding="utf-8-sig") as f:
        raw = json.load(f)
    return {str(k): [int(u) for u in v]
            for k, v in raw.items() if isinstance(v, list)}


def published_key(r: dict) -> str:
    return f"{r.get('venue', '')}{r.get('race_no', '')}"


def race_row(r: dict, records=None, as_of=None,
             published: dict[str, list[int]] | None = None,
             agari_mix: float = 0.0) -> RaceRow:
    horses = load_horses(r["entries"])
    history = load_history(r["history"]) if r.get("history") else None
    scores = score_race(horses, history, kyori=r.get("kyori"),
                        agari_mix=agari_mix,
                        records=records, as_of=as_of, venue=r.get("venue"),
                        surface=r.get("surface"))
    baba = r.get("baba") or "良"
    order = (published or {}).get(published_key(r))
    if order:
        # 公表した並びをそのまま使う。**スコアで並べ直さない**
        by_uma = {s.horse.umaban: s for s in scores}
        ranked = [by_uma[u] for u in order[:MARKS_SHOWN] if u in by_uma]
        mark_of = dict(zip(order, mark_sequence()))
    else:
        key = (lambda s: s.total_yoi) if baba == "良" else (lambda s: s.total_omoi)
        ranked = sorted(scores, key=key, reverse=True)[:MARKS_SHOWN]
        mark_of = {m.score.horse.umaban: m.mark
                   for m in assign_marks(scores, baba=baba)}

    # 荒れそう／堅そう。1番人気オッズ帯 × 上位3人気の支持集中度の2軸
    # （`keiba/arare.py`）。判定できないレースは空にして作らない
    fav = next((h for h in horses if h.ninki == 1), None)
    arare = arare_judge(fav.tansho_odds if fav else None, horses,
                        venue=r.get("venue")) or ""

    chaku, scratched, pay = load_result(r["entries"])
    cells = []
    for i, s in enumerate(ranked, start=1):
        u = s.horse.umaban
        c = chaku.get(u)
        cells.append(Cell(rank=i, umaban=u, wakuban=s.horse.wakuban,
                          mark=mark_of.get(u, ""),
                          kyaku=_kyaku(s.horse.kyakushitsu),
                          chaku=c if c in MEDALS else None,
                          scratched=u in scratched))
    top3 = []
    for pos in (1, 2, 3):
        hit = [u for u, c in chaku.items() if c == pos]
        top3.append(hit[0] if hit else None)
    while top3 and top3[-1] is None:
        top3.pop()
    return RaceRow(venue=r.get("venue", ""), race_no=r.get("race_no", ""),
                   name=r.get("name", ""), grade=r.get("grade", ""),
                   surface=r.get("surface", ""), baba=baba,
                   post_time=r.get("post_time", ""), arare=arare, cells=cells,
                   top3=top3, payouts=pay)


def _edge(rank: int) -> str:
    """その順位の右に引く罫。点線＝4頭BOX、実線＝6頭BOX。"""
    if rank == DOTTED_AFTER:
        return " dot"
    if rank == SOLID_AFTER:
        return " sol"
    return ""


def _cell(c: Cell | None, rank: int) -> str:
    edge = _edge(rank)
    if c is None:
        return f'<td class="cell{edge}"></td>'
    cls = "cell"
    if c.scratched:
        cls += " scr"
    elif c.chaku:
        cls += f" p{c.chaku}"
    w = c.wakuban if c.wakuban in WAKU else 0
    medal = (f'<span class="medal">{MEDALS[c.chaku]}</span>'
             if c.chaku else "")
    kyaku = f"<i>{_esc(c.kyaku)}</i>" if c.kyaku else ""
    return (f'<td class="{cls}{edge}">{medal}'
            f'<span class="mk">{_esc(c.mark)}{kyaku}</span>'
            f'<span class="u w{w}">{c.umaban}</span></td>')


def _venue_table(venue: str, rows: list[RaceRow]) -> str:
    head1 = ['<th rowspan="2">Race</th>',
             '<th rowspan="2">発走</th>',
             '<th rowspan="2">競走名/条件</th>',
             '<th rowspan="2">距離</th>']
    for label, sub, lo, hi in GROUPS:
        span = hi - lo + 1
        # 線は本文と同じ位置にしか引かない。群の右端が線の位置と一致
        # しないなら、ただの仕切り(edge)にする
        cls = "grp" + (" dot" if hi == DOTTED_AFTER else
                       (" sol" if hi == SOLID_AFTER else " edge"))
        head1.append(f'<th class="{cls}" colspan="{span}">{_esc(label)}'
                     + (f"<small>{_esc(sub)}</small>" if sub else "")
                     + "</th>")
    head1.append('<th class="grp" colspan="3">着 順<small>1着 / 2着 / 3着</small></th>')
    for _, disp in TICKETS:
        head1.append(f'<th rowspan="2">{_esc(disp)}</th>')

    head2 = []
    for _, _, lo, hi in GROUPS:
        for i in range(lo, hi + 1):
            head2.append(f'<th class="{_edge(i).strip()}">{i}</th>')
    head2 += ['<th>1</th>', '<th>2</th>', '<th class="edge">3</th>']

    body = []
    for r in rows:
        by_rank = {c.rank: c for c in r.cells}
        tds = [f'<td class="rno">{_esc(r.race_no)}</td>',
               f'<td class="post">{_esc(r.post_time)}</td>',
               f'<td class="rname">{_esc(r.name)}'
               + (f"<u>{_esc(r.grade)}"
                  + (f'<b class="ar">{_esc(r.arare)}</b>' if r.arare else "")
                  + "</u>" if (r.grade or r.arare) else "") + "</td>",
               f'<td class="kyori edge">{_esc(r.surface)}'
               f'<u>{_esc(r.baba)}</u></td>']
        for _, _, lo, hi in GROUPS:
            for i in range(lo, hi + 1):
                tds.append(_cell(by_rank.get(i), i))
        for i in range(3):
            u = r.top3[i] if i < len(r.top3) else None
            cls = f"chaku p{i + 1}" if u else "chaku none"
            if i == 2:
                cls += " edge"
            tds.append(f'<td class="{cls}">{u if u else "—"}</td>')
        for key, _ in TICKETS:
            v = r.payouts.get(key)
            tds.append(f'<td class="yen">{_esc(v)}</td>' if v
                       else '<td class="yen none">—</td>')
        body.append(f"<tr>{''.join(tds)}</tr>")

    done = sum(1 for r in rows if r.done)
    meta = f"{len(rows)}レース"
    meta += f" ・ 結果{done}レース入力済み" if done else " ・ 発走前"
    return (f'<div class="scroll"><table>'
            f'<caption>{_esc(venue)}<em>{_esc(meta)}</em></caption>'
            f'<thead><tr>{"".join(head1)}</tr>'
            f'<tr>{"".join(head2)}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def build_sheet(config: dict, title: str | None = None,
                records: str | None = None,
                published: dict[str, list[int]] | None = None,
                agari_mix: float = 0.0,
                use_records: bool = True,
                include_all: bool = False,
                target_races: str | None = DEFAULT_RACES) -> str:
    # use_records=False は「馬柱だけで採点する」味付け。戦績を渡さないので
    # 持ち時計・コース適性・距離適性・乗り替わり補正がすべて中立に倒れ、
    # **基礎能力(上がり3F)と前走テーブルだけがスコアを動かす**
    by_name = load_by_name(records, config_venue(config)) if use_records else None
    as_of = config_date(config)
    # 障害・新馬は予想の対象外（本人の指示・2026-09-22）。判定は
    # `keiba/target.py` の1か所で、4つの出力経路が同じ関数を通る
    races, dropped = ((config["races"], []) if include_all
                      else split_races(config["races"], target_races))
    rows = [race_row(r, by_name, as_of, published, agari_mix) for r in races]
    # 公表版と作り直した版が混ざらないよう、見出しに出どころを書く
    n_pub = sum(1 for r in races if published and published_key(r) in published)
    source = (f"印は公表版（{n_pub}/{len(races)}レース）" if n_pub else "")
    if note := excluded_note(dropped):
        source = (source + " / " if source else "") + note
    # 味付けを紙面に書く。**同じ日の紙面が2種類あるときに、どちらを見て
    # いるか分からなくなるのを防ぐ**（`--published` で版を分けたのと同じ理由）
    if agari_mix >= 1.0:
        source = (source + " / " if source else "") + "基礎能力=上がり3F"
    elif agari_mix > 0.0:
        source = ((source + " / " if source else "")
                  + f"基礎能力=持ち時計{1 - agari_mix:.0%}+上がり3F{agari_mix:.0%}")
    if not use_records:
        source = (source + " / " if source else "") + "馬柱のみ"
    by_venue: dict[str, list[RaceRow]] = {}
    for r in rows:
        by_venue.setdefault(r.venue or "—", []).append(r)
    tables = "".join(_venue_table(v, rs) for v, rs in by_venue.items())
    heading = config.get("heading", config.get("title", ""))

    keys = ('<p class="keys">'
            '<s><em style="background:var(--c1)"></em>1着</s>'
            '<s><em style="background:var(--c2)"></em>2着</s>'
            '<s><em style="background:var(--c3)"></em>3着</s>'
            '<s><em style="background:var(--scr)"></em>取消・除外</s>'
            '<s><em style="border:0;border-right:2px dashed var(--dotted);'
            'width:10px"></em>上位4頭BOX</s>'
            '<s><em style="border:0;border-right:2px solid var(--vermilion);'
            'width:10px"></em>上位6頭BOX</s></p>')
    body = (f'<div class="shinbun">'
            f'<div class="mast"><b>ポケットターフ</b>'
            f'<span>{_esc(heading)}</span>'
            + (f'<span>{_esc(source)}</span>' if source else "")
            + f'<i>{_esc("・".join(by_venue))}</i></div>'
            f'{tables}{keys}'
            + "".join(f'<p class="legend">{_esc(n)}</p>' for n in NOTICE_LINES)
            + '</div>')
    parts = []
    if title:
        parts += [f"<title>{_esc(title)}</title>", FONTS,
                  "<style>body{margin:0;background:#EDEBE6;padding:16px 12px}"
                  f"{CSS}</style>"]
    else:
        parts.append(f"<style>{CSS}</style>")
    return "\n".join(parts) + "\n" + body + "\n"
