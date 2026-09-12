#!/usr/bin/env bash
# 中央1-8Rを月ごとに収集する。
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
# 使い方:  bash scripts/collect_1_8R.sh 2025-01 2025-02 ...
set -u
LOG=${COLLECT_LOG:-/tmp/collect_1_8R.log}
for M in "$@"; do
  echo "=== $M 開始 $(date -u +%H:%M:%S) ===" | tee -a "$LOG"
  python3 -m keiba.cli collect --month "$M" --venue 中央 --races 1-8 \
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
