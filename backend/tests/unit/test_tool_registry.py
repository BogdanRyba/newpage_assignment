"""Tool registry: port-backed tools, unknown-tool safety, grounded results."""

from __future__ import annotations

from app.domain.models import FileAuthorship, RepoContext
from app.services.orchestrator.tools import default_registry
from tests.fakes import FakeAuthorship, make_deps, make_point

CTX = RepoContext(repo_id="r1")


async def test_retrieval_tool_returns_grounded_sources() -> None:
    deps = make_deps(
        points=[make_point(path="a.py", symbol="f", text="def f(): ...")], responses=[]
    )
    reg = default_registry(deps)
    res = await reg.invoke(CTX, "retrieval", {"query": "what is f"})
    assert res.ok
    assert res.sources and res.sources[0].path == "a.py"


async def test_unknown_tool_is_ignored_not_raised() -> None:
    deps = make_deps(points=[], responses=[])
    reg = default_registry(deps)
    res = await reg.invoke(CTX, "rm_rf", {"path": "/"})  # injected/garbage tool name
    assert res.ok is False
    assert res.sources == []
    assert reg.calls == ["rm_rf"]  # recorded, but no port was touched


async def test_authorship_tool_summarizes_real_author() -> None:
    fa = FileAuthorship(path="a.py", last_author="Ada", last_commit_sha="abcdef123456")
    deps = make_deps(points=[], responses=[], authorship=FakeAuthorship({"a.py": fa}))
    reg = default_registry(deps)
    res = await reg.invoke(CTX, "authorship_lookup", {"path": "a.py"})
    assert res.ok
    assert "Ada" in res.summary


async def test_graph_tool_disabled_returns_not_ok() -> None:
    deps = make_deps(points=[], responses=[])  # FakeGraphStore default enabled=False
    reg = default_registry(deps)
    res = await reg.invoke(CTX, "graph_neighbors", {"symbol": "f"})
    assert res.ok is False
