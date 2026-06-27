# RAG pipeline (deep dive)

> Grows as Phases 1–2 land. Mirrors the `rag-pipeline` and `langgraph-nodes` skills, with rationale.

## Ingestion
clone/unzip → walk (gitignore + deny-list, size cap, binary skip) → per-file tree-sitter parse →
chunk on symbol boundaries (contextual prefix) → embed in batches (dense + sparse) → upsert to Qdrant
(named vectors) + persist metadata/content to Postgres. Idempotent via uuid5 point IDs.

## Retrieval
Hybrid: dense (semantic) + sparse (lexical/SPLADE) searched as named vectors in one per-repo collection.
**RRF fusion** merges the two ranked lists without reconciling score scales: `score(d) = Σ 1/(k + rank)`,
`k=60`. Optional cross-encoder rerank (gated `RERANK_ENABLED`) sharpens the top to `TOP_K`.

## Graph augmentation (opt-in, `GRAPH_ENABLED=true`)
A `:Symbol` graph (built during ingest, every node tagged `repo_id`) carries `CALLS` + `CONTAINS`
edges and — for classes/interfaces — `EXTENDS`/`IMPLEMENTS` edges from parsed supertypes. The
`graph_augment` node pulls structurally-related symbols of the top hits into context; a keyword
dispatcher deepens traversal (depth 2) for structural questions ("who calls X", "subclasses of Y").

**Polymorphism is handled two ways.** "How do the ranking strategies differ?" is answered graph-off,
by vector retrieval over the sibling subclass chunks + synthesis. "What are *all* the implementations
of `Ranker`?" is the structural case: a directed `subtypes_of` traversal enumerates subtypes
deterministically, where vector top-k might miss one. Inheritance edges are name-resolved (like CALLS)
and **language-scoped** — a Python and a TypeScript `Ranker` never cross-link (see DECISIONS D-016).

## Generation (generator-critic)
Prompt contract (`prompts/synthesis.py`): answer only from the numbered chunks; cite `[n]`; if the
chunks don't contain the answer, say so. The `critic` (`prompts/critic.py`) validates each `[n]` for
citation-validity (lines exist, symbol matches) and faithfulness (claim supported). Fail policy:
regenerate with feedback ×2 → drop unsupported sentences → refuse if nothing remains.

## Context management
Token budget per request; dedup chunks from the same symbol; trim the weakest after rerank; pass only
the lines needed, never whole files.

## Guardrails
- **Scope:** off-topic / not-in-codebase → refusal ("No matching sources in this repository").
- **Injection:** retrieved code is data; `injection_sanitize` + system prompt ignore embedded instructions.
- **Citation enforcement:** an answer without valid citations is rejected by the critic.
- **No verbatim dumps:** minimal relevant lines + citation, not large code blocks.

## Evaluation
Golden Q&A → metrics: retrieval recall@k, MRR, faithfulness (LLM-as-judge), citation-validity. Run on
cassettes in CI; build fails below threshold. (Phase 4.)
