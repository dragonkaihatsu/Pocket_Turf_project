"""スコア上位4頭(5頭)の馬連BOXが的中したときの、実際の配当分布を測る。

全馬連の配当分布を使うと過大評価になる。BOXが当たるのは人気寄りの組に
偏るため、条件付き分布は全体より低いはず。ここを実測で確かめる。
"""
import json, random, statistics, sys
from itertools import combinations
from pathlib import Path
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
import keiba.scoring as sc
from backtest import load_race, load_race_info, race_date, race_venue, settle
from keiba.cli import _load_horse_records
from keiba.marks import assign_marks
from keiba.racefiles import result_files

ratings = json.loads(Path("data/profiles/jra/ratings.json").read_text(encoding="utf-8"))
sc.load_ratings = lambda *a, **k: ratings
kyori_by = load_race_info("data/profiles/jra/race_info.csv")
records = _load_horse_records("data/profiles/jra/horse_records_corpus.csv")

pay = {("3倍以上",4): [], ("3倍以上",5): [], ("2倍台",4): [], ("1倍台",4): []}
tried = {k: 0 for k in pay}
d = Path("data/collected_jra")
for res in result_files(d):
    stem = res.name[:-len("_結果.csv")]
    race = load_race(d, stem)
    if race is None: continue
    fav = min((h for h in race["horses"] if h.ninki),
              key=lambda h: h.ninki, default=None)
    if fav is None or not fav.tansho_odds: continue
    o = fav.tansho_odds
    tier = "1倍台" if o < 2 else "2倍台" if o < 3 else "3倍以上"
    scores = sc.score_race(race["horses"], None, kyori=kyori_by.get(stem),
                           records=records, as_of=race_date(stem),
                           venue=race_venue(stem))
    marked = assign_marks(scores, baba="良")
    order = [m.score.horse.umaban for m in marked]
    for w in (4, 5):
        key = (tier, w)
        if key not in pay or len(order) < w: continue
        tried[key] += 1
        tickets = [frozenset(c) for c in combinations(order[:w], 2)]
        inv, ret = settle("馬連", tickets, race)
        if ret > 0:
            pay[key].append(ret)

print("■ スコア上位N頭の馬連BOXが的中したときの配当（中央9-12R 実測）")
print(f"{'帯':<9}{'N頭':>4}{'対象R':>7}{'的中':>6}{'的中率':>8}"
      f"{'25%':>8}{'中央値':>8}{'75%':>9}")
for key in (("3倍以上",4), ("3倍以上",5), ("2倍台",4), ("1倍台",4)):
    v = sorted(pay[key]); n = tried[key]
    if not v: continue
    q = statistics.quantiles(v, n=4)
    print(f"{key[0]:<9}{key[1]:>4}{n:>7,}{len(v):>6}{len(v)/n:>8.1%}"
          f"{q[0]:>8,.0f}{q[1]:>8,.0f}{q[2]:>9,.0f}")

out = Path("data/profiles/jra/box_payouts.json")
json.dump({f"{k[0]}|{k[1]}": {"試行": tried[k], "配当": pay[k]} for k in pay},
          open(out, "w"), ensure_ascii=False)
print(f"\n書き出し: {out}")
