"""仮説検証: ブリンカー（遮眼革）を着けると走るのか。

本人の言葉（2026-09-12）:
  ブリンカー着用で成績が上がった、回収率がとれるかの検証。
  必ずしもいいとは言い切れず、やる気を失うこともあります。

## なぜ検証する価値があるか

**馬柱には「B」が載っている**（netkeibaは馬名の末尾に付ける）。だから
「今日Bを着けている」こと自体は市場も見ており、既に値段に入っている
可能性が高い。既出の設計原則どおりなら妙味は出ない。

しかし**「前走は着けていなかったのに今走から着けた」という変化は、
2枚の馬柱を突き合わせないと見えない**。これは不利痕跡（前走の脚質と
4角位置の矛盾）と同じ「自動照合しなければ見えない組み合わせ」の型で、
そちらは唯一独立検証を通っている。

## 「やる気を失う」側も見る

ブリンカーは視野を狭めて集中させる装具だが、馬によっては逆効果になる。
着ける側の効果だけを探すと、効いた例だけを拾って平均を過大評価する。
そこで **解除（前走B→今走なし）** も対照として並べ、さらに
前走着順・脚質・前走の不利痕跡で切って、効く条件と逆効果の条件を分ける。

    python3 scripts/blinker_test.py
"""
from __future__ import annotations

import csv
import glob
import re
from collections import defaultdict
from datetime import date

STAKE = 100
DATE_RE = re.compile(r'.*/(\d{4}-\d{2}-\d{2})_')
# 9-12Rに絞る。1-8Rの収集が途中なので混ぜると期間の偏りが入る
RACE_NO_RE = re.compile(r'_\D+?(\d{2})R_')
WANTED = {9, 10, 11, 12}


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


by_horse: dict[str, list[dict]] = defaultdict(list)
for f in sorted(glob.glob('data/collected_jra/*_結果.csv')):
    m = DATE_RE.match(f)
    rn = RACE_NO_RE.search(f)
    if not m or not rn or int(rn.group(1)) not in WANTED:
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

    # ブリンカーは出走馬CSV（馬柱）にしかない。結果ページには出ない
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
        if not (nm and ub.isdigit()):
            continue
        e = ent.get(nm, {})
        by_horse[nm].append({
            'date': d, 'chaku': int(r['着順']), 'field': len(rows),
            'ninki': int(nk) if nk.isdigit() else None,
            'agari_rank': agari_rank.get(ub), 'pos4': pos4.get(int(ub)),
            'kyaku': e.get('kyaku', ''), 'interval': e.get('interval'),
            'blinker': e.get('blinker'),      # None = 馬柱が無く不明
            'tan': pay_t.get(int(ub), 0), 'fuku': pay_f.get(int(ub), 0),
        })
for v in by_horse.values():
    v.sort(key=lambda x: x['date'])


def to_o(s: str) -> int:
    y, mo, dd = (int(x) for x in s.split('-'))
    return date(y, mo, dd).toordinal()


# 前走間隔日数と日付差が一致するペアだけ採る（間に挟まれた本当の前走の取りこぼしを除く）
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

# ブリンカーの有無が両方分かるペアだけを対象にする
known = [(p, c) for p, c in pairs
         if p['blinker'] is not None and c['blinker'] is not None]


def agg(rows):
    n = len(rows)
    if not n:
        return None
    w = sum(1 for r in rows if r['chaku'] == 1)
    plc_hits = sum(1 for r in rows if r['chaku'] <= 3)
    return {'n': n, 'wins': w, 'win': w / n,
            'plc_hits': plc_hits,      # 複勝で評価するときの「実際の的中本数」
            'plc': plc_hits / n,
            'tan': sum(r['tan'] for r in rows) / (n * STAKE),
            'fuku': sum(r['fuku'] for r in rows) / (n * STAKE)}


def show(title, groups):
    print(f"── {title}")
    print(f"{'区分':<34}{'n':>6}{'勝利':>6}{'勝率':>7}{'複勝率':>8}"
          f"{'単回収':>8}{'複回収':>8}")
    for lab, rows in groups:
        a = agg(rows)
        if not a:
            print(f"{lab:<34}{0:>6}")
            continue
        note = '' if a['wins'] >= 10 else '  ※的中10本未満'
        print(f"{lab:<34}{a['n']:>6,}{a['wins']:>6}{a['win']:>7.1%}"
              f"{a['plc']:>8.1%}{a['tan']:>8.0%}{a['fuku']:>8.0%}{note}")
    print()


def trans(p, c) -> str:
    """前走→今走のブリンカーの変化。"""
    if not p['blinker'] and c['blinker']:
        return '新規装着'
    if p['blinker'] and c['blinker']:
        return '継続装着'
    if p['blinker'] and not c['blinker']:
        return '解除'
    return 'なし'


def sel(rows, tag, extra=None):
    return [c for p, c in rows
            if trans(p, c) == tag and (extra is None or extra(p, c))]


def furi_B(p):
    """前走で前に行く脚質なのに4角後方＝出遅れ/掛かって沈んだ疑い。"""
    return (p['kyaku'] in ('逃げ', '先行') and p['pos4'] is not None
            and p['pos4'] >= 6)


print(f"9-12Rの前走ペア {len(pairs):,}組 / "
      f"ブリンカー有無が両走とも分かる {len(known):,}組\n")

TAGS = ('新規装着', '継続装着', '解除', 'なし')
show('ブリンカーの変化（全期間）',
     [(t, sel(known, t)) for t in TAGS])

