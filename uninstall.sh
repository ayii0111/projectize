#!/usr/bin/env bash
set -e
NAME="projectize"
claude plugin uninstall "${NAME}@${NAME}"
claude plugin marketplace remove "$NAME"

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
rm -f "$CLAUDE_DIR/commands/$NAME.md"

echo "✓ 已移除 ${NAME}。重啟 CC 套用。"
