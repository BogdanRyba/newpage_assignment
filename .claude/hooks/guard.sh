#!/usr/bin/env bash
# PreToolUse(Edit|Write): refuse edits that must never happen.
# Exit 2 blocks the tool call and feeds the message back to the model.
set -euo pipefail

fp="$(python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("tool_input",{}).get("file_path",""))' 2>/dev/null || true)"
[ -z "$fp" ] && exit 0
base="$(basename "$fp")"

# Secrets: .env (and variants) are gitignored. Only .env.example is allowed.
case "$base" in
  .env|.env.*)
    if [ "$base" != ".env.example" ]; then
      echo "guard: refusing to write '$fp' — .env holds secrets and is gitignored. Edit .env.example instead." >&2
      exit 2
    fi
    ;;
esac

# Lockfiles are generated, not hand-edited.
case "$base" in
  package-lock.json|yarn.lock|pnpm-lock.yaml|poetry.lock|uv.lock)
    echo "guard: refusing to hand-edit lockfile '$base' — regenerate it via the package manager." >&2
    exit 2
    ;;
esac

# Applied migrations are immutable. A migration already tracked by git is applied history.
case "$fp" in
  */alembic/versions/*.py)
    if git ls-files --error-unmatch "$fp" >/dev/null 2>&1; then
      echo "guard: '$fp' is an applied migration. Create a NEW revision instead of editing history." >&2
      exit 2
    fi
    ;;
esac

exit 0
