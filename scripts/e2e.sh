#!/usr/bin/env bash
# Real browser E2E: drives the actual UI (Playwright/Chromium) against the real backend + Gemini,
# ingesting a public repo and asserting the streamed answer renders. Needs GEMINI_API_KEY in .env.
#
# The in-container browser must reach the API, so the frontend is served with
# NEXT_PUBLIC_API_BASE=http://api:8000 (compose DNS) — different from the host-browser demo
# (localhost:8000). This recreates the stack with that env; restore the demo afterwards with
# `docker compose up -d` (default env).
set -uo pipefail
cd "$(dirname "$0")/.."

export NEXT_PUBLIC_API_BASE="http://api:8000"

echo "== bringing up stack for E2E (frontend → api:8000) =="
docker compose up -d --build postgres qdrant redis api worker frontend

echo "== waiting for api health =="
until [ "$(docker inspect -f '{{.State.Health.Status}}' ariadne-api-1 2>/dev/null)" = "healthy" ]; do
  sleep 2
done

echo "== running Playwright E2E (real browser, real Gemini) =="
docker compose run --rm playwright
rc=$?

if [ "$rc" -eq 0 ]; then
  echo "== E2E PASSED =="
else
  echo "== E2E FAILED (exit $rc) =="
fi

# Always restore the host-browser demo (frontend → localhost:8000) so the E2E never strands it.
echo "== restoring host demo (frontend → localhost:8000) =="
NEXT_PUBLIC_API_BASE=http://localhost:8000 docker compose up -d frontend >/dev/null 2>&1 || true
exit $rc
