"""Graph extraction — CALLS by name reference, CONTAINS by enclosing line range."""

from __future__ import annotations

from app.domain.graph.extract import build_graph
from app.domain.models import Chunk


def _c(
    symbol, kind, start, end, text, path="m.py", idx=0, lang="python", bases=None, implements=None
) -> Chunk:
    return Chunk(
        repo_id="r",
        path=path,
        lang=lang,
        symbol=symbol,
        kind=kind,
        start_line=start,
        end_line=end,
        text=text,
        index=idx,
        bases=bases or [],
        implements=implements or [],
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


# --- inheritance edges (EXTENDS / IMPLEMENTS) ---


def test_extends_edge_for_subclass_and_external_base_ignored() -> None:
    # OverlapRanker(Ranker): Ranker is a repo symbol → EXTENDS edge. Ranker(ABC): ABC is external
    # (not a repo symbol) → no dangling edge.
    chunks = [
        _c("Ranker", "class_definition", 1, 2, "class Ranker(ABC): ...", bases=["ABC"], idx=0),
        _c(
            "OverlapRanker",
            "class_definition",
            4,
            5,
            "class OverlapRanker(Ranker): ...",
            bases=["Ranker"],
            idx=1,
        ),
    ]
    _, edges = build_graph(chunks)
    extends = {(e.src, e.dst) for e in edges if e.type == "EXTENDS"}
    assert ("OverlapRanker", "Ranker") in extends
    assert not any(e.dst == "ABC" for e in edges)  # external base → no edge


def test_implements_edge_for_class_to_interface() -> None:
    chunks = [
        _c(
            "Ranker", "interface_declaration", 1, 2, "interface Ranker {}", lang="typescript", idx=0
        ),
        _c(
            "OverlapRanker",
            "class_declaration",
            4,
            5,
            "class OverlapRanker implements Ranker {}",
            lang="typescript",
            implements=["Ranker"],
            idx=1,
        ),
    ]
    _, edges = build_graph(chunks)
    impl = {(e.src, e.dst) for e in edges if e.type == "IMPLEMENTS"}
    assert ("OverlapRanker", "Ranker") in impl


def test_same_name_classes_across_languages_keep_separate_edges() -> None:
    # The collision the graph must survive: a Python and a TS `OverlapRanker`, each tied to a
    # same-named `Ranker`. build_graph keeps the two edges distinct by src_lang (neither dropped by
    # dedup); the language-scoped upsert then stops any cross-language link (asserted in the
    # graph_store integration test).
    chunks = [
        _c("Ranker", "class_definition", 1, 2, "class Ranker(ABC): ...", bases=["ABC"], idx=0),
        _c(
            "OverlapRanker",
            "class_definition",
            4,
            5,
            "class OverlapRanker(Ranker): ...",
            bases=["Ranker"],
            idx=1,
        ),
        _c(
            "Ranker",
            "interface_declaration",
            1,
            2,
            "interface Ranker {}",
            lang="typescript",
            path="api.ts",
            idx=2,
        ),
        _c(
            "OverlapRanker",
            "class_declaration",
            4,
            5,
            "class OverlapRanker implements Ranker {}",
            lang="typescript",
            path="api.ts",
            implements=["Ranker"],
            idx=3,
        ),
    ]
    _, edges = build_graph(chunks)
    extends = {(e.src, e.dst, e.src_lang) for e in edges if e.type == "EXTENDS"}
    implements = {(e.src, e.dst, e.src_lang) for e in edges if e.type == "IMPLEMENTS"}
    assert ("OverlapRanker", "Ranker", "python") in extends
    assert ("OverlapRanker", "Ranker", "typescript") in implements  # both languages survived
