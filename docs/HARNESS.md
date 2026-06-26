# Harness

Two distinct harnesses — don't conflate them.

## 1. Dev-time harness (how AI tools build this repo — README section g)
Configures Claude Code so standards are enforced by the environment, not model memory:
- **`CLAUDE.md`** — always-loaded context: stack, invariants, layout, DoD, testing rules, "never" list.
- **Hooks** (`.claude/hooks`, wired in `.claude/settings.json`):
  - `format.sh` (PostToolUse) — ruff/prettier on write.
  - `guard.sh` (PreToolUse) — block writes to `.env`, lockfiles, applied migrations.
  - `weak_asserts.py` (PreToolUse) — block green-washing tests (all asserts trivially true).
  - `tdd_redfirst.sh` (PostToolUse) — new test files should be red first.
  - `fast_tests.sh` (Stop) — never end a turn on red unit tests.
- **Skills** (`.claude/skills`) — procedures: code-chunking, rag-pipeline, langgraph-nodes,
  prompt-authoring, fastapi-conventions, qdrant-ops, harness-evals, testing.
- **Commands** (`.claude/commands`) — `/new-endpoint`, `/new-node`, `/add-eval`, `/run-checks`.
- **Subagent** — `reviewer` (isolated-context diff review against invariants).

## 2. Runtime/eval harness (makes Daedalus observable, deterministic, bounded)
Seven components — see the `harness-evals` skill for the canonical list:
typed state + node contracts · instrumentation (OTel + structlog) · record/replay cassettes ·
eval-runner (recall@k / MRR / faithfulness / citation-validity) · reusable guardrail nodes ·
budgets & limits · the `AgentRunner` facade (one code path for API and evals).

Rubric mapping: instrumentation + eval-runner → observability; eval-runner → quality controls;
guardrail nodes → guardrails; cassettes + AgentRunner → repeatable, maintainable AI flow.
