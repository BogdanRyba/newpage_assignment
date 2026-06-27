# Decision log (ADR-lite)

One short entry per decision: what, why, what we traded away. Newest first.
This feeds README section (e) — but the README is written in my own words, not pasted from here.

---

### D-017 · Local embedder weights the contextual header (path · symbol)
`LocalHashEmbedder` / `LocalHashSparse` (the offline CI embedder, D-011) now weights tokens from a
chunk's leading `# path · symbol` header (added by `with_context`) above body tokens. **Why:** a plain
bag-of-tokens let common body tokens (`note`, `search`, `self`) drown out the one distinctive symbol a
query is about, so symbol/file queries ranked their defining chunk mid-list — and D-016's deliberate
cross-language name collisions made it worse. The header is the highest-signal metadata we already
attach (the symbol a chunk defines + its file); weighting it restores rank-1 for those queries (e.g.
"how does NoteStore search?" rank 4 → 1), lifting eval MRR 0.49 → 0.60, back above the **unchanged**
0.5 gate. **Trade-off:** couples the local embedder to the chunk-header convention (documented; if the
format changes the boost simply doesn't apply — no breakage); a few subword-colliding names
(`searchNotes` vs a `search` method) still rank below 1, the lexical ceiling that real Gemini clears
semantically (so this hint is local-only).

### D-016 · Inheritance in the graph (EXTENDS/IMPLEMENTS) + language-scoped edges
The parser now extracts a class/interface's supertypes (Python bases, TS `extends`/`implements`,
interface-extends-interface), carried `SymbolSpan → Chunk → GraphNode`. `build_graph` emits `EXTENDS`
and `IMPLEMENTS` edges, name-resolved exactly like CALLS (an external base such as `ABC` resolves to no
repo symbol → no edge). A **directed** `subtypes_of` traversal enumerates subclasses/implementations
(sibling-free, transitive), while `neighbors` stays undirected for augmentation. **Why:** "what
implements/subclasses X?" is the canonical structural query graph-RAG should answer where pure vector
top-k can miss a sibling. **Cross-language collision:** the fixture deliberately has a Python *and* a TS
`Ranker`/`OverlapRanker`; edges now carry `src_lang` and the upsert MATCH requires both endpoints share
it, so the two hierarchies never cross-link — this also fixed the same latent bug in CALLS/CONTAINS
(edges had matched on symbol name only). **Trade-off:** same name-based heuristic limits as CALLS
(aliased/qualified cross-module bases unresolved); two same-named classes in the *same* language across
files still conflate; `.ts`/`.tsx` count as distinct languages (the fixture stays within one). The
graph-off MVP path is unchanged — inheritance traversal is exercised only with `GRAPH_ENABLED=true`.
The deliberate duplicate names also add lexically-similar chunks that initially lowered the **local**
embedder's first-hit rank — addressed by header weighting (D-017), **not** by relaxing the gate;
`recall@k` stays the hard completeness gate (0.8, actual 1.0).

### D-011 · Deterministic local embedder (`EMBEDDING_PROVIDER=local`)
A hashed bag-of-tokens dense + sparse embedder with no network/key/model-download.
**Why:** lets the full ingest + retrieval pipeline run in CI and demo with zero
credentials, and gives integration tests a deterministic retrieval substrate (combined
with cassettes for the LLM). **Trade-off:** lexical-overlap quality only — never a default
for real use; Gemini stays the default provider.

### D-015 · AST chunking also captures module-level content
`_chunk_symbols` now emits `module` chunks for lines not inside any function/class span — module
docstrings, top-level constants (prompt `SYSTEM` strings, `config` values), imports. **Why:** the
AST-only chunker silently dropped module-level code, so "how is X defended/configured?" questions had
nothing to retrieve and refused (caught during real-code testing). **Trade-off:** a few more chunks per
file; filtered to meaningful runs (≥2 non-blank lines or ≥40 chars) to skip trivial gaps. Also split
identifiers into subwords (camelCase/snake_case) in the **local** embedder so the offline eval reflects
lexical intent (`createNote` ↔ "create note"); real Gemini embeddings already handle this semantically.

### D-014 · Graph RAG (Neo4j) — opt-in, name-based call/contains graph
Implemented the graph seam: a `:Symbol` graph (CALLS + CONTAINS edges, every node tagged
`repo_id`) built during ingest, and a `graph_augment` node that pulls callers/callees/containers
of the top hits into context. A keyword dispatcher deepens traversal for structural questions
("who calls X"). Opt-in via `GRAPH_ENABLED=true` + `docker compose --profile graph up`; the MVP
path is untouched when off. **Why:** structural relationships answer questions pure vector search
can't ("blast radius", "what calls this"). **Trade-off:** resolution is **name-based** (no type/scope
analysis) — two same-named symbols in different files conflate, and dynamic dispatch is missed. Honest
heuristic; a real resolver (or LSP/SCIP index) is the productionization path. Isolation is by `repo_id`
on every node + traversal, never by graph instance.

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
