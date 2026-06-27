#!/usr/bin/env bash
# Single "are we done?" gate: lint + types + deterministic tests, backend + frontend.
# Runs inside containers so it works without a local toolchain. Used by /run-checks and CI.
set -euo pipefail
cd "$(dirname "$0")/.."

run() { echo; echo "== $1 =="; shift; "$@"; }

run "ruff (lint)"      docker compose run --rm --no-deps api ruff check .
run "ruff (format)"    docker compose run --rm --no-deps api ruff format --check .
run "mypy (types)"     docker compose run --rm --no-deps api mypy app
run "pytest (replay)"  docker compose run --rm --no-deps -e CASSETTE_MODE=replay api pytest -m "not integration" -q
run "frontend lint"    docker compose run --rm --no-deps frontend npm run lint
run "frontend types"   docker compose run --rm --no-deps frontend npm run typecheck
run "frontend test"    docker compose run --rm --no-deps frontend npm run test

echo; echo "All checks passed."
