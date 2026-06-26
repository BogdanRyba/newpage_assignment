---
name: harness-evals
description: The runtime/eval harness — instrumentation, cassettes, eval-runner metrics, guardrail nodes, budgets, and the AgentRunner facade. Use when working on observability, evals, determinism, or the agent entrypoint.
---

# Harness & evals

The harness is what makes Daedalus observable, deterministic, and bounded. Seven parts:

1. **Typed state + node contracts** — `services/query/state.py`; nodes are unit-testable functions.
2. **Instrumentation (Decorator)** — `core/instrument.py` wraps nodes/adapters with an OTel span +
   structlog line: `query, retrieved IDs+scores, latency, tokens, model, node`. Agent logs tag `[daedalus]`.
3. **Cassettes** — `core/cassette.py` at the LangChain model boundary; `CASSETTE_MODE=record|replay|off`.
   Replay = no network, deterministic CI. See `testing` skill.
4. **Eval-runner** — `evals/`: golden Q&A → full graph → metrics:
   - retrieval **recall@k**, **MRR** (did we fetch the expected files/symbols?)
   - **faithfulness** via LLM-as-judge (is each claim backed by a cited chunk?)
   - **citation-validity** (do cited lines exist and contain the symbol?)
   CI fails the build below threshold.
5. **Guardrail nodes** — reusable: `scope_check`, `injection_sanitize`, `citation_validate`.
6. **Budgets/limits** — `core/budgets.py` + state: recursion_limit, max_iterations, token budget, timeout.
7. **AgentRunner facade ("Daedalus")** — `services/agent_runner.py`: stitches checkpointer + tracer +
   limits + cassette and exposes `run()` / `stream()`. **API and evals call this same path** so prod
   and test exercise identical code.

Rubric mapping: 2+4 → observability, 4 → quality controls, 5 → guardrails, 3 → repeatable AI flow.
