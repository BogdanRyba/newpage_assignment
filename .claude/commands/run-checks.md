---
description: Run the full check gate (ruff, mypy, pytest-replay, frontend lint) before declaring work done.
---

Run `bash scripts/run-checks.sh` and report the result.

This is the single "are we done?" gate (DoD step: run before declaring done):

- `ruff check .` + `ruff format --check .` (backend lint/format)
- `mypy app` (backend types)
- `pytest -m "not integration"` with `CASSETTE_MODE=replay` (deterministic backend tests)
- `npm run lint` (frontend)

If anything fails, fix it before continuing. Do not report a task complete with a red gate.
For the live integration suite (real Gemini + Qdrant) run separately:
`docker compose run --rm api pytest -m integration`.
