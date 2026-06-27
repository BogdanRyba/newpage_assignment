"""Build a lightweight call/contains graph from chunked symbols.

Approximate, name-based resolution (no type/scope analysis): a CALLS edge is added when a
symbol's body mentions another known symbol's name; CONTAINS when a class's line range encloses
a method. This is intentionally simple — good enough to surface "related code" for augmentation,
and honestly documented as a heuristic (two same-named symbols in different files will conflate).
"""

from __future__ import annotations

import re
from collections import defaultdict

from app.domain.models import Chunk, GraphEdge, GraphNode

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CLASS_KINDS = {"class_definition", "class_declaration", "interface_declaration"}


def build_graph(chunks: list[Chunk]) -> tuple[list[GraphNode], list[GraphEdge]]:
    sym_chunks = [c for c in chunks if c.symbol]
    nodes = [
        GraphNode(
            symbol=c.symbol or "",
            path=c.path,
            lang=c.lang,
            kind=c.kind,
            start_line=c.start_line,
            end_line=c.end_line,
            text=c.text,
            point_id=c.point_id,
        )
        for c in sym_chunks
    ]

    names = {c.symbol for c in sym_chunks if c.symbol}
    edges: list[GraphEdge] = []
    seen: set[tuple[str, str, str]] = set()

    def add(src: str, dst: str, etype: str) -> None:
        key = (src, dst, etype)
        if src != dst and key not in seen:
            seen.add(key)
            edges.append(GraphEdge(src=src, dst=dst, type=etype))

    # CALLS: a symbol references another known symbol's name in its body.
    for c in sym_chunks:
        if not c.symbol:
            continue
        referenced = set(_IDENT.findall(c.text)) & names
        for dst in referenced:
            add(c.symbol, dst, "CALLS")

    # CONTAINS: a class's line range encloses another symbol in the same file.
    by_path: dict[str, list[Chunk]] = defaultdict(list)
    for c in sym_chunks:
        by_path[c.path].append(c)
    for items in by_path.values():
        classes = [x for x in items if x.kind in _CLASS_KINDS]
        for cls in classes:
            for m in items:
                if m is cls or not cls.symbol or not m.symbol:
                    continue
                if cls.start_line <= m.start_line and m.end_line <= cls.end_line:
                    add(cls.symbol, m.symbol, "CONTAINS")

    return nodes, edges
