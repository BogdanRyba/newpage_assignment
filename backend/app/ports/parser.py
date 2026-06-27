"""Port: source → symbol spans (tree-sitter adapter implements this)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class SymbolSpan(BaseModel):
    """One AST symbol: its kind, name, byte/line extent, and any supertypes."""

    kind: str
    symbol: str | None
    start_byte: int
    end_byte: int
    start_line: int  # 1-based, inclusive
    end_line: int
    bases: list[str] = []  # superclasses / super-interfaces (Python bases, TS `extends`)
    implements: list[str] = []  # interfaces a TS class declares with `implements`


@runtime_checkable
class Parser(Protocol):
    def supports(self, path: str) -> bool:
        """True if this parser has a grammar for the file's language."""
        ...

    def parse_symbols(self, path: str, source: str) -> list[SymbolSpan]:
        """Top-level + nested function/class/method spans, in source order."""
        ...

    def language_of(self, path: str) -> str:
        """Language tag for the path (e.g. 'python'); 'text' if unknown."""
        ...
