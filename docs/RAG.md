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
