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

# class/interface nodes whose heritage (bases / implements) we extract for the inheritance graph
_CLASS_NODES = {"class_definition", "class_declaration", "interface_declaration"}
# node types that name a type/superclass across the python + typescript grammars
_TYPE_NODES = {
    "identifier",
    "attribute",
    "type_identifier",
    "member_expression",
    "nested_type_identifier",
    "generic_type",
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
                bases, implements = _bases_of(node, lang) if node.type in _CLASS_NODES else ([], [])
                spans.append(
                    SymbolSpan(
                        kind=node.type,
                        symbol=_name_of(node),
                        start_byte=node.start_byte,
                        end_byte=node.end_byte,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        bases=bases,
                        implements=implements,
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


def _decode(node) -> str:  # noqa: ANN001 — tree_sitter.Node
    """Bare last segment of a type/identifier node, utf-8 decoded.

    `abc.ABC` → `ABC`, `Base<T>` → `Base`, `Foo` → `Foo`. We match against same-repo symbol
    *names* (the graph keys on bare names), so we strip namespace/type-args the way an
    unqualified reference would appear.
    """
    raw = (node.text or b"").decode("utf-8", "ignore")
    return raw.split(".")[-1].split("<")[0].strip()


def _bases_of(node, lang: str) -> tuple[list[str], list[str]]:  # noqa: ANN001 — tree_sitter.Node
    """`(extends, implements)` supertype names for a class/interface node.

    Defensive: reads children by node *type* (not fragile field names), tolerates missing
    heritage, skips Python `metaclass=`/kwargs (only `identifier`/`attribute` count) and TS
    `type_arguments`. External bases (ABC, library types) come back as plain names; the graph
    layer decides whether they resolve to a known symbol.
    """
    extends: list[str] = []
    implements: list[str] = []

    if lang == "python":
        args = node.child_by_field_name("superclasses")
        if args is None:  # fallback: locate the argument_list child by type
            args = next((c for c in node.children if c.type == "argument_list"), None)
        if args is not None:
            extends = [
                name
                for c in args.named_children
                if c.type in {"identifier", "attribute"} and (name := _decode(c))
            ]
        return extends, implements

    # TypeScript / TSX / JS
    if node.type == "interface_declaration":
        clause = next((c for c in node.children if c.type == "extends_type_clause"), None)
        if clause is not None:
            extends = [
                name
                for c in clause.named_children
                if c.type in _TYPE_NODES and (name := _decode(c))
            ]
        return extends, implements

    heritage = next((c for c in node.children if c.type == "class_heritage"), None)
    for clause in heritage.children if heritage is not None else node.children:
        if clause.type == "extends_clause":
            for c in clause.named_children:  # first type-ish child is the superclass
                if c.type in _TYPE_NODES and (name := _decode(c)):
                    extends.append(name)
                    break
        elif clause.type == "implements_clause":
            implements.extend(
                name
                for c in clause.named_children
                if c.type in _TYPE_NODES and (name := _decode(c))
            )

    return extends, implements