print("=" * 78)
print("【1】市場は「今日Bを着けている」ことを織り込んでいるか（人気帯内）\n")
BANDS = (('1-3番人気', lambda n: n and n <= 3),
         ('4-5番人気', lambda n: n and 4 <= n <= 5),
         ('6-9番人気', lambda n: n and 6 <= n <= 9),
         ('10番人気以下', lambda n: n and n >= 10))
for lab, f_band in BANDS:
    show(f'{lab} の中で',
         [(t, [c for c in sel(known, t) if f_band(c['ninki'])]) for t in TAGS])

print("=" * 78)
print("【2】どんな馬に着けると効くのか（新規装着を条件で切る）\n")
show('新規装着を前走着順で切る', [
    ('新規装着 × 前走二桁着順', sel(known, '新規装着', lambda p, c: p['chaku'] >= 10)),
    ('新規装着 × 前走6-9着', sel(known, '新規装着', lambda p, c: 6 <= p['chaku'] <= 9)),
    ('新規装着 × 前走1-5着', sel(known, '新規装着', lambda p, c: p['chaku'] <= 5)),
    ('対照 なし × 前走二桁着順', sel(known, 'なし', lambda p, c: p['chaku'] >= 10)),
    ('対照 なし × 前走1-5着', sel(known, 'なし', lambda p, c: p['chaku'] <= 5)),
])

show('新規装着を前走の不利痕跡で切る（掛かって沈んだ馬に着けたか）', [
    ('新規装着 × 前走 前に行って沈んだ', sel(known, '新規装着', lambda p, c: furi_B(p))),
    ('新規装着 × それ以外', sel(known, '新規装着', lambda p, c: not furi_B(p))),
    ('対照 なし × 前走 前に行って沈んだ', sel(known, 'なし', lambda p, c: furi_B(p))),
])

show('新規装着を今走の脚質で切る', [
    (f'新規装着 × {k}', sel(known, '新規装着', lambda p, c, k=k: c['kyaku'] == k))
    for k in ('逃げ', '先行', '差し', '追込')
])

print("=" * 78)
print("【3】期間で割った独立検証（2025=材料 / 2026=検証）\n")
for per, lab in (('2025', '2025年'), ('2026', '2026年')):
    s = [(p, c) for p, c in known if c['date'].startswith(per)]
    show(f'{lab}', [(t, sel(s, t)) for t in TAGS])

print("=" * 78)
print("【4】期間で割って残るのはどれか（主指標は複勝率と複勝回収率）\n")
print("単勝回収率は裾が重く、これまでの検証でも一度も再現していない。")
print("正解率を主指標に据えた方針（CLAUDE.md）に合わせ、複勝側で見る。\n")

SUBS = [
    ('解除（前走B→今走なし）', lambda p, c: trans(p, c) == '解除'),
    ('新規装着', lambda p, c: trans(p, c) == '新規装着'),
    ('新規装着 × 前走1-5着', lambda p, c: trans(p, c) == '新規装着' and p['chaku'] <= 5),
    ('新規装着 × 前走二桁着順', lambda p, c: trans(p, c) == '新規装着' and p['chaku'] >= 10),
    ('継続装着', lambda p, c: trans(p, c) == '継続装着'),
    ('対照 なし', lambda p, c: trans(p, c) == 'なし'),
]
# 「実際の的中本数10本以上」という母数基準は、評価する券種の的中で数える。
# 複勝で評価しているのに勝利数で判定すると、基準を厳しく取り違える
print(f"{'区分':<30}"
      f"{'2025 n':>8}{'複勝率':>8}{'複回収':>8}{'複的中':>7}"
      f"{'2026 n':>8}{'複勝率':>8}{'複回収':>8}{'複的中':>7}")
for lab, f_sub in SUBS:
    line = f"{lab:<30}"
    for per in ('2025', '2026'):
        rows = [c for p, c in known
                if c['date'].startswith(per) and f_sub(p, c)]
        a = agg(rows)
        if not a:
            line += f"{0:>8}{'—':>8}{'—':>8}{0:>7}"
            continue
        mark = '' if a['plc_hits'] >= 10 else '*'
        line += (f"{a['n']:>8,}{a['plc']:>8.1%}{a['fuku']:>8.0%}"
                 f"{str(a['plc_hits']) + mark:>7}")
    print(line)
print("  * = 複勝の的中が10本未満（母数基準を満たさない）\n")

print("── 人気帯内の複勝率リフト（同じ価格帯で比べる）")
print(f"{'人気帯':<14}{'区分':<10}"
      f"{'2025 n':>8}{'複勝率':>8}{'リフト':>8}"
      f"{'2026 n':>8}{'複勝率':>8}{'リフト':>8}")
for lab, f_band in BANDS:
    for tag in ('新規装着', '解除', '継続装着'):
        line = f"{lab:<14}{tag:<10}"
        for per in ('2025', '2026'):
            base = [c for p, c in known
                    if c['date'].startswith(per) and f_band(c['ninki'])]
            rows = [c for p, c in known
                    if c['date'].startswith(per) and f_band(c['ninki'])
                    and trans(p, c) == tag]
            if len(rows) < 30 or not base:
                line += f"{len(rows):>8}{'—':>8}{'—':>8}"
                continue
            r = sum(1 for c in rows if c['chaku'] <= 3) / len(rows)
            b = sum(1 for c in base if c['chaku'] <= 3) / len(base)
            line += f"{len(rows):>8}{r:>8.1%}{(r - b) * 100:>+7.1f}p"
        print(line)
