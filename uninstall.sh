#!/usr/bin/env bash
set -e
NAME="projectize"
# 依安裝來源移除：custom-tools 市集（市集本身保留，可能還有其他 plugin）或本機開發用 marketplace
if claude plugin uninstall "${NAME}@custom-tools" 2>/dev/null; then
	:
else
	claude plugin uninstall "${NAME}@${NAME}"
	claude plugin marketplace remove "$NAME"
fi

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
rm -f "$CLAUDE_DIR/commands/$NAME.md"

echo "✓ 已移除 ${NAME}。重啟 CC 套用。"
