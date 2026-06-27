# Scope

## MVP (must ship)
- Ingest one repo (clone by URL or upload .zip) into Qdrant + Postgres.
- AST-aware chunking for Python + TS/JS/TSX; fallback splitter for everything else.
- Hybrid retrieval (dense + sparse) → RRF → optional rerank.
- LangGraph query graph with generator-critic; streamed answers with `path:line` citations.
- Next.js UI: ingest → live indexing → workspace (chat + clickable source panel).
- `docker compose up` brings everything up; seeder ingests a sample repo for instant demo.
- Alembic migrations; eval harness with a golden set + metrics; deterministic cassette tests.

## Built beyond MVP
- **Neo4j graph RAG (opt-in):** call/contains graph + `graph_augment` node + keyword dispatcher
  for structural questions. Enable with `GRAPH_ENABLED=true` + `docker compose --profile graph up`.

## Stretch (documented as "next", not built unless time allows)
- Parallel query decomposition (LangGraph `Send`) + a proper symbol resolver (replace name-based graph).
- Incremental re-indexing by git diff (hashes already stored per file).
- Multi-repo workspace switching beyond one-at-a-time.
- LangSmith-first tracing UI.

## Out of scope (explicitly)
- Auth / multi-tenant / RBAC.
- Full language coverage (long tail of tree-sitter grammars → fallback).
- Production deployment (described in README "productionize", not built).
- Human-in-the-loop approval (only relevant once the agent edits code).

## Cut lines (if time runs short)
- Rerank is env-gated; ship with it off before cutting retrieval quality elsewhere.
- Frontend stays clean over feature-rich: ingest + chat + citations is enough.
- Keep the harness proportional — it serves delivery, it isn't the product.
