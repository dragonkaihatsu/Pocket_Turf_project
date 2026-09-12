#!/usr/bin/env python3
"""これまでに検証した仮説を、母数の観点から一括で再判定する。

## 目的

CLAUDE.mdには多くの仮説の実測値が載っているが、**母数が足りているかどうかを
そろえて確認していなかった**。実際に「複勝率40.0%対32.0%」を上向き材料と
書いて撤回している（n=65では15pt未満の差は見えない）。

そこで同じ土台（中央9-12Rの前走ペア）に載る仮説を1つのスクリプトで並べ、
`keiba/power.py` の判定（差あり / 差なし / 判定不能）を付ける。

  差あり   … 対照の点推定が検証群の95%信頼区間の外
  差なし   … 区間は重なるが母数は十分（効果があれば見えたはず）
  判定不能 … 区間が重なり、かつこの母数では意味のある差も見えない

## 主指標は複勝率

CLAUDE.md「主指標は同一人気帯内の正解率リフト」に合わせる。単勝回収率は
これまで一度も期間をまたいで再現していないため、判定には使わない
（参考として表示する）。

## 履歴と「今走」は分ける（`--target-races`・2026-09-12）

`--races 1-12` をそのまま渡すと、**今走が1-8R（下級条件）のペアも母集団に
入る**。前走ペアは14,542組→22,939組に増えるが、増えた分の多くは
「下級条件の馬が下級条件を走った」ペアで、9-12Rを予想するための集計とは
母集団が違う。特に減量騎手は1-8Rに3.7倍密に乗っているので影響が大きい。

そこで**前走（履歴）は `--races`、今走は `--target-races`** で分ける:

    # 前走が平場のペアも拾いつつ、今走は9-12Rだけ
    python3 scripts/review_hypotheses.py --races 1-12 --target-races 9-12

CLAUDE.md「前走の47.6%が平場にある（今の収集では前走が見つからない）」が
狙っていたのはこの形である。既定は `--races` と同じ（従来の挙動）。

## 期間の再現も見る

差ありと出た区分は、2025年と2026年で符号が一致するかも確認する。
片方だけで出ている差は、母数が足りていても信用できない。

    python3 scripts/review_hypotheses.py
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.power import HEADER, judge
from keiba.scoring import tier1_min_rides
from keiba.racefiles import (DEFAULT_RACES, parse_races, race_number,
                             result_paths)

STAKE = 100
DATE_RE = re.compile(r'.*/(\d{4}-\d{2}-\d{2})_')

# 減量騎手の記号（netkeibaの騎手表記にそのまま入っている）
GENRYO_MARKS = ("☆", "▲", "△", "◇")


def parse_corner(s: str, n: int):
    toks = re.findall(r'\d+', s)
    out = []
    for t in toks:
        v = int(t)
        if v <= 18:
            out.append(v)
        else:
            out.extend(int(c) for c in t)
    if len(set(out)) != len(out) or not (n - 2 <= len(out) <= n):
        return None
    return out


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--races", default=DEFAULT_RACES)
    ap.add_argument("--target-races", default=None,
                    help="「今走」のレース番号。既定は --races と同じ。"
                         "前走は --races から拾うので、`--races 1-12 "
                         "--target-races 9-12` で「前走が平場のペアも使い、"
                         "今走は9-12Rだけ」になる")
    ap.add_argument("--months", default=None,
                    help="対象月。1-8Rの収集が途中のあいだ `--races 1-12` をそのまま渡すと「1-8Rが入っている数ヶ月」と「9-12Rだけの残り」が混ざるので、効果を測るときは期間を揃える（例 2025-01..2025-03）")
    return ap.parse_args()


ARGS = parse_args()


def load() -> list[dict]:
    by_horse: dict[str, list[dict]] = defaultdict(list)
    # 騎手ごとの騎乗数（ティア判定用）。材料と検証を分けず全期間で数えるが、
    # ティアは「一軍かどうか」という粗い区分なので後知恵の影響は小さい
    rides: dict[str, int] = defaultdict(int)

    files = result_paths(ARGS.dir, ARGS.races, ARGS.months)
    for f in files:
        m = DATE_RE.match(f)
        if not m:
            continue
        d = m.group(1)
        rno = race_number(f)
        pay_t, pay_f = {}, {}
        try:
            for p in csv.DictReader(open(f.replace('_結果.csv', '_配当.csv'),
                                         encoding='utf-8-sig')):
                if p.get('券種') == '単勝':
                    pay_t[int(p['組み合わせ'])] = int(p['配当'])
                elif p.get('券種') == '複勝':
                    pay_f[int(p['組み合わせ'])] = int(p['配当'])
        except (FileNotFoundError, ValueError):
            pass

        ent = {}
        try:
            for e in csv.DictReader(open(f.replace('_結果.csv', '_出走馬.csv'),
                                         encoding='utf-8-sig')):
                nm = (e.get('馬名') or '').strip()
                iv = e.get('前走間隔日数') or ''
                if nm:
                    ent[nm] = {
                        'interval': int(iv) if iv.isdigit() else None,
                        'kyaku': (e.get('脚質') or '').strip(),
                        'blinker': (e.get('ブリンカー') or '').strip() == 'B',
                        'tenyu': (e.get('転入初戦') or '').strip() == 'Y',
                        'layoff': (e.get('長期休養明け') or '').strip() == 'Y',
                    }
        except FileNotFoundError:
            pass

        rows = [r for r in csv.DictReader(open(f, encoding='utf-8-sig'))
                if (r.get('着順') or '').isdigit()]
        if not rows:
            continue

        ag = []
        for r in rows:
            try:
                ag.append((float(r['上がり3F']), r['馬番']))
            except (ValueError, KeyError):
                pass
        ag.sort()
        agari_rank = {ub: i for i, (_, ub) in enumerate(ag, start=1)}

        pos4 = {}
        try:
            cs = list(csv.DictReader(open(f.replace('_結果.csv', '_通過順.csv'),
                                          encoding='utf-8-sig')))
            lc = parse_corner(cs[-1].get('通過順') or '', len(rows)) if cs else None
            if lc:
                pos4 = {ub: i for i, ub in enumerate(lc, start=1)}
        except FileNotFoundError:
            pass

        for r in rows:
            nm = (r.get('馬名') or '').strip()
            ub = r.get('馬番') or ''
            nk = r.get('人気') or ''
            jk = (r.get('騎手') or '').strip()
            if not (nm and ub.isdigit()):
                continue
            rides[jk] += 1
            e = ent.get(nm, {})
            by_horse[nm].append({
                'date': d, 'R': rno,
                'chaku': int(r['着順']), 'field': len(rows),
                'ninki': int(nk) if nk.isdigit() else None,
                'jockey': jk,
                'agari_rank': agari_rank.get(ub), 'pos4': pos4.get(int(ub)),
                'kyaku': e.get('kyaku', ''), 'interval': e.get('interval'),
                'blinker': e.get('blinker'), 'tenyu': e.get('tenyu'),
                'layoff': e.get('layoff'),
                'tan': pay_t.get(int(ub), 0), 'fuku': pay_f.get(int(ub), 0),
            })
    for v in by_horse.values():
        v.sort(key=lambda x: x['date'])
    return by_horse, rides


def to_o(s: str) -> int:
    y, mo, dd = (int(x) for x in s.split('-'))
    return date(y, mo, dd).toordinal()


by_horse, rides = load()
TARGET = parse_races(ARGS.target_races or ARGS.races)
pairs = []
for nm, lst in by_horse.items():
    for i in range(1, len(lst)):
        cur = lst[i]
        if cur['interval'] is None:
            continue
        # 前走（履歴）は全帯から拾うが、「今走」は対象帯だけ
        if TARGET is not None and cur['R'] not in TARGET:
            continue
        t = to_o(cur['date']) - cur['interval']
        for cand in lst[:i][::-1]:
            if abs(to_o(cand['date']) - t) <= 2:
                pairs.append((cand, cur))
                break

runs = [r for lst in by_horse.values() for r in lst]
print(f"中央 履歴{ARGS.races}R: {len(runs):,}出走 / "
      f"今走{ARGS.target_races or ARGS.races}R の前走ペア {len(pairs):,}組 / "
      f"騎手 {len(rides):,}人\n")

# 一軍の判定は **keiba.scoring と同じ関数**を通す。ここに `n >= 400` と
# 書いていたため、1-8Rの収集で延べ騎乗が増えたときに検証側の一軍だけが
# 15人→32人に膨らみ、「前走二桁×一軍へ乗り替わり」の複勝率が
# 16.9%→13.6%に薄まった（人数を固定すると16.2%で再現する）。
# 閾値を2か所に書くと、実装と検証が静かにずれる
TIER1_CUT = tier1_min_rides({"騎手": {j: {"n": n} for j, n in rides.items()}})
TIER1 = {j for j, n in rides.items() if n >= TIER1_CUT}
# 極少騎乗の下限も**騎乗数の比**で決める。生の50騎乗のままだと、収集が
# 増えるほど「極少」に該当する騎手が減っていく
TINY_CUT = max(1, round(50 * sum(rides.values()) / 25877))
TINY = {j for j, n in rides.items() if n < TINY_CUT}
print(f"一軍 {len(TIER1)}人（{TIER1_CUT:,}騎乗以上）/ "
      f"極少騎乗 {len(TINY)}人（{TINY_CUT:,}騎乗未満）\n")


def place(rows) -> tuple[int, int]:
    return sum(1 for r in rows if r['chaku'] <= 3), len(rows)


def win(rows) -> tuple[int, int]:
    return sum(1 for r in rows if r['chaku'] == 1), len(rows)


def tan_roi(rows) -> float:
    return (sum(r['tan'] for r in rows) / (len(rows) * STAKE)) if rows else 0.0


def fuku_roi(rows) -> float:
    return (sum(r['fuku'] for r in rows) / (len(rows) * STAKE)) if rows else 0.0


def furi_B(p) -> bool:
    return (p['kyaku'] in ('逃げ', '先行') and p['pos4'] is not None
            and p['pos4'] >= 6)


def blink(p, c) -> str:
    if not p['blinker'] and c['blinker']:
        return '新規装着'
    if p['blinker'] and c['blinker']:
        return '継続装着'
    if p['blinker'] and not c['blinker']:
        return '解除'
    return 'なし'


def genryo(j: str) -> bool:
    return any(m in j for m in GENRYO_MARKS)


# ── 仮説の定義: (見出し, 検証群の条件, 対照群の条件) ──
# 対照は「その仮説が比べるべき相手」を仮説ごとに選ぶ。全体平均と比べると
# 前走着順などの交絡が入るため
DD = lambda p: p['chaku'] >= 10          # 前走二桁着順
GOOD = lambda p: p['chaku'] <= 5         # 前走1-5着

HYPOTHESES = [
    ("■ 不利の痕跡（前走の脚質と4角位置の矛盾）", [
        ("前走二桁 × 前に行って沈んだ",
         lambda p, c: DD(p) and furi_B(p),
         lambda p, c: DD(p) and not furi_B(p)),
        ("前走二桁 × 上がり3F上位3位",
         lambda p, c: DD(p) and (p['agari_rank'] or 99) <= 3,
         lambda p, c: DD(p) and (p['agari_rank'] or 99) > 3),
    ]),
    ("■ 乗り替わり（格上げ）", [
        ("前走二桁 × 一軍騎手へ乗り替わり",
         lambda p, c: DD(p) and p['jockey'] != c['jockey'] and c['jockey'] in TIER1
                      and p['jockey'] not in TIER1,
         lambda p, c: DD(p) and p['jockey'] == c['jockey']),
        ("前走1-5着 × 一軍騎手へ乗り替わり",
         lambda p, c: GOOD(p) and p['jockey'] != c['jockey'] and c['jockey'] in TIER1
                      and p['jockey'] not in TIER1,
         lambda p, c: GOOD(p) and p['jockey'] == c['jockey']),
    ]),
    ("■ 減量騎手で下地 → 一軍騎手", [
        ("前走が減量騎手 × 今走一軍",
         lambda p, c: genryo(p['jockey']) and c['jockey'] in TIER1,
         lambda p, c: not genryo(p['jockey']) and c['jockey'] in TIER1),
        ("前走1-5着 × 前走減量 → 今走一軍",
         lambda p, c: GOOD(p) and genryo(p['jockey']) and c['jockey'] in TIER1,
         lambda p, c: GOOD(p) and not genryo(p['jockey']) and c['jockey'] in TIER1),
    ]),
    ("■ ブリンカー", [
        ("装着あり（新規+継続）",
         lambda p, c: c['blinker'], lambda p, c: not c['blinker']),
        ("新規装着", lambda p, c: blink(p, c) == '新規装着',
         lambda p, c: blink(p, c) == 'なし'),
        ("継続装着", lambda p, c: blink(p, c) == '継続装着',
         lambda p, c: blink(p, c) == 'なし'),
        ("解除（前走B→今走なし）", lambda p, c: blink(p, c) == '解除',
         lambda p, c: blink(p, c) == 'なし'),
        ("新規装着 × 前走1-5着",
         lambda p, c: blink(p, c) == '新規装着' and GOOD(p),
         lambda p, c: blink(p, c) == 'なし' and GOOD(p)),
    ]),
    ("■ 臨戦過程（大井で『逆』と出た仮説を中央で）", [
        ("JRA転入初戦", lambda p, c: c['tenyu'], lambda p, c: not c['tenyu']),
        ("長期休養明け(180日超)", lambda p, c: c['layoff'],
         lambda p, c: not c['layoff']),
        ("中1〜2週(7-14日)",
         lambda p, c: c['interval'] is not None and 7 <= c['interval'] <= 14,
         lambda p, c: c['interval'] is not None and c['interval'] > 14),
    ]),
    ("■ 騎手のティア（人気薄に限定）", [
        ("10番人気以下 × 極少騎乗の騎手",
         lambda p, c: (c['ninki'] or 0) >= 10 and c['jockey'] in TINY,
         lambda p, c: (c['ninki'] or 0) >= 10 and c['jockey'] not in TINY),
        ("10番人気以下 × 一軍騎手",
         lambda p, c: (c['ninki'] or 0) >= 10 and c['jockey'] in TIER1,
         lambda p, c: (c['ninki'] or 0) >= 10 and c['jockey'] not in TIER1),
    ]),
]

def evaluate(lab, f_test, f_ctrl, metric):
    """metric は place（複勝）か win（勝率）。判定と期間再現を返す。"""
    test = [c for p, c in pairs if f_test(p, c)]
    ctrl = [c for p, c in pairs if f_ctrl(p, c)]
    if not test or not ctrl:
        return None, None, test
    kt, nt = metric(test)
    kc, nc = metric(ctrl)
    v = judge(lab, kt, nt, kc, nc)
    signs = []
    for per in ('2025', '2026'):
        t = [c for c in test if c['date'].startswith(per)]
        cc = [c for c in ctrl if c['date'].startswith(per)]
        # 期間ごとにも的中10本を要求する。勝率は的中が薄くなるため、
        # これを課さないと1〜2本の差で「再現／反転」が決まってしまう
        if cc and metric(t)[0] >= 10:
            kt2, nt2 = metric(t)
            kc2, nc2 = metric(cc)
            signs.append(1 if kt2 / nt2 >= kc2 / nc2 else -1)
    rep = ("再現" if len(signs) == 2 and signs[0] == signs[1]
           else "反転" if len(signs) == 2 else "期間不足")
    return v, rep, test


results = []
for metric, mlabel, roi, roilab in ((place, "複勝率", fuku_roi, "複回収"),
                                    (win, "勝率", tan_roi, "単回収")):
    print("#" * 96)
    print(f"### 主指標: {mlabel}")
    print("#" * 96)
    for group, items in HYPOTHESES:
        print(group)
        print(HEADER)
        for lab, f_test, f_ctrl in items:
            v, rep, test = evaluate(lab, f_test, f_ctrl, metric)
            if v is None:
                print(f"{lab:<32}   該当なし")
                continue
            print(v.line() + f"  [{rep}] {roilab}{roi(test):.0%}")
            results.append((mlabel, group, v, rep))
        print()


print("=" * 96)
print("【まとめ1】母数が足りていて差が出て、しかも期間で再現した区分だけ")
print("           → これだけが信用できる\n")
print(f"{'指標':<7}" + HEADER)
for m, group, v, rep in results:
    if v.ok and rep == "再現":
        print(f"{m:<7}" + v.line())
print()
print("【まとめ2】差は出たが期間で符号が反転 → 信用しない")
for m, group, v, rep in results:
    if v.ok and rep == "反転":
        print(f"  {m:<5}{v.label:<34} n={v.n:>6,}  差{v.diff*100:+.1f}p")
print()
print("【まとめ3】母数が十分なのに差が無かった → 仮説を棄却できる")
for m, group, v, rep in results:
    if v.code == "差なし":
        print(f"  {m:<5}{v.label:<34} n={v.n:>6,}  差{v.diff*100:+.1f}p  "
              f"（{v.mdd*100:.1f}pt以上なら見えた）")
print()
print("【まとめ4】判定不能（母数不足）→ 追わない／母数を増やしてから")
for m, group, v, rep in results:
    if v.code == "判定不能":
        print(f"  {m:<5}{v.label:<34} n={v.n:>6,}  差{v.diff*100:+.1f}p  "
              f"要{v.mdd*100:.1f}pt / 主張には{v.need_n:,}頭")
