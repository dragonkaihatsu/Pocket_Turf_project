#!/usr/bin/env bash
# 中央のレースを月ごとに収集する（帯は RACES で指定・既定1-8）。
#
# なぜ1-8Rが必要か: コース特性ごとの適性を測るには1頭あたりの過去走が
# 要るが、9-12Rだけの収集では過去走数の中央値が3走しかなく、
# 適性ではなくノイズを測ってしまう（scripts/course_traits.py）。
# 1-8Rを足すと同年の戦績がほぼ揃い、バックテストが可能になる。
#
# 月ごとに区切る理由: 全期間を一度に流すと数時間かかり、途中で
# 中断したときに進捗が分からない。collect は取得済みをスキップするので
# 月単位で回せば再開も安全。
#
# 帯を切り替えられるようにした理由（2026-09-12）: 1-8Rが21ヶ月ぶん揃って
# 開催日が正確に分かったところ、**9-12Rに86本(4.4%)の欠け**が見つかった。
# 9-12Rが1本も無い開催日が9日あり、開催日そのものが見えていなかった
# （`keiba.racefiles.month_coverage` は開催日を手元のファイルから数える）。
# 主指標はすべて9-12Rを土台にしているので、この穴は埋める必要がある。
#
# 使い方:
#   bash scripts/collect_months.sh 2025-01 2025-02 ...          # 既定1-8R
#   RACES=9-12 bash scripts/collect_months.sh 2026-01 2026-02   # 穴埋め
#
# collect は取得済みをスキップするので、埋まっている月を渡しても
# 欠けている分だけを取りに行く（二重取得にならない）。
set -u
RACES=${RACES:-1-8}
LOG=${COLLECT_LOG:-/tmp/collect_${RACES}.log}
for M in "$@"; do
  echo "=== $M (${RACES}R) 開始 $(date -u +%H:%M:%S) ===" | tee -a "$LOG"
  python3 -m keiba.cli collect --month "$M" --venue 中央 --races "$RACES" \
      --outdir data/collected_jra --cache-dir data/raw \
      --interval 1.5 >> "$LOG" 2>&1
  rc=$?
  n=$(ls data/collected_jra/*_結果.csv 2>/dev/null | wc -l)
  echo "=== $M 終了 rc=$rc 累計${n}レース $(date -u +%H:%M:%S) ===" | tee -a "$LOG"
  if [ $rc -ne 0 ]; then
    echo "!! $M で失敗。中断する" | tee -a "$LOG"
    exit $rc
  fi
done
echo "全月完了" | tee -a "$LOG"
