"""仮説検証: 前走と今走の「実際のメンバーの質の差分」は妙味になるか。

本人の言葉（2026-09-11）:
  強い相手と戦って負けたけど、弱い組み合わせになって張り合えそうとか、
  逆に前走は過剰で良いように着差がついたけど実はそんなに強くない、
  というのが分かればいい。（例: ファウストラーゼン、ジョバンニ）

前回失敗した「相手の質（水準）」との違い:
  水準はレース名＝クラスから読めるので市場に織り込まれていた。今回測るのは
  **前走のメンバー質 − 今走のメンバー質（差分）**。クラス名は新聞に載るが、
  「同じ3勝クラスでも中身が濃いか薄いか」は載らない。差分は自動照合でしか
  見えない組み合わせなので、織り込まれていない可能性がある。

メンバー質の定義（情報漏れなし）:
  そのレースの出走馬それぞれについて「今走の日付より前」の勝率を取り、平均する。
  前走メンバー質は、前走の相手が**前走後・今走前**に挙げた成績も含む
  （＝「あの相手はその後も勝っている」という、今走時点で分かる情報）。
"""
import csv, glob, re, bisect, statistics
from collections import defaultdict
from datetime import date
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
from keiba.racefiles import result_paths  # 対象レース帯の絞り込みを1か所に集約

STAKE = 100
DATE_RE = re.compile(r'.*/(\d{4}-\d{2}-\d{2})_')

races = {}
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
    names = []
    for r in csv.DictReader(open(f, encoding='utf-8-sig')):
        nm = (r.get('馬名') or '').strip(); ub = r.get('馬番') or ''
        ch = r.get('着順') or ''; nk = r.get('人気') or ''
        if not (nm and ub.isdigit() and ch.isdigit()): continue
        rec = {'name': nm, 'date': d, 'stem': stem, 'chaku': int(ch),
               'ninki': int(nk) if nk.isdigit() else None,
               'interval': interval.get(nm),
               'tan': pay_t.get(int(ub), 0), 'fuku': pay_f.get(int(ub), 0)}
        by_horse[nm].append(rec); names.append(nm)
    if names: races[stem] = {'date': d, 'names': names}
for v in by_horse.values(): v.sort(key=lambda x: x['date'])
# 二分探索用に日付だけの配列を用意
dates_of = {nm: [r['date'] for r in lst] for nm, lst in by_horse.items()}

def prior(nm, cutoff):
    """cutoff より前の (出走数, 勝利数)。"""
    lst = by_horse.get(nm, [])
    i = bisect.bisect_left(dates_of[nm], cutoff)
    if i == 0: return 0, 0
    return i, sum(1 for r in lst[:i] if r['chaku'] == 1)

def field_quality(stem, cutoff, exclude):
    """そのレースの出走馬の、cutoff時点までの勝率の平均。"""
    race = races.get(stem)
    if not race: return None
    rates = []
    for nm in race['names']:
        if nm == exclude: continue
        s, w = prior(nm, cutoff)
        if s >= 2: rates.append(w / s)
    if len(rates) < 3: return None
    return statistics.mean(rates)

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

rows = []
for prev, cur in pairs:
    fq_prev = field_quality(prev['stem'], cur['date'], prev['name'])
    fq_now = field_quality(cur['stem'], cur['date'], cur['name'])
    if fq_prev is None or fq_now is None: continue
    rows.append({**cur, 'delta': fq_prev - fq_now,
                 'fq_prev': fq_prev, 'fq_now': fq_now, 'prev_chaku': prev['chaku']})
print(f"メンバー質の差分が測れた出走: {len(rows):,}件 / 前走ペア{len(pairs):,}組")
d = [r['delta'] for r in rows]
print(f"差分の分布: 中央値{statistics.median(d):+.3f} "
      f"25%点{statistics.quantiles(d, n=4)[0]:+.3f} 75%点{statistics.quantiles(d, n=4)[2]:+.3f}\n")

def agg(rs):
    n = len(rs)
    if not n: return None
    w = sum(1 for r in rs if r['chaku'] == 1)
    return {'n': n, 'wins': w, 'win': w/n,
            'plc': sum(1 for r in rs if r['chaku'] <= 3)/n,
            'tan': sum(r['tan'] for r in rs)/(n*STAKE),
            'fuku': sum(r['fuku'] for r in rs)/(n*STAKE)}

