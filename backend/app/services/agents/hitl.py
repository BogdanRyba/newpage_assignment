"""Human-in-the-loop: draft a high-stakes proposal, pause for approval, then resume.

A tiny LangGraph — propose → gate(interrupt) → finalize — compiled with a checkpointer so the
pause is DURABLE: the run state lives in Postgres, so a fresh process/worker can resume the same
thread after a restart or a reconnecting client. The gate calls `interrupt()`, which raises on the
first pass (the run pauses with the proposal as payload) and, on resume, returns the human's
decision passed via `Command(resume=...)`. Nothing is applied unless the human approves.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings
from app.domain.models import Answer
from app.prompts import propose
from app.services.query.state import Deps


class HitlState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    repo_id: str
    question: str
    proposal: str = ""
    decision: str = ""
    answer: Answer | None = None


def _propose_node(deps: Deps):  # noqa: ANN202 — node
    async def _node(state: HitlState) -> dict:
        text = await deps.generator.complete(propose.SYSTEM, propose.build_user(state.question))
        return {"proposal": text.strip()}

    return _node


def _gate_node(deps: Deps):  # noqa: ANN202 — node
    async def _node(state: HitlState) -> dict:
        # Pauses the run; resumes with the human's decision via Command(resume=...).
        decision = interrupt(
            {"type": "approval", "action": "apply_change", "proposal": state.proposal}
        )
        return {"decision": str(decision)}

    return _node


def _finalize_node(deps: Deps):  # noqa: ANN202 — node
    async def _node(state: HitlState) -> dict:
        if state.decision.lower() == "approve":
            return {"answer": Answer(text=f"Approved proposal:\n\n{state.proposal}")}
        return {
            "answer": Answer(
                text="The proposed change was rejected; no action was taken.",
                refused=True,
                refusal_reason="rejected",
            )
        }

    return _node


def build_hitl_graph(deps: Deps, checkpointer):  # noqa: ANN001, ANN201 — compiled LangGraph
    g = StateGraph(HitlState)
    g.add_node("propose", _propose_node(deps))
    g.add_node("gate", _gate_node(deps))
    g.add_node("finalize", _finalize_node(deps))
    g.add_edge(START, "propose")
    g.add_edge("propose", "gate")
    g.add_edge("gate", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


def _psycopg_dsn() -> str:
    """Convert the app's SQLAlchemy/asyncpg URL to a plain psycopg DSN for the checkpointer."""
    url = get_settings().database_url
    return url.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")


@asynccontextmanager
async def open_checkpointer() -> AsyncIterator[object]:
    """Yield a ready Postgres checkpointer (durable), or an in-memory one if PG is unavailable.

    Degrades instead of failing: HITL still works within a process if the durable store can't be
    reached — we just lose cross-restart resume, which is logged by the caller.
    """
    from app.core.logging import get_logger

    log = get_logger("hitl")
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(_psycopg_dsn()) as saver:
            await saver.setup()
            yield saver
    except Exception as exc:  # noqa: BLE001 — never drop the user; degrade to in-memory
        log.warning("hitl_checkpointer_degraded", error=str(exc))
        yield MemorySaver()


class HitlRunner:
    """Drives the HITL graph: start() runs until the approval pause; resume() finishes it."""

    def __init__(self, deps: Deps, checkpointer) -> None:  # noqa: ANN001
        self.graph = build_hitl_graph(deps, checkpointer)

    async def start(self, thread_id: str, repo_id: str, question: str) -> dict:
        """Run to the approval gate. Returns {"interrupt": payload} or {"answer": Answer}."""
        cfg = {"configurable": {"thread_id": thread_id}}
        result = await self.graph.ainvoke(
            HitlState(repo_id=repo_id, question=question), config=cfg
        )
        return _result(result)

    async def resume(self, thread_id: str, decision: str) -> dict:
        """Resume a paused run with the human's decision."""
        cfg = {"configurable": {"thread_id": thread_id}}
        result = await self.graph.ainvoke(Command(resume=decision), config=cfg)
        return _result(result)


def _result(result: dict) -> dict:
    interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
    if interrupts:
        return {"interrupt": interrupts[0].value}
    answer = result.get("answer") if isinstance(result, dict) else None
    return {"answer": answer or Answer(text="No proposal produced.", refused=True)}
