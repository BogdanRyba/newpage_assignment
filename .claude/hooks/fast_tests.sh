#!/usr/bin/env bash
# Stop hook: run the fast unit subset so a turn never ends on red.
# Deterministic (cassette replay), excludes integration. No-ops without pytest.
set -euo pipefail

command -v pytest >/dev/null 2>&1 || exit 0
[ -d backend/tests/unit ] || exit 0

cd backend
if ! CASSETTE_MODE=replay pytest tests/unit -q -m "not integration" >/tmp/ariadne_fast_tests.log 2>&1; then
  echo "fast unit tests are red — see /tmp/ariadne_fast_tests.log" >&2
  exit 2
fi
exit 0