def show(title, groups):
    print(f"── {title}")
    print(f"{'区分':<30}{'n':>7}{'勝利':>6}{'勝率':>7}{'複勝率':>8}{'単回収':>8}{'複回収':>8}")
    for lab, rs in groups:
        a = agg(rs)
        if not a: print(f"{lab:<30}{0:>7}"); continue
        note = '' if a['wins'] >= 10 else '  ※的中10本未満'
        print(f"{lab:<30}{a['n']:>7,}{a['wins']:>6}{a['win']:>7.1%}{a['plc']:>8.1%}"
              f"{a['tan']:>8.0%}{a['fuku']:>8.0%}{note}")
    print()

def dt(x):
    if x >= 0.06: return 'A 相手弱化(大)'
    if x >= 0.02: return 'B 相手弱化(小)'
    if x > -0.02: return 'C ほぼ同等'
    if x > -0.06: return 'D 相手強化(小)'
    return 'E 相手強化(大)'
DT = ['A 相手弱化(大)','B 相手弱化(小)','C ほぼ同等','D 相手強化(小)','E 相手強化(大)']

show('メンバー質の差分（全体）', [(t, [r for r in rows if dt(r['delta']) == t]) for t in DT])

def band(nk):
    if nk is None: return None
    return ('1-3番人気' if nk <= 3 else '4-5番人気' if nk <= 5
            else '6-9番人気' if nk <= 9 else '10番人気以下')
for b in ['1-3番人気','4-5番人気','6-9番人気','10番人気以下']:
    show(f'{b} の中で差分別（＝オッズに無い情報か）',
         [(t, [r for r in rows if band(r['ninki']) == b and dt(r['delta']) == t]) for t in DT])

# 本人の2パターンを直接
show('本人の2パターン', [
    ('前走大敗(二桁)×相手弱化', [r for r in rows if r['prev_chaku'] >= 10 and r['delta'] >= 0.02]),
    ('前走大敗(二桁)×相手強化', [r for r in rows if r['prev_chaku'] >= 10 and r['delta'] <= -0.02]),
    ('前走好走(1-2着)×相手強化', [r for r in rows if r['prev_chaku'] <= 2 and r['delta'] <= -0.02]),
    ('前走好走(1-2着)×相手弱化', [r for r in rows if r['prev_chaku'] <= 2 and r['delta'] >= 0.02]),
])

# ---- 独立検証: 2025年と2026年に割る ----
print("=" * 76)
for per in ('2025', '2026'):
    sel = [r for r in rows if r['date'].startswith(per)]
    show(f'{per}年（独立検証）', [
        ('前走二桁×相手弱化', [r for r in sel if r['prev_chaku'] >= 10 and r['delta'] >= 0.02]),
        ('前走二桁×相手強化', [r for r in sel if r['prev_chaku'] >= 10 and r['delta'] <= -0.02]),
        ('前走1-2着×相手弱化', [r for r in sel if r['prev_chaku'] <= 2 and r['delta'] >= 0.02]),
        ('前走1-2着×相手強化', [r for r in sel if r['prev_chaku'] <= 2 and r['delta'] <= -0.02]),
    ])
    show(f'{per}年 人気帯内（回収率が出ていたセル）', [
        ('4-5番人気×弱化大', [r for r in sel if band(r['ninki'])=='4-5番人気' and dt(r['delta'])=='A 相手弱化(大)']),
        ('4-5番人気×強化', [r for r in sel if band(r['ninki'])=='4-5番人気' and r['delta'] <= -0.02]),
        ('6-9番人気×弱化', [r for r in sel if band(r['ninki'])=='6-9番人気' and r['delta'] >= 0.02]),
        ('6-9番人気×強化', [r for r in sel if band(r['ninki'])=='6-9番人気' and r['delta'] <= -0.02]),
    ])

# ファウストラーゼンの函館記念は差分いくつだったか
print("=" * 76)
for r in rows:
    if r['name'] in ('ファウストラーゼン', 'ジョバンニ'):
        race = r['stem'].split('_', 1)[1] if '_' in r['stem'] else r['stem']
        print(f"{r['name']:<12}{r['date']} {race:<30} {r['chaku']:>2}着 "
              f"{r['ninki'] or '-':>2}人気  前走{r['prev_chaku']:>2}着  "
              f"メンバー質 前走{r['fq_prev']:.3f}→今走{r['fq_now']:.3f} "
              f"差分{r['delta']:+.3f} {dt(r['delta'])}")
