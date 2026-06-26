---
description: Scaffold a new LangGraph query-graph node with typed state I/O and a cassette-backed test.
argument-hint: <node_name> (e.g. "rerank")
---

Create a new query-graph node following the `langgraph-nodes` skill. Argument: $ARGUMENTS

Steps:
1. Write the failing test first (`backend/tests/unit/test_node_<name>.py`): construct a `State`, run the
   node, assert the partial-state contract. Positive + negative + edge. Mock ports; if it calls the LLM,
   drive it through a cassette (`CASSETTE_MODE=replay`).
2. Add `backend/app/services/query/nodes/<name>.py`: a function `State -> partial State`. Side effects
   only through ports. Wrap with `instrument` for tracing/logging.
3. Wire it into `services/query/graph.py` (edge + any conditional routing).
4. If it calls an LLM, add/extend a prompt module in `app/prompts/` (never inline strings).
5. Run `/run-checks`.
