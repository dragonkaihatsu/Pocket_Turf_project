"""相手の質（横の比較）を素材にした偏差値は、オッズに無い情報になるか。

上がり3F偏差値は新聞に載っている素材なので市場に織り込まれていた。
新聞に載っていないのは「誰に負けたのか、その相手はその後どうだったか」。
新聞は「前走5着 0.3秒差」しか書かない。我々は全出走馬を持っているので、
**前走で自分を負かした馬たちのその後**を追える。

  前走で自分より上に来た馬たちが、その後（今走より前まで）どれだけ勝って
  いるか = 「強い相手に負けた」のか「弱い相手に負けた」のか

情報漏れ防止: 相手のその後の成績は、**今走の日付より前**のものだけを数える。
"""
import csv, glob, re, statistics
from collections import defaultdict
from datetime import date
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
from keiba.racefiles import result_paths  # 対象レース帯の絞り込みを1か所に集約

STAKE = 100
DATE_RE = re.compile(r'.*/(\d{4}-\d{2}-\d{2})_')

races = {}          # stem -> {date, rows:[{name,chaku,...}]}
by_horse = defaultdict(list)

for f in result_paths('data/collected_jra'):
    m = DATE_RE.match(f)
    if not m: continue
    d = m.group(1)
    stem = f.split('/')[-1][:-len('_結果.csv')]
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

    rows = []
    for r in csv.DictReader(open(f, encoding='utf-8-sig')):
        nm = (r.get('馬名') or '').strip(); ub = r.get('馬番') or ''
        ch = r.get('着順') or ''; nk = r.get('人気') or ''
        if not (nm and ub.isdigit() and ch.isdigit()): continue
        rec = {'name': nm, 'date': d, 'stem': stem, 'chaku': int(ch),
               'ninki': int(nk) if nk.isdigit() else None,
               'interval': interval.get(nm),
               'tan': pay_t.get(int(ub), 0), 'fuku': pay_f.get(int(ub), 0)}
        rows.append(rec); by_horse[nm].append(rec)
    if rows:
        races[stem] = {'date': d, 'rows': rows, 'field': len(rows)}
for v in by_horse.values(): v.sort(key=lambda x: x['date'])

def to_o(s):
    y, m, dd = (int(x) for x in s.split('-')); return date(y, m, dd).toordinal()

# 前走ペアを作る（間隔一致で検証済みのものだけ）
pairs = []
for nm, lst in by_horse.items():
    for i in range(1, len(lst)):
        cur = lst[i]
        if cur['interval'] is None: continue
        t = to_o(cur['date']) - cur['interval']
        for cand in lst[:i][::-1]:
            if abs(to_o(cand['date']) - t) <= 2:
                pairs.append((cand, cur)); break
print(f"前走ペア: {len(pairs):,}組")

def beaters_quality(prev, cur_date):
    """前走で自分より上に来た馬たちの「その後（今走より前まで）の勝率」。"""
    race = races.get(prev['stem'])
    if not race: return None, 0
    ahead = [r['name'] for r in race['rows'] if r['chaku'] < prev['chaku']]
    if not ahead: return None, 0
    wins = starts = 0
    for nm in ahead:
        for r in by_horse.get(nm, []):
            if prev['date'] < r['date'] < cur_date:   # 前走より後・今走より前
                starts += 1
                if r['chaku'] == 1: wins += 1
    if starts < 3: return None, starts
    return wins / starts, starts

enriched = []
for prev, cur in pairs:
    if prev['chaku'] <= 3:      # 自分が3着以内なら「負けた相手」の話にならない
        continue
    q, k = beaters_quality(prev, cur['date'])
    if q is None: continue
    enriched.append({**cur, 'bq': q, 'bq_starts': k, 'prev_chaku': prev['chaku']})

print(f"相手の質が測れた出走: {len(enriched):,}件"
      f"（前走4着以下・相手の後続出走3走以上）\n")

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
    print(f"{'区分':<28}{'n':>7}{'勝利':>6}{'勝率':>7}{'複勝率':>8}{'単回収':>8}{'複回収':>8}")
    for lab, rows in groups:
        a = agg(rows)
        if not a: print(f"{lab:<28}{0:>7}"); continue
        note = '' if a['wins'] >= 10 else '  ※的中10本未満'
        print(f"{lab:<28}{a['n']:>7,}{a['wins']:>6}{a['win']:>7.1%}{a['plc']:>8.1%}"
              f"{a['tan']:>8.0%}{a['fuku']:>8.0%}{note}")
    print()

def qt(q):
    if q >= 0.20: return 'A 相手が強い(勝率20%超)'
    if q >= 0.12: return 'B 12-20%'
    if q >= 0.06: return 'C 6-12%'
    return 'D 相手が弱い(6%未満)'
QT = ['A 相手が強い(勝率20%超)','B 12-20%','C 6-12%','D 相手が弱い(6%未満)']

show('前走で負けた相手の質で分ける（全体）',
     [(t, [r for r in enriched if qt(r['bq']) == t]) for t in QT])

def band(nk):
    if nk is None: return None
    return ('1-3番人気' if nk <= 3 else '4-5番人気' if nk <= 5
            else '6-9番人気' if nk <= 9 else '10番人気以下')
for b in ['1-3番人気','4-5番人気','6-9番人気','10番人気以下']:
    show(f'{b} の中で相手の質別（＝オッズに無い情報か）',
         [(t, [r for r in enriched if band(r['ninki']) == b and qt(r['bq']) == t])
          for t in QT])
