---
description: Add a golden Q&A case to the eval set (question + expected files/symbols).
argument-hint: "<question>"
---

Add an eval case following the `harness-evals` skill. Question: $ARGUMENTS

Steps:
1. Append a case to `backend/evals/golden.yaml` (or `.json`): `{ question, expected_files,
   expected_symbols, must_cite: true|false }`. For an off-topic/refusal case set `expect_refusal: true`.
2. If new LLM responses are involved, record cassettes: run the eval once with `CASSETTE_MODE=record`,
   then commit the new `tests/cassettes/*.json`.
3. Run the eval-runner (`CASSETTE_MODE=replay`) and confirm the case is scored (recall@k / MRR /
   faithfulness / citation-validity). Keep the suite above its CI threshold.
