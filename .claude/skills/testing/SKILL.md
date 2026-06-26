---
name: testing
description: Testing standards and procedure — TDD, positive/negative/adversarial coverage, the test pyramid, seeding Qdrant, and record/replay cassettes for deterministic LLM tests. Use whenever writing or reviewing tests.
---

# Testing

Core rule: **a test that cannot catch a real bug is not a test, it's dead weight.**
(The `weak_asserts` PreToolUse hook blocks green-washing; `tdd_redfirst` checks new tests are red first.)

## Principles
- Test **behaviour and contracts**, never the current implementation. If the code is wrong, the test
  must fail. Don't assert internal call counts unless the contract is about them.
- **TDD** for non-trivial logic (chunking, fusion, citation validation, guardrails, prompt contracts):
  write the failing test first.
- Every new module needs **≥1 positive, 1 negative, 1 edge** test. Add **adversarial** cases where the
  module touches untrusted input (prompt injection in a chunk, off-topic query, empty retrieval).
- **Mocking the entire subject under test is forbidden.**

## Pyramid
- **Unit** (`tests/unit`): mock the ports (LLM/embedder/vector). Test domain logic in isolation. Fast.
- **Integration** (`tests/integration`, `-m integration`): real Gemini + real Qdrant against a seeded
  test collection. A RAG integration test must assert the retrieved chunks **actually contain the
  expected symbols/lines**, not merely that something came back.
- **Eval** (`evals/`): golden Q&A through the full graph; assert recall@k / MRR / faithfulness ≥ threshold.

## Cassettes (deterministic LLM tests)
`CASSETTE_MODE=record` runs real calls and writes `tests/cassettes/<hash>.json`. `CASSETTE_MODE=replay`
serves them with no network — the CI default. Cassettes key on a hash of the model + input, so the
same call replays exactly. Record once when a prompt/version changes; commit the fixtures.

## Seeding Qdrant for integration
Use the `sample_repo/` fixture; ingest it into a throwaway collection named per test; assert chunk
counts and that a known query retrieves the known symbol. Tear the collection down after.
