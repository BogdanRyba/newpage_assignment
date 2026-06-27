"""Graph extraction — CALLS by name reference, CONTAINS by enclosing line range."""

from __future__ import annotations

from app.domain.graph.extract import build_graph
from app.domain.models import Chunk


def _c(symbol, kind, start, end, text, path="m.py", idx=0) -> Chunk:
    return Chunk(
        repo_id="r",
        path=path,
        lang="python",
        symbol=symbol,
        kind=kind,
        start_line=start,
        end_line=end,
        text=text,
        index=idx,
    )


def test_calls_edge_when_body_references_another_symbol() -> None:
    chunks = [
        _c("helper", "function_definition", 1, 2, "def helper():\n    return 1", idx=0),
        _c("main", "function_definition", 4, 6, "def main():\n    return helper() + 1", idx=1),
    ]
    nodes, edges = build_graph(chunks)
    assert {n.symbol for n in nodes} == {"helper", "main"}
    calls = {(e.src, e.dst) for e in edges if e.type == "CALLS"}
    assert ("main", "helper") in calls
    assert ("helper", "main") not in calls  # helper doesn't reference main


def test_contains_edge_for_class_method() -> None:
    chunks = [
        _c("Calc", "class_definition", 1, 6, "class Calc:\n    def add(self): ...", idx=0),
        _c("add", "function_definition", 2, 3, "def add(self):\n    return 1", idx=1),
    ]
    _, edges = build_graph(chunks)
    contains = {(e.src, e.dst) for e in edges if e.type == "CONTAINS"}
    assert ("Calc", "add") in contains


def test_no_self_edges_and_unknown_names_ignored() -> None:
    chunks = [_c("solo", "function_definition", 1, 2, "def solo():\n    return unknown_fn()")]
    nodes, edges = build_graph(chunks)
    assert len(nodes) == 1
    assert edges == []  # references an unknown name, and never itself
