"""馬体重の推移（増え続け／減り続け）の該当母数を数えるだけ。判定はしない。"""
import re, sys, csv, collections
sys.path.insert(0, '.')
from keiba.racefiles import result_files, race_venue

DELTA = re.compile(r'\(([+-]\d+)\)')

# 馬名 -> [(日付, 場, R, delta, 着順)]
hist = collections.defaultdict(list)
files = result_files('data/collected_jra', races='1-12')
for f in files:
    m = re.match(r'(\d{4}-\d{2}-\d{2})_(\D+?)(\d{2})R_', f.name)
    if not m:
        continue
    date, ba, r = m.group(1), m.group(2), int(m.group(3))
    with open(f, encoding='utf-8-sig') as fh:
        for row in csv.DictReader(fh):
            d = DELTA.search(row.get('馬体重') or '')
            if not d:
                continue
            try:
                chaku = int(row['着順'])
            except (ValueError, KeyError, TypeError):
                chaku = None
            hist[row['馬名']].append((date, ba, r, int(d.group(1)), chaku))

target = {'9', '10', '11', '12'}
cnt = collections.Counter()
for name, runs in hist.items():
    runs.sort()
    for i, (date, ba, r, dl, chaku) in enumerate(runs):
        if r < 9 or chaku is None:
            continue
        prev = [x[3] for x in runs[max(0, i-3):i]]
        if len(prev) < 3:
            cnt['前3走の増減が揃わない'] += 1
            continue
        cnt['対象（前3走の増減が分かる）'] += 1
        if all(x < 0 for x in prev):
            cnt['3走連続で減'] += 1
        elif all(x > 0 for x in prev):
            cnt['3走連続で増'] += 1
        else:
            cnt['まちまち'] += 1

print(f"結果CSV {len(files)}本 / 馬体重の増減が読めた馬 {len(hist)}頭")
for k in ['対象（前3走の増減が分かる）', '3走連続で減', '3走連続で増', 'まちまち', '前3走の増減が揃わない']:
    print(f"  {k}: {cnt[k]:,}")
