"""Parser contract — symbol extraction including class heritage (bases / implements).

The inheritance graph (EXTENDS/IMPLEMENTS edges) is only as good as what the parser pulls off
each class/interface node, so these assert the *exact* supertype names across Python and TS. If
heritage extraction silently breaks, "what are the subclasses of X?" stops working — fail loudly.
"""

from __future__ import annotations

from app.adapters.parsing.tree_sitter import TreeSitterParser

PARSER = TreeSitterParser()
_CLASS_KINDS = {"class_definition", "class_declaration", "interface_declaration"}


def _classes(path: str, src: str) -> dict[str, tuple[list[str], list[str]]]:
    return {
        s.symbol: (s.bases, s.implements)
        for s in PARSER.parse_symbols(path, src)
        if s.kind in _CLASS_KINDS
    }


# --- positive ---

PY = """\
from abc import ABC, abstractmethod


class Ranker(ABC):
    @abstractmethod
    def score(self): ...


class OverlapRanker(Ranker):
    def score(self):
        return 1
"""


def test_python_subclass_records_its_base() -> None:
    classes = _classes("r.py", PY)
    assert classes["OverlapRanker"] == (["Ranker"], [])  # subclass records its base
    assert classes["Ranker"] == (["ABC"], [])  # external base captured by bare name


def test_python_multiple_inheritance_skips_metaclass_kwarg() -> None:
    classes = _classes("r.py", "class C(A, B, metaclass=Meta):\n    pass\n")
    assert classes["C"] == (["A", "B"], [])  # metaclass= is a kwarg, not a base


# --- negative / edge ---


def test_python_class_without_base_has_empty_bases() -> None:
    classes = _classes("r.py", "class Plain:\n    x = 1\n")
    assert classes["Plain"] == ([], [])


TS = """\
export interface NoteDTO { id: number; }
export interface ScoredNote extends NoteDTO { score: number; }
export interface Ranker { score(n: NoteDTO): number; }
export class OverlapRanker implements Ranker { score(n: NoteDTO): number { return 0; } }
export class Both extends Base implements I, J { run(): void {} }
"""


def test_typescript_extends_and_implements_are_distinguished() -> None:
    classes = _classes("r.ts", TS)
    assert classes["ScoredNote"] == (["NoteDTO"], [])  # interface extends interface → bases
    assert classes["OverlapRanker"] == ([], ["Ranker"])  # class implements interface → implements
    assert classes["Both"] == (["Base"], ["I", "J"])  # extends + multi-implements split correctly
    assert classes["NoteDTO"] == ([], [])  # no heritage
