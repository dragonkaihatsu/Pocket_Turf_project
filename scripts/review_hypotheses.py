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

## 期間の再現も見る

差ありと出た区分は、2025年と2026年で符号が一致するかも確認する。
片方だけで出ている差は、母数が足りていても信用できない。

    python3 scripts/review_hypotheses.py
"""
from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.power import HEADER, judge
from keiba.racefiles import result_paths

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


def load() -> list[dict]:
    by_horse: dict[str, list[dict]] = defaultdict(list)
    # 騎手ごとの騎乗数（ティア判定用）。材料と検証を分けず全期間で数えるが、
    # ティアは「一軍かどうか」という粗い区分なので後知恵の影響は小さい
    rides: dict[str, int] = defaultdict(int)

    files = result_paths('data/collected_jra')
    for f in files:
        m = DATE_RE.match(f)
        if not m:
            continue
        d = m.group(1)
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
                'date': d, 'chaku': int(r['着順']), 'field': len(rows),
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
pairs = []
for nm, lst in by_horse.items():
    for i in range(1, len(lst)):
        cur = lst[i]
        if cur['interval'] is None:
            continue
        t = to_o(cur['date']) - cur['interval']
        for cand in lst[:i][::-1]:
            if abs(to_o(cand['date']) - t) <= 2:
                pairs.append((cand, cur))
                break

runs = [r for lst in by_horse.values() for r in lst]
print(f"中央9-12R: {len(runs):,}出走 / 前走ペア {len(pairs):,}組 / "
      f"騎手 {len(rides):,}人\n")

TIER1 = {j for j, n in rides.items() if n >= 400}      # 一軍（400騎乗超）
TINY = {j for j, n in rides.items() if n < 50}         # 極少騎乗


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
