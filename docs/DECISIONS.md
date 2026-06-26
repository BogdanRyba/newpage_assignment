# Decision log (ADR-lite)

One short entry per decision: what, why, what we traded away. Newest first.
This feeds README section (e) — but the README is written in my own words, not pasted from here.

---

### D-011 · Deterministic local embedder (`EMBEDDING_PROVIDER=local`)
A hashed bag-of-tokens dense + sparse embedder with no network/key/model-download.
**Why:** lets the full ingest + retrieval pipeline run in CI and demo with zero
credentials, and gives integration tests a deterministic retrieval substrate (combined
with cassettes for the LLM). **Trade-off:** lexical-overlap quality only — never a default
for real use; Gemini stays the default provider.

### D-013 · Eval determinism: local embedder + recorded LLM cassettes
The eval-runner computes retrieval metrics (recall@k, MRR) with the deterministic local
embedder (offline, no key) so the CI gate always bites; answer metrics (citation-validity,
faithfulness via LLM-as-judge) replay recorded Gemini cassettes. **Why:** a quality gate that
needs a paid key or flakes on LLM nondeterminism isn't a gate. **Trade-off:** cassettes must be
re-recorded when a prompt/version changes (the VERSION tags make that traceable).

### D-012 · Scope refusal via a `NO_ANSWER` sentinel
Empty retrieval rarely happens (a vector store always returns top-k), so off-topic questions
weren't refused. The synthesis prompt now instructs the model to emit exactly `NO_ANSWER` when
the sources don't cover the question; the critic converts that to a clean refusal. **Why:** a
robust, provider-agnostic scope gate beats a brittle similarity threshold that needs per-model
calibration. **Trade-off:** relies on instruction-following — covered by a recorded prompt test.

### D-010 · `python-multipart` dependency
Added for the `.zip` upload endpoint (FastAPI form/file parsing). **Why:** the design
offers "drop a .zip" alongside clone-by-URL. **Trade-off:** one small dependency; trivial.

### D-009 · Prompts are first-class versioned artifacts
Each LLM call uses a dedicated prompt module under `app/prompts/` with explicit role/context/
constraints/output_format sections and a `VERSION`. **Why:** prompts are where most RAG behaviour and
most regressions live; scattering f-strings makes them untestable and untraceable. **Trade-off:** more
ceremony per prompt than an inline string — worth it for prompt unit tests and version-tagged eval runs.

### D-008 · Generator-critic is the only agentic pattern in MVP
Query is a LangGraph graph with one cycle: generate → critic (citation-validity + faithfulness) →
regenerate ×2 → drop unsupported → refuse. Dispatcher + parallel decomposition are deferred to the
Neo4j graph phase; iterative-refinement / HITL / deep hierarchy are deliberately omitted. **Why:** a
documentation assistant mostly retrieves and answers; multi-agent ceremony on retrieve→generate is the
over-engineering the brief warns against. Generator-critic directly serves "trust comes from sources".
**Trade-off:** fewer agents to show off; better judgment to defend.

### D-007 · Record/replay cassettes at the LangChain model boundary
Custom cassette layer records real Gemini/embedder responses to JSON keyed by input-hash; replay runs
offline. **Why:** LLM output is nondeterministic — without this, "agent tests" flap and cost money.
CI runs `CASSETTE_MODE=replay`. **Trade-off:** must re-record when a prompt/version changes (vs vcrpy's
HTTP brittleness or hand-written fakes that aren't real responses).

### D-006 · Observability = OTel + structlog locally, LangSmith optional
Spans + structured logs run in-process, no external key; LangSmith is opt-in via env. **Why:** keeps
`docker compose up` self-contained and CI offline/deterministic. **Trade-off:** less polished trace UI
out of the box than LangSmith-first.

### D-005 · Async ingest via Taskiq + Redis worker
Ingestion runs in a separate worker container; progress streams to the UI via Redis pub/sub → SSE.
**Why:** indexing is slow and CPU-bound; keeping it off the API event loop is correct, and a real queue
demonstrates at-least-once + idempotency. **Trade-off:** more moving parts in compose than an in-process
background task — accepted for the production-shaped story.

### D-004 · LangChain scoped to LLM only; retrieval stays raw behind ports
LangChain handles chat + embeddings; Qdrant (hybrid named-vectors + RRF + rerank) and Neo4j stay raw
behind our `vector_store` / `graph_store` ports, called from LangGraph nodes. **Why:** maximal control
over hybrid retrieval (named vectors, custom RRF, collection-per-repo) where it matters, LangChain where
it adds value. **Trade-off:** a bit more retrieval code than `EnsembleRetriever`, far more control.

### D-003 · Gemini for both embeddings and synthesis (provider behind a port)
Default dense embeddings `gemini-embedding-001`, synthesis `gemini-3.5-flash`, all via LangChain. Sparse
is local (fastembed). **Why:** one vendor, one key, simplest demo; code-specialised Voyage stays a
documented swap behind the `embedder` port. **Trade-off:** Gemini embeddings are slightly weaker on pure
code than Voyage — acceptable, and switchable by env.

### D-002 · Hexagonal-lite, not full DDD
Ports (`typing.Protocol`) only on volatile IO boundaries (embedder, sparse, generator, vector_store,
graph_store, parser); domain kept framework-free. **Why:** the domain is a technical retrieval pipeline,
not a rich rules engine — full DDD aggregates/bounded-contexts would be cargo cult. Consciously skipped:
CQRS/ES, generic Repository, Specification, internal event bus, Saga. **Trade-off:** none meaningful at
this size; documented so the omission reads as judgment, not ignorance.

### D-001 · Neo4j designed-in now, implemented later
`graph_store` port + adapter stub + a passthrough `graph_augment` node exist from day one; the real graph
(call/import edges, structural queries) is stretch. **Why:** the user wants to add graph RAG later; baking
the seam in now avoids a refactor, while keeping MVP scope honest. **Trade-off:** a little dead structure
in the MVP — cheap insurance.
