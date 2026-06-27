# Ariadne

A **code documentation assistant**: point it at a repository, ask questions in natural language,
and get answers where **every claim is cited to exact `path:line` ranges** you can click through to
the source. The product is *Ariadne* (the thread of trust between you and the code); the in-product
agent is *Daedalus* (the LangGraph graph that "built the labyrinth and knows every corner").

> **A note on this README.** The factual sections below (setup, architecture, decisions, how the AI
> tooling was used) describe what was actually built and verified. Section (i) — *Reflections* — is
> intentionally left for me to write in my own voice, as the assignment asks. Deep-dives live in
> [`docs/`](docs/); the decision log is [`docs/DECISIONS.md`](docs/DECISIONS.md).

---

## (a) Setup

**Prerequisites:** Docker + Docker Compose. A Gemini API key for live answers (optional — see offline mode).

```bash
cp .env.example .env          # add GEMINI_API_KEY for live chat
docker compose up --build     # api :8000 · frontend :3000 · postgres · qdrant · redis · worker
```

`migrate` applies the schema, `seed` ingests the bundled [`backend/sample_repo`](backend/sample_repo)
so the demo works immediately. Open **http://localhost:3000**, click **Sample → ariadne-sample**, and ask
"How does the calculator add to its running total?"

**Offline / no-key mode** (deterministic, zero credentials) — uses a local hashed embedder and
replays recorded LLM cassettes:

```bash
EMBEDDING_PROVIDER=local docker compose up --build      # ingest + retrieval work with no key
```

**Checks** (lint + types + deterministic tests + frontend):

```bash
bash scripts/run-checks.sh
# integration + eval gate (real Postgres+Qdrant, offline LLM via cassettes):
docker compose run --rm -e EMBEDDING_PROVIDER=local -e CASSETTE_MODE=replay api \
  sh -c "alembic upgrade head && pytest -m integration && python -m evals.run --check-thresholds"
```

## (b) Architecture

Hexagonal-lite + **Pipes & Filters** on two pipelines, with **LangGraph** for the query flow.
Full write-up + diagram: [`docs/DESIGN.md`](docs/DESIGN.md).

- **Ingest** (Taskiq worker): `clone/unzip → walk → tree-sitter chunk → embed(dense+sparse) → Qdrant + Postgres`.
- **Query** (LangGraph graph "Daedalus"): `embed → retrieve → fuse(RRF) → rerank → assemble → generate ⇄ critic`.

Ports (`typing.Protocol`) sit only on the **volatile IO boundaries** — embedder, sparse embedder,
generator, vector store, graph store, parser — so providers are swappable. The domain (`app/domain`)
is framework/LangChain/infra-free. LangChain is scoped to the **LLM only** (chat + embeddings); Qdrant
and Neo4j stay raw behind our ports so we control hybrid named-vectors, RRF, and collection-per-repo.
Multi-repo isolation flows through a `RepoContext` (repo_id → Qdrant collection + graph namespace), not
through class structure. `backend/app/` layout is documented in [`CLAUDE.md`](CLAUDE.md).

## (c) Productionizing

What this is **not** yet, and how I'd take it there:
- **State stores:** managed Postgres + Qdrant (and Neo4j when graph RAG lands); today they're local containers.
- **Multi-store consistency:** ingest writes Postgres + Qdrant; in prod a failure between them can drift.
  MVP relies on idempotent uuid5 retries; prod wants an **outbox + reconciliation** sweep.
