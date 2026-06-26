---
name: langgraph-nodes
description: How to write LangGraph nodes for the query graph — typed state, pure node functions, the generator-critic loop, and budgets/limits. Use when adding or changing a query-graph node.
---

# LangGraph nodes

The query graph is the in-product agent **Daedalus**. Keep it boring and testable.

## State + node contract
- State is a typed pydantic model (`services/query/state.py`): `query, repo_ctx, hits, context,
  draft, citations, critic_iters, budget, refused, ...`.
- A node is (almost) a pure function `State -> partial State`. No hidden globals. This makes every
  node unit-testable in isolation, mocking only the ports it calls.
- Side effects (LLM/embedder/vector calls) go through **ports**, never directly — so they can be
  decorated (retry/cache/trace) and replayed from cassettes.

## Generator-critic loop (the one agentic pattern in MVP)
1. `generate` drafts an answer from assembled context, citing `[n]`.
2. `critic` validates every `[n]`: (a) **citation-validity** — the cited lines exist and contain the
   referenced symbol; (b) **faithfulness** — the claim is supported by that chunk.
3. Conditional edge on the verdict:
   - all good → END.
   - issues + `critic_iters < MAX_CRITIC_ITERATIONS` (2) → `regenerate` with the critic's feedback.
   - retries exhausted → `drop_unsupported`: keep only cite-supported sentences.
   - nothing left supported → `scope_refuse` ("insufficient support in this repository").

## Budgets (prevent runaway loops)
`recursion_limit` on the graph, `MAX_CRITIC_ITERATIONS` in state, `TOKEN_BUDGET` per request,
`REQUEST_TIMEOUT_S`. A critic loop without limits can spin forever — always cap it.

## Tests
positive: a faithful draft passes critic untouched. negative: a hallucinated path/line is rejected.
edge: 2 failed regenerations → drop path; everything unsupported → refusal. Run on cassettes.
