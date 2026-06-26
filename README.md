# Ariadne

A code documentation assistant: ingest a repository, ask questions in natural language, and get
answers where **every claim is cited to exact `path:line` ranges**. The in-product agent is *Daedalus*.

> This README is a placeholder. The full write-up (setup, architecture, RAG approach, key decisions,
> what I'd do differently, how AI tooling was used) is written by hand in Phase 5.

## Quick start
```bash
cp .env.example .env        # add your GEMINI_API_KEY
docker compose up --build   # api :8000 · frontend :3000 · postgres · qdrant · redis · worker
```
The `seed` service ingests the bundled `sample_repo/` so the demo works immediately.

## Layout
- `backend/`  — FastAPI + LangChain/LangGraph service (hexagonal-lite; see `docs/DESIGN.md`).
- `frontend/` — Next.js UI reproducing the Ariadne design.
- `docs/`     — `DESIGN.md`, `DECISIONS.md`, `RAG.md`, `HARNESS.md`, `SCOPE.md`.
- `.claude/`  — dev-time AI harness (CLAUDE.md context, hooks, skills, commands).

## Checks
```bash
bash scripts/run-checks.sh   # ruff + mypy + pytest (cassette replay) + frontend lint
```
