#!/usr/bin/env bash
set -e
NAME="projectize"
REPO="ayii0111/$NAME"
# 本機執行：用本地路徑
if [ -f "$(dirname "$0")/.claude-plugin/plugin.json" ]; then
	DIR="$(cd "$(dirname "$0")" && pwd)"
	claude plugin marketplace add "$DIR"
	CMD_SRC="$DIR/command-template/$NAME.md"
else
	# curl | bash：用 GitHub source
	claude plugin marketplace add "$REPO"
	CMD_SRC=""
fi
claude plugin install "${NAME}@${NAME}"

# 指令檔手動放進 ~/.claude/commands，避免顯示成「projectize:projectize」
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
mkdir -p "$CLAUDE_DIR/commands"
if [ -n "$CMD_SRC" ]; then
	cp "$CMD_SRC" "$CLAUDE_DIR/commands/$NAME.md"
else
	curl -fsSL "https://raw.githubusercontent.com/$REPO/main/command-template/$NAME.md" -o "$CLAUDE_DIR/commands/$NAME.md"
fi

echo "✓ 安裝完成。在 CC 執行 /reload-plugins 或重啟 CC 套用。"
