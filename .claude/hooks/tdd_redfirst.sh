#!/usr/bin/env bash
# PostToolUse(Edit|Write): TDD red-first guard.
# When a BRAND-NEW test file is created, it should fail first (implementation not
# written yet). If it passes immediately, that's a smell — surfaced as advisory
# feedback to the model. No-ops if pytest isn't available (e.g. host without deps).
set -euo pipefail

fp="$(python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("tool_input",{}).get("file_path",""))' 2>/dev/null || true)"
[ -z "$fp" ] && exit 0

# Only newly-created test files (not yet tracked by git).
case "$fp" in
  */test_*.py|*_test.py|test_*.py) ;;
  *) exit 0 ;;
esac
if git ls-files --error-unmatch "$fp" >/dev/null 2>&1; then
  exit 0  # already tracked → not a new red-first test
fi
command -v pytest >/dev/null 2>&1 || exit 0

if CASSETTE_MODE=replay pytest "$fp" -q >/dev/null 2>&1; then
  echo "tdd: new test file '$fp' passes already. Confirm it actually exercises NEW behaviour — a red-first test should fail before the implementation exists." >&2
  exit 2  # PostToolUse: advisory feedback, does not undo the write
fi
exit 0
