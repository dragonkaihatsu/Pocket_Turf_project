"""横断偏差値（レースをまたいで比較できる能力値）を作って検証する。

考え方:
  上がり3Fの絶対値はペース・馬場・クラスで変わるので横比較できない。
  しかし我々は全出走馬を持っているので、**各レース内で偏差値化**すれば
  「そのメンバーの中でどれだけ速く上がったか」という条件非依存の値になる。
  これを馬ごとに過去走で平均すれば、レースをまたいで比較できる能力値になる。

  上がり3F偏差値 = 50 + 10 × (レース平均 - その馬のタイム) / 標準偏差
  （タイムは小さいほど速いので符号を反転）

検証の要点:
  1. 情報漏れを防ぐ。ある馬のレーティングは**そのレースより前の走り**だけで作る
  2. 「オッズには見えない強さ」かを見る。**同じ人気帯の中で**レーティングが
     着順を判別できるなら、市場が持っていない情報である
  3. 2025年で作って2026年で検証する（独立性）
"""
import csv, glob, re, statistics
from collections import defaultdict

STAKE = 100
DATE_RE = re.compile(r'.*/(\d{4}-\d{2}-\d{2})_')

runs = defaultdict(list)   # 馬名 -> [{date, dev, chaku, ...}]
race_rows = []             # 各出走（今走の予想対象になりうる行）

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
    kyaku = {}
    try:
        for e in csv.DictReader(open(f.replace('_結果.csv','_出走馬.csv'), encoding='utf-8-sig')):
            nm = (e.get('馬名') or '').strip()
            if nm: kyaku[nm] = (e.get('脚質') or '').strip()
    except FileNotFoundError: pass

    rows = [r for r in csv.DictReader(open(f, encoding='utf-8-sig'))
            if (r.get('着順') or '').isdigit()]
    ag = []
    for r in rows:
        try: ag.append(float(r['上がり3F']))
        except (ValueError, KeyError): ag.append(None)
    vals = [v for v in ag if v]
    if len(vals) < 5: continue
    mu = statistics.mean(vals)
    sd = statistics.pstdev(vals) or 1.0

    for r, a in zip(rows, ag):
        nm = (r.get('馬名') or '').strip(); ub = r.get('馬番') or ''
        nk = r.get('人気') or ''
        if not (nm and ub.isdigit()): continue
        dev = 50 + 10 * (mu - a) / sd if a else None
        rec = {'name': nm, 'date': d, 'dev': dev, 'chaku': int(r['着順']),
               'ninki': int(nk) if nk.isdigit() else None, 'field': len(rows),
               'kyaku': kyaku.get(nm, ''),
               'tan': pay_t.get(int(ub), 0), 'fuku': pay_f.get(int(ub), 0)}
        race_rows.append(rec)
        if dev is not None:
            runs[nm].append(rec)

for v in runs.values(): v.sort(key=lambda x: x['date'])
race_rows.sort(key=lambda x: x['date'])

# その馬の「そのレースより前」の偏差値平均をレーティングにする（情報漏れ防止）
def rating_before(name, date, min_runs=2):
    past = [r['dev'] for r in runs.get(name, []) if r['date'] < date]
    if len(past) < min_runs: return None, len(past)
    return statistics.mean(past), len(past)

targets = []
for rec in race_rows:
    rt, k = rating_before(rec['name'], rec['date'])
    if rt is None: continue
    targets.append({**rec, 'rating': rt, 'nruns': k})

print(f"レーティングが付いた出走: {len(targets):,}件"
      f"（過去2走以上ある馬のみ。全{len(race_rows):,}出走中）\n")

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
    print(f"{'区分':<30}{'n':>7}{'勝利':>6}{'勝率':>7}{'複勝率':>8}{'単回収':>8}{'複回収':>8}")
    for lab, rows in groups:
        a = agg(rows)
        if not a: print(f"{lab:<30}{0:>7}"); continue
        note = '' if a['wins'] >= 10 else '  ※的中10本未満'
        print(f"{lab:<30}{a['n']:>7,}{a['wins']:>6}{a['win']:>7.1%}{a['plc']:>8.1%}"
              f"{a['tan']:>8.0%}{a['fuku']:>8.0%}{note}")
    print()

def tier(r):
    if r >= 55: return 'A 偏差値55以上'
    if r >= 52: return 'B 52-55'
    if r >= 48: return 'C 48-52'
    if r >= 45: return 'D 45-48'
    return 'E 45未満'
TIERS = ['A 偏差値55以上','B 52-55','C 48-52','D 45-48','E 45未満']

show('レーティング単体で着順を判別できるか（全体）',
     [(t, [r for r in targets if tier(r['rating']) == t]) for t in TIERS])

# 核心: 同じ人気帯の中でレーティングが効くか＝市場が持っていない情報か
def band(nk):
    if nk is None: return None
    return ('1-3番人気' if nk <= 3 else '4-5番人気' if nk <= 5
            else '6-9番人気' if nk <= 9 else '10番人気以下')
for b in ['1-3番人気','4-5番人気','6-9番人気','10番人気以下']:
    show(f'{b} の中でレーティング別（＝オッズに無い情報か）',
         [(t, [r for r in targets if band(r['ninki']) == b and tier(r['rating']) == t])
          for t in TIERS])
