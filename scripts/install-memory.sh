#!/usr/bin/env bash
# このリポジトリの CLAUDE.md を、Claude Code の「ユーザーレベルメモリ」に
# @import として登録する。
#
# 背景:
#   Claude（チャット）のメモリと Claude Code のメモリは共有されない。
#   Claude Code 側のメモリは CLAUDE.md ファイルで持ち込む。
#
# いつ使うか:
#   このリポジトリの中で Claude Code を起動する分には、リポジトリ直下の
#   CLAUDE.md が「プロジェクトメモリ」として自動で読み込まれるので、
#   このスクリプトは不要。
#   別のディレクトリで起動したセッションにも競馬予想の仕様を効かせたい
#   場合だけ実行する。
#
# 注意:
#   ユーザーレベルメモリは全プロジェクトの全セッションで読み込まれる。
#   競馬と無関係な作業のときも約70行ぶんコンテキストを消費するので、
#   常用しないなら実行しなくてよい。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$REPO_ROOT/CLAUDE.md"
CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
USER_MEMORY="$CONFIG_DIR/CLAUDE.md"
IMPORT_LINE="@$SOURCE"

if [ ! -f "$SOURCE" ]; then
  echo "エラー: $SOURCE が見つかりません" >&2
  exit 1
fi

mkdir -p "$CONFIG_DIR"

if [ -f "$USER_MEMORY" ] && grep -qF "$IMPORT_LINE" "$USER_MEMORY"; then
  echo "登録済みです: $USER_MEMORY"
  echo "  → $IMPORT_LINE"
  exit 0
fi

if [ ! -f "$USER_MEMORY" ]; then
  printf '# 個人用メモリ\n\n' > "$USER_MEMORY"
  echo "作成しました: $USER_MEMORY"
fi

printf '\n## 競馬予想システム（100点スコアリング）\n%s\n' "$IMPORT_LINE" >> "$USER_MEMORY"

echo "登録しました: $USER_MEMORY"
echo "  → $IMPORT_LINE"
echo
echo "次回以降のセッションから読み込まれます。"
echo "セッション内で /context を実行し、Memory files に上記が出れば成功です。"
