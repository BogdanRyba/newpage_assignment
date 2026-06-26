#!/usr/bin/env bash
# PostToolUse(Edit|Write): auto-format the file that was just written.
# We don't trust the model to remember formatting — the hook enforces it.
# No-ops where the toolchain isn't on PATH (e.g. host without ruff/prettier).
set -euo pipefail

fp="$(python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("tool_input",{}).get("file_path",""))' 2>/dev/null || true)"
[ -z "$fp" ] && exit 0
[ -f "$fp" ] || exit 0

case "$fp" in
  *.py)
    if command -v ruff >/dev/null 2>&1; then
      ruff format "$fp" >/dev/null 2>&1 || true
      ruff check --fix "$fp" >/dev/null 2>&1 || true
    fi
    ;;
  *.ts|*.tsx|*.js|*.jsx|*.json|*.css|*.md)
    if command -v prettier >/dev/null 2>&1; then
      prettier --write "$fp" >/dev/null 2>&1 || true
    fi
    ;;
esac
exit 0
