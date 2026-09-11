"""独立検証: 2025年で見つけた形が、2026年でも通用するか。

CLAUDE.mdの方針（材料と検証のレースを完全に分ける）に従う。
in-sampleで見えた「前走二桁 × 格上げ乗り替わり」の優位が、
期間を分けても再現するかを確かめる。再現しなければ後知恵。
"""
import csv, glob, re
from collections import defaultdict
from datetime import date

STAKE = 100
DATE_RE = re.compile(r'.*/(\d{4}-\d{2}-\d{2})_')

# 騎手ティアは2025年の勝利数だけで作る（2026年の結果を使わない＝後知恵排除）
wins25 = defaultdict(int)
for f in glob.glob('data/collected_jra/2025-*_結果.csv'):
    for r in csv.DictReader(open(f, encoding='utf-8-sig')):
        j = (r.get('騎手') or '').strip(); c = r.get('着順') or ''
        if j and c.isdigit() and int(c) == 1: wins25[j] += 1

def tier(j):
    w = wins25.get(j, 0)
    return 3 if w >= 30 else 2 if w >= 18 else 1 if w >= 6 else 0

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
    interval = {}
    try:
        for e in csv.DictReader(open(f.replace('_結果.csv','_出走馬.csv'), encoding='utf-8-sig')):
            nm = (e.get('馬名') or '').strip(); iv = e.get('前走間隔日数') or ''
            if nm: interval[nm] = int(iv) if iv.isdigit() else None
    except FileNotFoundError: pass
    for r in csv.DictReader(open(f, encoding='utf-8-sig')):
        nm = (r.get('馬名') or '').strip(); j = (r.get('騎手') or '').strip()
        ub, nk, ch = r.get('馬番') or '', r.get('人気') or '', r.get('着順') or ''
        if not (nm and j and ub.isdigit() and ch.isdigit()): continue
        by_horse[nm].append({'date': d, 'jockey': j, 'chaku': int(ch),
                             'ninki': int(nk) if nk.isdigit() else None,
                             'tan': pay_t.get(int(ub), 0), 'fuku': pay_f.get(int(ub), 0),
                             'interval': interval.get(nm)})
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

up   = lambda p,c: tier(c['jockey']) > tier(p['jockey'])
keep = lambda p,c: p['jockey'] == c['jockey']

for period, label in ((('2025',), '2025年（材料期間・in-sample）'),
                      (('2026',), '2026年（検証期間・独立）')):
    sel = [(p,c) for p,c in pairs if c['date'].startswith(period) and p['chaku'] >= 10]
    print(f"── {label}  前走二桁着順のペア {len(sel):,}組")
    print(f"{'区分':<30}{'n':>6}{'勝利':>6}{'勝率':>7}{'複勝率':>8}{'単回収':>8}{'複回収':>8}")
    rows = [
        ('全体 × 格上げ乗り替わり', [c for p,c in sel if up(p,c)]),
        ('全体 × 継続騎乗',        [c for p,c in sel if keep(p,c)]),
        ('1-3番人気 × 格上げ',     [c for p,c in sel if up(p,c) and c['ninki'] and c['ninki']<=3]),
        ('1-3番人気 × 継続騎乗',   [c for p,c in sel if keep(p,c) and c['ninki'] and c['ninki']<=3]),
    ]
    for lab, rs in rows:
        a = agg(rs)
        if not a:
            print(f"{lab:<30}{'0':>6}"); continue
        mark = '' if a['wins'] >= 10 else '  ※的中10本未満'
        print(f"{lab:<30}{a['n']:>6,}{a['wins']:>6}{a['win']:>7.1%}{a['plc']:>8.1%}"
              f"{a['tan']:>8.0%}{a['fuku']:>8.0%}{mark}")
    print()
