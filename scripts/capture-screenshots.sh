#!/usr/bin/env bash
# Capture README screenshots from the running stack.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p docs/assets tests/e2e/test-results

has_gemini_key() {
  if [ -n "${GEMINI_API_KEY:-}" ]; then
    return 0
  fi
  [ -f .env ] && grep -qE '^GEMINI_API_KEY=[^[:space:]]' .env
}

echo "== bringing up stack for screenshots =="
if has_gemini_key; then
  echo "   (live mode — using .env credentials; indexed repo must already exist)"
  docker compose up -d --build postgres qdrant redis migrate api worker seed frontend
else
  echo "   (offline mode — local embedder + cassette replay; wipes vector data for consistency)"
  docker compose down -v >/dev/null 2>&1 || true
  EMBEDDING_PROVIDER=local CASSETTE_MODE=replay docker compose up -d --build postgres qdrant redis migrate api worker seed frontend
fi

echo "== waiting for api health =="
until [ "$(docker inspect -f '{{.State.Health.Status}}' ariadne-api-1 2>/dev/null)" = "healthy" ]; do
  sleep 2
done

echo "== waiting for seed to finish =="
docker compose wait seed 2>/dev/null || true
docker compose logs seed 2>/dev/null | tail -5 || true

echo "== waiting for frontend to compile =="
sleep 10

echo "== capturing screenshots with Playwright =="
docker compose run --rm --no-deps \
  -e BASE_URL=http://frontend:3000 \
  -v "$(pwd)/docs/assets:/docs/assets" \
  -v "$(pwd)/tests/e2e/test-results:/e2e/test-results" \
  playwright \
  sh -c "npm install --no-audit --no-fund && npx playwright test screenshots.spec.ts"

video="$(find tests/e2e/test-results -name 'video.webm' 2>/dev/null | head -1)"
if [ -n "$video" ]; then
  cp "$video" docs/assets/demo.webm
  echo "== demo video: docs/assets/demo.webm =="
fi

echo "== screenshots written to docs/assets/ =="
ls -la docs/assets/