- **Ingest at scale:** Taskiq already decouples the worker; add autoscaling, backpressure, and per-repo
  rate limits. Reranking moves to a GPU node (it's CPU-gated off by default here).
- **Secrets / multi-tenancy / auth:** none yet (out of scope). Add OIDC, per-tenant repo scoping (the
  `RepoContext` seam helps), and secret management.
- **Observability in the cloud:** OTel spans already exist — point the OTLP exporter at a collector;
  optionally enable LangSmith via env.

## (d) RAG / LLM approach

Details + rationale: [`docs/RAG.md`](docs/RAG.md). Highlights:
- **Chunking** is AST-aware (tree-sitter: Python/TS/JS), on function/class/method boundaries with a
  contextual prefix; unknown languages fall back to a recursive splitter so nothing is dropped.
- **Retrieval** is hybrid — dense (Gemini) + sparse (fastembed) as named vectors in one per-repo Qdrant
  collection — fused with **RRF** (no score-scale reconciliation), optional cross-encoder rerank.
- **Generation is a generator-critic loop.** The critic checks *citation-validity* deterministically
  (every `[n]` maps to a real source) and *faithfulness* via an LLM judge; it regenerates with feedback,
  then drops unsupported sentences, then refuses ("insufficient support"). Off-topic questions refuse via
  a `NO_ANSWER` sentinel. **All LLM access goes through LangChain.**
- **Prompts are first-class artifacts** (`app/prompts/`) — versioned, with explicit role/context/
  constraints/output_format and rationale; never inline f-strings.
- **Determinism:** a custom cassette layer records real LLM calls and replays them, so tests and the eval
  gate run offline and reproducibly.

## (e) Key decisions

The full ADR log is [`docs/DECISIONS.md`](docs/DECISIONS.md). The load-bearing ones: hexagonal-lite over
full DDD; LangChain scoped to the LLM while retrieval stays raw; Gemini for both embeddings + synthesis
(provider behind a port); Taskiq+Redis async ingest; generator-critic as the *only* agentic pattern in
MVP; cassettes + local embedder for a CI gate that actually bites; Neo4j designed-in (port + passthrough)
but not implemented.

## (f) Engineering standards — kept & consciously skipped

**Kept:** Definition-of-Done per feature (runs in compose, has a failing-without-it test, errors handled,
tradeoff logged). A real **testing standard** — behaviour/contract tests, positive + negative + adversarial
(prompt-injection, off-topic, empty retrieval), a test pyramid (unit mocks IO; integration hits real
Qdrant+Postgres and asserts retrieved chunks contain the expected symbols; evals score the full pipeline),
and *no green-washing* (a PreToolUse hook blocks tests whose every assertion is trivially true).

**Consciously skipped** (judgment, documented): full DDD aggregates/bounded-contexts, CQRS/Event-Sourcing,
a generic `Repository<T>`, the Specification pattern, an internal event bus, Sagas. On the agent side: of
the eight common multi-agent patterns, only **generator-critic** is in MVP; dispatcher + parallel
decomposition are deferred to the Neo4j graph phase; iterative-refinement / HITL / deep hierarchy are
omitted as over-engineering for a retrieve-and-answer system.

## (g) How AI tooling was used

Two harnesses (see [`docs/HARNESS.md`](docs/HARNESS.md)):
- **Dev-time** ([`.claude/`](.claude)): `CLAUDE.md` (always-loaded invariants), **hooks** that enforce what a
  model forgets (auto-format; block edits to secrets/lockfiles/applied migrations; **block green-washing
  tests**; TDD red-first; run fast tests on stop), **skills** (chunking, rag-pipeline, langgraph-nodes,
  prompt-authoring, qdrant-ops, harness-evals, testing), **commands** (`/new-endpoint`, `/new-node`,
  `/add-eval`, `/run-checks`), and a `reviewer` subagent.
- **Runtime** (in the product): typed graph state, the instrument decorator (OTel + structured `[daedalus]`
  logs), record/replay cassettes, the eval-runner, reusable guardrail steps, budgets/limits, and the
  `AgentRunner` facade — one code path shared by the API and the evals.

## (h) What I'd do differently / next

**Graph RAG is now implemented** (opt-in): a Neo4j call/contains graph + a `graph_augment` node that
enriches the top hits with structurally-related symbols, plus a keyword dispatcher that deepens
traversal for "who calls X"-style questions (`GRAPH_ENABLED=true` + `docker compose --profile graph up`).
Its resolution is name-based — the honest next step is a real symbol resolver (LSP/SCIP) to kill
same-name conflation, plus parallel query decomposition (LangGraph `Send`). Beyond that: incremental
re-indexing by git diff (file hashes already stored), the citation **hover-preview popover** (deferred —
click-to-open is implemented), evals against real Gemini embeddings, and a larger golden set with
regression tracking across prompt `VERSION`s.

## (i) Reflections

> _(Written by me, in my own words — see the note at the top.)_

---

🤖 Built with Claude Code. Backend `backend/` · Frontend `frontend/` · Design reference in
`Product Design Principles/`.
