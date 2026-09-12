"""騎手プレミアム検証・第2版: 短期免許の外国人騎手を分離する。

第1版ではD層(50騎乗未満)の回収率が高く出たが、そこにモレイラ・バデル等の
短期免許外国人トップジョッキーが混ざっていた（いい馬にだけ乗るため）。
仮説「マイナー騎手は名前のぶん人気を割り引かれる＝妙味」を検証するには
彼らを除く必要がある。
"""
import csv, glob, re
from collections import defaultdict
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
from keiba.racefiles import result_paths  # 対象レース帯の絞り込みを1か所に集約

STAKE = 100
# カタカナ/ラテン文字主体の騎手名＝外国人（短期免許・通年免許とも）
FOREIGN_RE = re.compile(r'^[ァ-ヶーA-Za-z][ァ-ヶーA-Za-z・]*$')

rides = defaultdict(int)
rows_all = []
for f in result_paths('data/collected_jra'):
    pay_t, pay_f = {}, {}
    try:
        for p in csv.DictReader(open(f.replace('_結果.csv','_配当.csv'), encoding='utf-8-sig')):
            if p.get('券種') == '単勝': pay_t[int(p['組み合わせ'])] = int(p['配当'])
            elif p.get('券種') == '複勝': pay_f[int(p['組み合わせ'])] = int(p['配当'])
    except (FileNotFoundError, ValueError):
        pass
    for r in csv.DictReader(open(f, encoding='utf-8-sig')):
        j = (r.get('騎手') or '').strip()
        ninki, umaban, chaku = r.get('人気') or '', r.get('馬番') or '', r.get('着順') or ''
        if not (j and ninki.isdigit() and umaban.isdigit() and chaku.isdigit()):
            continue
        rides[j] += 1
        rows_all.append({'j': j, 'ninki': int(ninki), 'chaku': int(chaku),
                         'tan': pay_t.get(int(umaban), 0), 'fuku': pay_f.get(int(umaban), 0)})

def is_foreign(j):
    # 減量記号(☆▲△◇)を外してから判定
    return bool(FOREIGN_RE.match(re.sub(r'^[☆▲△◇◎]', '', j)))

def tier(j):
    if is_foreign(j): return 'X 外国人騎手'
    n = rides[j]
    if n >= 400: return 'A 一軍(400騎乗超)'
    if n >= 150: return 'B 中堅(150-399)'
    if n >= 50:  return 'C 少数(50-149)'
    return 'D 極少(50未満)'

def band(n):
    if n <= 1: return '1番人気'
    if n == 2: return '2番人気'
    if n == 3: return '3番人気'
    if n <= 5: return '4-5番人気'
    if n <= 9: return '6-9番人気'
    return '10番人気以下'

cells = defaultdict(lambda: {'n':0,'win':0,'plc':0,'tan':0,'fuku':0})
for r in rows_all:
    c = cells[(band(r['ninki']), tier(r['j']))]
    c['n'] += 1
    c['win'] += 1 if r['chaku'] == 1 else 0
    c['plc'] += 1 if r['chaku'] <= 3 else 0
    c['tan'] += r['tan']; c['fuku'] += r['fuku']

bands = ['1番人気','2番人気','3番人気','4-5番人気','6-9番人気','10番人気以下']
tiers = ['A 一軍(400騎乗超)','B 中堅(150-399)','C 少数(50-149)','D 極少(50未満)','X 外国人騎手']
fo = sorted({j for j in rides if is_foreign(j)}, key=lambda x: -rides[x])
print('外国人として分離した騎手:', ' '.join(f'{j}({rides[j]})' for j in fo[:12]), '...\n')
print(f"{'人気帯':<14}{'騎手ティア':<18}{'n':>7}{'勝率':>7}{'複勝率':>8}{'単回収':>8}{'複回収':>8}")
for b in bands:
    for t in tiers:
        c = cells.get((b,t))
        if not c or c['n'] < 30: continue
        print(f"{b:<14}{t:<18}{c['n']:>7,}{c['win']/c['n']:>7.1%}{c['plc']/c['n']:>8.1%}"
              f"{c['tan']/(c['n']*STAKE):>8.0%}{c['fuku']/(c['n']*STAKE):>8.0%}")
    print()
