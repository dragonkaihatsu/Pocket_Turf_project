"""仮説検証: 「不利（出遅れ・包まれ）を受けた馬の妙味は、もう食われたのか」。

本人の言葉（2026-09-11）:
  新聞に載るのは表面（馬名・血統・騎手・前走5走の着順と着差）。足りないのは
  横の比較——対戦相手との結果、出遅れ、包まれ、ハンデ差。これらは文字データに
  残らずパトロールビデオか有料情報でしか見られなかった。しかしAIの発展で
  この不利を狙って大量購入する人が現れ、ボーナスチャンスのような馬は
  もう姿を消したのではないか。

不利そのものは映像データでしか分からないが、**痕跡は文字データに残る**:
  代理A「脚は使えたのに着順が悪い」= 前走で上がり3F上位3位以内 × 6着以下
      → 包まれた・進路がなかった・出遅れて届かなかった疑い
  代理B「前に行くはずが後ろにいた」= 前走の脚質が逃げ/先行 × 4角6番手以下
      → 出遅れの疑い

2025年と2026年に割って、妙味が縮んでいるかを見る。
"""
import csv, glob, re
from collections import defaultdict
from datetime import date

STAKE = 100
DATE_RE = re.compile(r'.*/(\d{4}-\d{2}-\d{2})_')

def parse_corner(s, n):
    toks = re.findall(r'\d+', s)
    out = []
    for t in toks:
        v = int(t)
        if v <= 18: out.append(v)
        else: out.extend(int(c) for c in t)
    if len(set(out)) != len(out) or not (n - 2 <= len(out) <= n): return None
    return out

by_horse = defaultdict(list)
for f in sorted(glob.glob('data/collected_jra/*_結果.csv')):
    m = DATE_RE.match(f)
    if not m: continue
    d = m.group(1)
    pay_t, pay_f = {}, {}
    try:
        for p in csv.DictReader(open(f.replace('_結果.csv','_配当.csv'), encoding='utf-8-sig')):
            if p.get('券種') == '単勝': pay_t[int(p['組み合わせ'])] = int(p['配当'])
            elif p.get('券種') == '複勝': pay_f[int(p['組み合わせ'])] = int(p['配当'])
    except (FileNotFoundError, ValueError): pass
    ent = {}
    try:
        for e in csv.DictReader(open(f.replace('_結果.csv','_出走馬.csv'), encoding='utf-8-sig')):
            nm = (e.get('馬名') or '').strip(); iv = e.get('前走間隔日数') or ''
            if nm: ent[nm] = {'interval': int(iv) if iv.isdigit() else None,
                              'kyaku': (e.get('脚質') or '').strip()}
    except FileNotFoundError: pass
    rows = [r for r in csv.DictReader(open(f, encoding='utf-8-sig'))
            if (r.get('着順') or '').isdigit()]
    if not rows: continue
    # 上がり3Fのレース内順位（速い順）
    ag = []
    for r in rows:
        try: ag.append((float(r['上がり3F']), r['馬番']))
        except (ValueError, KeyError): pass
    ag.sort()
    agari_rank = {ub: i for i, (_, ub) in enumerate(ag, start=1)}
    # 最終コーナー位置
    pos4 = {}
    try:
        cs = list(csv.DictReader(open(f.replace('_結果.csv','_通過順.csv'), encoding='utf-8-sig')))
        lc = parse_corner(cs[-1].get('通過順') or '', len(rows)) if cs else None
        if lc: pos4 = {ub: i for i, ub in enumerate(lc, start=1)}
    except FileNotFoundError: pass

    for r in rows:
        nm = (r.get('馬名') or '').strip(); ub = r.get('馬番') or ''
        nk = r.get('人気') or ''
        if not (nm and ub.isdigit()): continue
        e = ent.get(nm, {})
        by_horse[nm].append({
            'date': d, 'chaku': int(r['着順']), 'field': len(rows),
            'ninki': int(nk) if nk.isdigit() else None,
            'agari_rank': agari_rank.get(ub), 'pos4': pos4.get(int(ub)),
            'kyaku': e.get('kyaku', ''), 'interval': e.get('interval'),
            'tan': pay_t.get(int(ub), 0), 'fuku': pay_f.get(int(ub), 0)})
for v in by_horse.values(): v.sort(key=lambda x: x['date'])

def to_o(s):
    y, m, dd = (int(x) for x in s.split('-')); return date(y, m, dd).toordinal()

pairs = []
for nm, lst in by_horse.items():
    for i in range(1, len(lst)):
        cur = lst[i]
        if cur['interval'] is None: continue
        t = to_o(cur['date']) - cur['interval']
        for cand in lst[:i][::-1]:
            if abs(to_o(cand['date']) - t) <= 2:
                pairs.append((cand, cur)); break

def agg(rows):
    n = len(rows)
    if not n: return None
    w = sum(1 for r in rows if r['chaku'] == 1)
    return {'n': n, 'wins': w, 'win': w/n,
            'plc': sum(1 for r in rows if r['chaku'] <= 3)/n,
            'tan': sum(r['tan'] for r in rows)/(n*STAKE),
            'fuku': sum(r['fuku'] for r in rows)/(n*STAKE)}

# 不利の代理指標（前走に対して判定）
def furi_A(p):   # 脚は使えたのに着順が悪い
    return p['agari_rank'] is not None and p['agari_rank'] <= 3 and p['chaku'] >= 6
def furi_B(p):   # 前に行く脚質なのに4角後方（出遅れ疑い）
    return (p['kyaku'] in ('逃げ', '先行') and p['pos4'] is not None
            and p['pos4'] >= 6)
def plain_bad(p):  # 単に着順が悪いだけ（対照）
    return p['chaku'] >= 6 and not furi_A(p) and not furi_B(p)

def show(title, groups):
    print(f"── {title}")
    print(f"{'区分':<36}{'n':>6}{'勝利':>6}{'勝率':>7}{'複勝率':>8}{'単回収':>8}{'複回収':>8}")
    for lab, rows in groups:
        a = agg(rows)
        if not a: print(f"{lab:<36}{0:>6}"); continue
        note = '' if a['wins'] >= 10 else '  ※的中10本未満'
        print(f"{lab:<36}{a['n']:>6,}{a['wins']:>6}{a['win']:>7.1%}{a['plc']:>8.1%}"
              f"{a['tan']:>8.0%}{a['fuku']:>8.0%}{note}")
    print()

print(f"検証可能なペア: {len(pairs):,}組\n")
show('不利の痕跡がある馬は今走で走るか（全期間）', [
    ('代理A 前走: 上がり3F上位3位×6着以下', [c for p,c in pairs if furi_A(p)]),
    ('代理B 前走: 前に行く脚質×4角6番手以下', [c for p,c in pairs if furi_B(p)]),
    ('対照 前走: 単に6着以下（痕跡なし）',     [c for p,c in pairs if plain_bad(p)]),
    ('対照 前走: 1-5着',                     [c for p,c in pairs if p['chaku'] <= 5]),
])

for per, lab in ((('2025',), '2025年'), (('2026',), '2026年')):
    sel = [(p,c) for p,c in pairs if c['date'].startswith(per)]
    show(f'{lab}（妙味が縮んだかを見る）', [
        ('代理A 上がり3F上位3位×6着以下', [c for p,c in sel if furi_A(p)]),
        ('代理B 前に行く脚質×4角6番手以下', [c for p,c in sel if furi_B(p)]),
        ('対照 単に6着以下',               [c for p,c in sel if plain_bad(p)]),
    ])
