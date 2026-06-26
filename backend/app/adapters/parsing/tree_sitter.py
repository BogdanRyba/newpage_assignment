"""Tree-sitter parser adapter (implements the Parser port).

Uses the canonical py-tree-sitter API with grammars loaded from
`tree_sitter_language_pack.get_language`. We capture function/class/method/interface
definitions; files without a grammar report `supports() == False` so the domain falls
back to recursive splitting.
"""

from __future__ import annotations

from pathlib import Path

from tree_sitter import Language, Parser
from tree_sitter_language_pack import get_language

from app.ports.parser import SymbolSpan

# extension → tree-sitter language
GRAMMARS: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}

# node types that constitute a retrievable symbol, per language
SYMBOL_TYPES: dict[str, set[str]] = {
    "python": {"function_definition", "class_definition"},
    "typescript": {
        "function_declaration",
        "method_definition",
        "class_declaration",
        "interface_declaration",
    },
    "tsx": {
        "function_declaration",
        "method_definition",
        "class_declaration",
        "interface_declaration",
    },
    "javascript": {"function_declaration", "method_definition", "class_declaration"},
}

_parsers: dict[str, Parser] = {}


def _parser_for(lang: str) -> Parser:
    if lang not in _parsers:
        language: Language = get_language(lang)  # type: ignore[arg-type]
        try:
            _parsers[lang] = Parser(language)
        except TypeError:  # older API: settable attribute
            parser = Parser()
            parser.language = language
            _parsers[lang] = parser
    return _parsers[lang]


class TreeSitterParser:
    def language_of(self, path: str) -> str:
        return GRAMMARS.get(Path(path).suffix, "text")

    def supports(self, path: str) -> bool:
        return Path(path).suffix in GRAMMARS

    def parse_symbols(self, path: str, source: str) -> list[SymbolSpan]:
        lang = self.language_of(path)
        if lang == "text":
            return []
        parser = _parser_for(lang)
        tree = parser.parse(source.encode("utf-8"))
        targets = SYMBOL_TYPES.get(lang, set())

        spans: list[SymbolSpan] = []
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type in targets:
                spans.append(
                    SymbolSpan(
                        kind=node.type,
                        symbol=_name_of(node),
                        start_byte=node.start_byte,
                        end_byte=node.end_byte,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                    )
                )
            stack.extend(reversed(node.children))

        spans.sort(key=lambda s: (s.start_byte, s.end_byte))
        return spans


def _name_of(node) -> str | None:  # noqa: ANN001 — tree_sitter.Node
    name = node.child_by_field_name("name")
    if name is not None and name.text is not None:
        return name.text.decode("utf-8", "ignore")
    for child in node.children:
        if child.type in {"identifier", "type_identifier", "property_identifier"}:
            return (child.text or b"").decode("utf-8", "ignore")
    return None
