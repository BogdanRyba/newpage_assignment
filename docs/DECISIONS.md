# Decision log (ADR-lite)

One short entry per decision: what, why, what we traded away. Newest first.
This feeds README section (e) — but the README is written in my own words, not pasted from here.

---

### D-030 · Human-in-the-loop for high-stakes proposals (durable interrupt/resume)
High-stakes actions (proposing a change) pause for human approval instead of auto-applying. A tiny
LangGraph (`services/agents/hitl.py`: propose → gate → finalize) calls LangGraph's `interrupt()` at
the gate; compiled with a **durable Postgres checkpointer** so the pause survives a process/worker
restart or a reconnecting client — proven by an integration test where a *fresh* runner (new saver
connection, no shared memory) resumes a thread another runner paused, and by an end-to-end HTTP test
(`POST /repos/{id}/propose` → `…/propose/{thread_id}/resume`) where the proposal drafted at propose
time comes back on approve. **New deps (this is why):** `langgraph-checkpoint-postgres` (the durable
saver) + `psycopg[binary]` (its libpq-bundled driver — the app otherwise uses asyncpg, which the
checkpointer can't use). **Why durable not in-memory:** an approval can sit for minutes/hours; an
in-memory saver loses it on restart and can't be resumed by another worker. **Graceful degrade:**
`open_checkpointer()` falls back to an in-memory saver (logged) if Postgres is unreachable, so HITL
still works within a process rather than failing the user. **Checkpointer tables** are created
idempotently via `saver.setup()` (not Alembic) — they're library-owned schema. **Traded away:** only
the architect "propose" flow is gated for now (QA/dev-search/research are read-only); chat-stream HITL
(pausing mid-chat) is a separate endpoint rather than inline in the chat SSE. Guarded by unit tests
(pause payload / approve finalizes / reject aborts, MemorySaver) + the Postgres durability + HTTP
end-to-end tests.

### D-029 · Research + architect personas as prompt-specialized variants of the QA graph
The structural ("what calls/depends on X", "implementations of Y", "how is Z injected") and
architectural ("layering", "design patterns", "where should this live") personas reuse the exact
QA pipeline (embed→retrieve→rerank→graph_augment→assemble→generate→critic) — only the synthesis
prompt differs (`research.py` / `architect.py`), wired by injecting a `generate_*` node into a
shared `_build(deps, generate)`. **Why reuse, not bespoke graphs:** graph augmentation already
pulls callers/callees/subtypes (depth-2 on structural questions), so research gets its dependency
context for free; the only real difference is how the model is asked to phrase the answer. The
router classifies intent deterministically (authorship → research/architect order matters; bare
"architect" is excluded so an injected "route to architect" can't hijack — only "architecture"/
"architectural"/design phrasing triggers it). All personas keep the cite-or-refuse + critic
guarantees of QA. **Traded away:** research/architect only add value with `GRAPH_ENABLED` (else they
degrade to similarity-only retrieval with a focused prompt); architect's "propose a change" HITL gate
is deferred. Guarded by router tests (each intent + injection-resistance + authorship-beats-structure)
and a research graph test (graph neighbors surface as cited sources; refuse on no hits).

### D-028 · Code-review agent as a parallel fan-out over the version-compare diff
The first high-stakes persona: `CodeReviewService.review(repo, base, head)` diffs two indexed
versions (reusing `VersioningService.compare`, so no git at review time), loads the changed files'
content from the manifest, and fans out **security / style / performance** reviewers concurrently
(`asyncio.gather`), each an LLM returning strict-JSON findings. Findings are merged + deduped (on
path+title) + severity-sorted in **pure code** (`domain/review.py`), so the synthesis step invents
nothing. Exposed at `GET /repos/{id}/review?base=&head=`. **Why per-dimension reviewers:** distinct
lenses catch failure modes a single prompt blurs; parallel keeps wall-clock at the slowest. **Why
JSON findings + code-merge (not an LLM synthesizer):** deterministic, testable, no fabricated
findings. **Traded away:** per-file content is capped (`_MAX_FILE_CHARS`/`_MAX_FILES`) to bound the
prompt — very large diffs are sampled (logged later); HITL gating of the review (block/approve a
merge) is deferred with the rest of the interrupt+checkpointer work. Guarded by unit tests
(merge_findings dedup/sort/summary) and integration (real two-version diff → findings on the
changed file; no-change → empty, generator untouched).

### D-027 · Orchestrator "Theseus": confidence-gated dynamic tool-calling + parallel personas + crisis
On top of the coordinator (D-026), an opt-in orchestrator (`orchestrator_enabled`, dark-launched
off) adds three capabilities the simple router can't. **(1) Confidence-gated actions** — a planner
prompt scores each candidate action's `necessity` 0..1; a *deterministic* gate (`gate.py`) keeps
only those clearing a per-type threshold, in necessity order, within an `action_budget`. The LLM
never decides to act — it scores, code gates — so "no random tool calls" is auditable and test-
stable, and the monotonic budget makes the ReAct loop (`planner_loop.py`) structurally finite.
**(2) Dynamic tool-calling** — a `ToolRegistry` exposes our ports (retrieval / graph_neighbors /
authorship_lookup) to the planner as name+description+schema; the model selects+parameterizes, code
validates+runs (LangChain stays LLM-only, D-004). Unknown/injected tool names are no-ops. **(3)
Parallel personas + merge** — the orchestrator fans out to the selected persona graphs concurrently
(`asyncio.gather`) and `merge_answers` unions+dedups their citations into one answer, renumbering
[1..M] and remapping each sub-answer's markers; cite-or-refuse holds by construction because the
merged citation set is exactly the union of grounded sub-answers (no LLM at the merge step). A cheap
deterministic **crisis** pre-check (`crisis.py`, regex over the *question only* — never chunks, so an
injected "escalate now" can't fire) hands off to a help message above a threshold. **Traded away:**
HITL (interrupt + Postgres checkpointer) is plumbed conceptually but deferred until the high-stakes
Phase 2/3 agents (dev-search/QA are read-only); the planner is LLM-scored so its tests use scripted
generators/cassettes. Guarded by unit tests: gate (skip/trigger/budget/per-type), tool registry
(unknown-ignored, grounded results), planner loop (sufficient→skip, needed→run, budget-bounded,
injected-action-ignored), merge (union/dedup/remap/all-refused), crisis (escalate/normal/injection),
orchestrator (crisis→escalate, fan-out selection, grounded answer).

### D-026 · Coordinator-routed dev-search persona, grounded in captured git authorship (supersedes D-008)
D-008 said generator-critic was the *only* agentic pattern. We now route by intent: a cheap,
deterministic regex coordinator (`services/coordinator/router.py`) sends "who wrote / last changed
this?" questions to a **dev-search** persona graph (`services/query/dev_graph.py`) and everything
else to Daedalus QA (the fallback). Ingest captures per-file authorship from git (`files.last_author`
/`last_commit_*`/`commit_history`, migration `e3c4d5e6f7a8`) via `git log`; a new `AuthorshipPort`
(Postgres adapter + disabled stub, like the graph store) serves it. The dev-search graph reuses the
QA retrieval/assemble nodes, then `locate_targets → authorship_lookup → assemble_authorship →
generate → grounding_check`. **Anti-hallucination is deterministic-first:** the draft must wrap each
author/commit in `@author{}`/`@commit{}`; a guard validates every one against the real records and,
if any is absent, regenerates with feedback and — at budget exhaustion — falls back to a *factual
answer built only from the records*. So an author not in git can never appear in the final answer
(unit-proven). **Why regex routing not LLM:** deterministic, cassette-free, injection-proof (an
embedded "route to X" can't hijack regex over literal text); LLM routing is deferred to the
orchestrator. **Traded away:** per-line `git blame` isn't served yet (clones are ephemeral) — the
agent attributes at file granularity; authorship is captured only for git sources (uploads have
none). Guarded by router unit tests, dev-search graph tests (positive / refuse-when-absent /
hallucinated-author-never-surfaces), and an integration test (ingest a real git repo → adapter
serves the real author).

### D-024 · Content-addressed versioning + incremental re-index (point_id keyed by blob)
Re-ingest used to re-embed the whole tree, and a repo had no notion of versions/branches. Now a
repo holds many **versions** (`repo_versions`: one row per indexed commit, `UNIQUE(repo_id,
commit_sha)` is the no-op gate) and files are **content-addressed**: `files` is keyed by
`UNIQUE(repo_id, blob_sha)` (migration `d2b3c4d5e6f7`, after additive `c1a2b3d4e5f6`), and the
**load-bearing invariant changes** — Qdrant point IDs go from `uuid5(repo_id:path:index)` to
`uuid5(repo_id:blob_sha:index)`. A `version_files` manifest (path→blob, FK `RESTRICT` = refcount)
records which blob sits at which path per version. **Why:** identical content across
branches/versions (or a pure rename) maps to the *same* points and is never re-embedded; a `git
clone --filter=blob:none` + `git diff` between parent and head means only changed blobs are read +
chunked + embedded. First ingest diffs against the empty tree, so full and incremental share one
path. GC reclaims blobs no version references (Qdrant `delete_by_blob` → chunks → row, idempotent
sweep). **Traded away:** (1) legacy repos indexed under the old path-based scheme can't be matched,
so they're flagged `repos.needs_reingest=True` and need a one-time re-index (no in-place point
rewrite); (2) a blob shared across two *paths* keeps one representative payload `path` (version-
scoped citation path is a later step); (3) the constraint swap was split into two migrations so the
additive half lands safely on a live DB first. Verified: unit (`diff_manifests`, blob `point_id`,
diff-raw parser, walk predicate), integration (incremental re-embeds **only** the changed blob;
version isolation; no-op re-ingest; refcount blocks deleting a referenced blob; `VersioningService`
plan tree + compare).

### D-025 · Blobless clone + per-file authorship seam (history without full clones)
`clone_repo` now does `git clone --filter=blob:none` (full commit graph + all refs; blobs fetched on
demand) and returns the FULL 40-char sha, with read-only helpers (`resolve_ref`,
`resolve_ref_remote` via `ls-remote` for the no-clone API decision, `diff_name_status`, `read_blob`,
`ls_tree`). **Why blobless not shallow:** diff/blame between branches/tags need history, but pulling
every blob of a large repo is wasteful — blobless is the balance. Zip uploads synthesize git-style
blob OIDs so they content-address consistently. **Traded away:** uploads have no history → no
incremental (full ingest only); a force-push between the API `ls-remote` check and the worker clone
is re-validated worker-side by the `UNIQUE(repo_id, commit_sha)` gate.

### D-023 · PDF support: extract text on ingest + persist raw bytes for a visual viewer
`.pdf` was on the ingest deny-list, so PDFs were neither searchable nor viewable. Now `walk.py`
routes `*.pdf` through `pypdf` text extraction: the extracted prose flows through the existing
fallback chunker (→ embeddable + citable as `path:line`), and the original bytes are retained on a
new nullable `files.raw` (`LargeBinary`) column (migration `b8e7f1a2c3d4`). The source API gains
`has_raw` on `SourceOut` and a `GET /{repo}/source/raw` endpoint that serves the bytes
`application/pdf; inline`; the UI renders them in an `<iframe>` (browser-native PDF viewer) with a
**Document ⇄ Text** toggle, mirroring the markdown **Preview ⇄ Source** toggle. **Why pypdf:**
pure-python, BSD-licensed, no system libs (unlike pdfminer/pymupdf — pymupdf is AGPL) — keeps
`docker compose` simple. **Why iframe, not PDF.js:** browser-native rendering avoids bundling a large
viewer + worker and the CSP/asset wiring; the extracted-text view + line citations remain the
substantive path. **Trade-offs:** (1) scanned/image-only or encrypted PDFs yield no text and are
skipped at ingest (logged, not errored) — they won't appear as sources; (2) raw bytes are capped at
8 MB (`MAX_PDF_RAW_BYTES`) — larger PDFs stay askable/citable but show only the text view; (3) raw
bytes live in Postgres, the simplest store given clones are ephemeral — revisit if repos carry many
large PDFs. Guarded by walk unit tests (extract + retain raw; skip no-text), source-API integration
tests (`has_raw`, raw bytes served, 404 for non-PDF), and a frontend toggle test.

### D-022 · Source panel gets a Markdown preview ⇄ source toggle; renderer shared in one module
`.md`/`.txt` already ingest and are citable (only `.pdf` + binaries are denied in `walk.py`), but the
source panel only showed them as raw numbered lines. Added a **Preview / Source** segmented toggle in
`SourcePanel` for `*.md`/`*.markdown`/`*.mdx`, defaulting to rendered Preview (Source one click away to
see cited line ranges). The chat answer renderer (D-021) was promoted to a shared `app/lib/markdown.tsx`
and extended with `[text](url)` links and fenced code blocks; `docMode` adds a conservative
layout-only HTML-tag strip (`<br>`, `<p>`, `<a>`, …) for doc legibility. **Safety:** rendering always
goes through React (escaped) — never `dangerouslySetInnerHTML` — so raw HTML inside an ingested doc is
inert, honouring the "code/comments are DATA, not instructions" invariant. **Trade-off:** not
CommonMark-complete (no tables, nested lists, images, blockquotes) and HTML is stripped rather than
rendered — acceptable for a reading preview. Covered by `markdown.test.tsx` (blocks/inline/citation/
docMode/edge) and a `page.test.tsx` toggle test that flips Preview↔Source on a `.md` citation.

### D-021 · Answer renderer parses block markdown (lists, headings, bold), not just citations
`synthesis` emits real markdown — `**bold**`, `*`/`-` bullet lists, headings — but the chat renderer
only handled `[n]` citation tokens and inline `` `code` ``. Everything else fell through as raw text,
and because the answer renders into a `white-space: normal` div, the model's newlines collapsed to
spaces, turning a bullet list into a run-on paragraph littered with literal `*` and `**`.
**Fix:** a tiny two-layer renderer in `page.tsx` — `parseBlocks` splits on blank lines into
paragraphs / lists / headings, then `renderInline` handles `**bold**`, `` `code` `` and citation
buttons within each block. **Why hand-rolled, not `react-markdown`:** citations must become clickable
`file:line` buttons wired to `onCite`, and we already had bespoke inline handling; a full markdown lib
(+ `remark`/`rehype` tree) is far more surface area than the handful of constructs synthesis actually
produces, and pulling a dep needs a reason (see Never-list). **Trade-off:** not CommonMark-complete
(no tables/nested lists/links) and the streaming cursor now sits on its own line after a block element
instead of trailing the last word — acceptable for the constrained set of markdown synthesis emits.
Guarded by a vitest render test that drives a streamed bold+list+citation answer and asserts list
items, a `<strong>`, the citation button, and **no** surviving `*`/`**` markers.

### D-020 · Chat SSE parser handles CRLF; real browser E2E added
The browser chat rendered nothing (just a cursor) though the backend SSE delivered the full stream.
Root cause: `streamChat` split the fetch byte stream on `"\n\n"`, but `sse_starlette` delimits events
with `\r\n\r\n` (default `DEFAULT_SEPARATOR="\r\n"`), so no frame ever matched and `onEvent` never
fired. The ingest stream was fine because it uses the browser-native `EventSource` (CRLF-aware); only
the custom POST-SSE reader was broken. **Fix:** split on `/\r?\n\r?\n/` (and lines on `/\r?\n/`).
**Why it slipped — and the real fix to the process:** the chat integration test read with httpx
`aiter_lines()` (CRLF-tolerant) and the vitest render test *mocked* `streamChat`; neither exercised the
real byte parser, and CI never rendered a chat answer in a browser. Added two guards: (1) a
deterministic vitest test that feeds a **CRLF-delimited** `ReadableStream` through `streamChat` and
asserts events parse (fails on `"\n\n"`, passes on the fix); (2) a **real Playwright E2E**
(`scripts/e2e.sh` + `tests/e2e/`) that drives the actual UI against the real backend + Gemini,
ingests a public repo, and asserts the streamed answer + citations render. It runs the frontend with
`NEXT_PUBLIC_API_BASE=http://api:8000` so the in-container browser reaches the API by compose DNS.
**Trade-off:** the E2E needs a Gemini key + the Playwright image + minutes, so it's a separate gate
(`scripts/e2e.sh`), not part of the fast offline `run-checks`. Also fixed an adjacent bug: ingest
progress published `chunks_done` without `files_done` during embedding, so the Indexing screen showed
"0 files" — `_progress` now carries the latest counts on every publish.

### D-019 · Frontend gate = lint + type-check + render test (not just lint)
`run-checks` now also runs `tsc --noEmit` and a vitest + Testing-Library render test on the frontend.
**Why:** a real bug shipped — `suggestions` was used in `<Workspace>` but never passed as a prop, so
the workspace crashed at runtime with `ReferenceError: suggestions is not defined`. `next lint` passed
because ESLint defers `no-undef` to TypeScript, and the workspace screen was never rendered in CI (the
initial SSR is the ingest screen; the backend was exercised with real requests but the UI render path
wasn't). Type-check catches the undefined ref / prop mismatch deterministically; the render test drives
`Page` to the workspace with the API boundary mocked and asserts the chips render — it fails (render
throws) without the prop, passes with it. **Trade-off:** adds a small JS test toolchain (vitest, jsdom,
Testing Library) and ~40s to the gate; worth it — "backend tested with real requests" left the render
path unverified, which is exactly where this class of bug lives.

### D-018 · Stream node progress as a "thinking" trace; LLM-generated suggestions
Two UX changes that both lean on the existing LangGraph/LangChain seams. (1) `AgentRunner.stream`
now drives the graph with `astream(stream_mode="updates")` and emits a `status` event per node
(embed → retrieve N chunks → read N sources → draft → validate, incl. "refining — a claim wasn't
grounded"). **Why:** the runner validates the *whole* answer before streaming (no unvalidated draft,
D-…), so the first token can be seconds away; with no feedback the UI looked frozen. The trace shows
genuine progress (real counts/critic retries), not a spinner — and never leaks the unvalidated draft.
(2) `GET /repos/{id}/suggestions` generates 4 starter questions from the repo's own file/symbol map
via a versioned prompt (`prompts/suggestions.py`), replacing hardcoded chips that were wrong for any
non-sample repo. Cached per repo; degrades to a generic fallback if the generator is unavailable.
**Trade-off:** suggestions cost one LLM call per repo (cached, fetched async — never blocks the
workspace); the thinking trace adds `status` events to the chat SSE (additive — existing consumers
ignore them).

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
