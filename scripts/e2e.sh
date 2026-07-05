#!/usr/bin/env bash
# Real browser E2E: drives the actual UI (Playwright/Chromium) against the real backend + Gemini,
# ingesting a public repo and asserting the streamed answer renders. Needs GEMINI_API_KEY in .env.
set -uo pipefail
cd "$(dirname "$0")/.."

echo "== bringing up stack for E2E =="
docker compose up -d --build postgres qdrant redis api worker frontend

echo "== waiting for api health =="
until [ "$(docker inspect -f '{{.State.Health.Status}}' ariadne-api-1 2>/dev/null)" = "healthy" ]; do
  sleep 2
done

echo "== running Playwright E2E (real browser, real Gemini) =="
docker compose run --rm --no-deps playwright
rc=$?

if [ "$rc" -eq 0 ]; then
  echo "== E2E PASSED =="
else
  echo "== E2E FAILED (exit $rc) =="
fi

exit $rc
