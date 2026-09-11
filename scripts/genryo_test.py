"""仮説検証: 「前走は減量騎手（下地作り）→ 今走はトップ騎手（勝負）」は妙味か。

本人の言葉（2026-09-11）:
  減量騎手を乗せてレースの抽選に通りやすい好着順を稼ぎ、仕上げは
  ルメールで勝負ヤリ、みたいなことは当然ある。ただし調教師の起用意図は
  我々には分からない。

→ 意図は観測できないが、その痕跡（減量記号つき騎手 → トップ騎手への
  乗り替わり）は netkeiba の騎手表記から直接判別できる。
"""
import csv, glob, re
from collections import defaultdict
from datetime import date

STAKE = 100
DATE_RE = re.compile(r'.*/(\d{4}-\d{2}-\d{2})_')
MARKS = '☆▲△◇'

wins = defaultdict(int)
for f in glob.glob('data/collected_jra/*_結果.csv'):
    for r in csv.DictReader(open(f, encoding='utf-8-sig')):
        j = (r.get('騎手') or '').strip(); c = r.get('着順') or ''
        if j and c.isdigit() and int(c) == 1: wins[j] += 1

def is_genryo(j): return bool(j) and j[0] in MARKS
def is_top(j):    return wins.get(j, 0) >= 30        # 一軍（30勝以上＝20人）
def is_vtop(j):   return wins.get(j, 0) >= 50        # 最上位（50勝以上＝7人）

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

def show(title, groups):
    print(f"── {title}")
    print(f"{'区分':<32}{'n':>6}{'勝利':>6}{'勝率':>7}{'複勝率':>8}{'単回収':>8}{'複回収':>8}")
    for lab, rows in groups:
        a = agg(rows)
        if not a:
            print(f"{lab:<32}{0:>6}"); continue
        note = '' if a['wins'] >= 10 else '  ※的中10本未満'
        print(f"{lab:<32}{a['n']:>6,}{a['wins']:>6}{a['win']:>7.1%}{a['plc']:>8.1%}"
              f"{a['tan']:>8.0%}{a['fuku']:>8.0%}{note}")
    print()

# 前走が減量騎手だったペアだけを見る
g = [(p, c) for p, c in pairs if is_genryo(p['jockey'])]
print(f"前走が減量騎手だったペア: {len(g):,}組\n")

show('前走=減量騎手 → 今走の乗り替わり先で分ける', [
    ('→ 最上位騎手(50勝以上)',   [c for p,c in g if is_vtop(c['jockey'])]),
    ('→ 一軍騎手(30勝以上)',     [c for p,c in g if is_top(c['jockey'])]),
    ('→ それ以外に乗り替わり',   [c for p,c in g if not is_top(c['jockey']) and c['jockey'] != p['jockey']]),
    ('→ 同じ減量騎手で継続',     [c for p,c in g if c['jockey'] == p['jockey']]),
])

# 前走の着順で分ける（好着順で下地を作った形か、大敗か）
show('前走=減量騎手 × 前走で好走(1-5着) → 一軍騎手', [
    ('前走1-5着 → 一軍騎手', [c for p,c in g if p['chaku'] <= 5 and is_top(c['jockey'])]),
    ('前走1-5着 → 継続',     [c for p,c in g if p['chaku'] <= 5 and c['jockey'] == p['jockey']]),
    ('前走6着以下 → 一軍騎手', [c for p,c in g if p['chaku'] >= 6 and is_top(c['jockey'])]),
    ('前走6着以下 → 継続',     [c for p,c in g if p['chaku'] >= 6 and c['jockey'] == p['jockey']]),
])

# 期間を割って独立性を見る
for per, lab in ((('2025',), '2025年'), (('2026',), '2026年')):
    sel = [(p,c) for p,c in g if c['date'].startswith(per)]
    show(f'{lab}（期間別）前走=減量騎手', [
        ('→ 一軍騎手', [c for p,c in sel if is_top(c['jockey'])]),
        ('→ 継続',     [c for p,c in sel if c['jockey'] == p['jockey']]),
    ])

# 対照: 前走が一般騎手（減量記号なし・非一軍）→ 一軍騎手 の場合
n = [(p, c) for p, c in pairs
     if not is_genryo(p['jockey']) and not is_top(p['jockey'])]
show('対照: 前走=一般騎手(減量記号なし・非一軍) → 一軍騎手', [
    ('→ 一軍騎手', [c for p,c in n if is_top(c['jockey'])]),
    ('→ 継続',     [c for p,c in n if c['jockey'] == p['jockey']]),
])
