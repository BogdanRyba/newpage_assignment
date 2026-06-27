"""Chunking contract tests — real tree-sitter (the subject is deterministic).

Covers AST chunking for Python and TS, the no-grammar fallback, and edges. If symbol
boundaries or line ranges drift, citations land on the wrong code — so these must fail loudly.
"""

from __future__ import annotations

from app.adapters.parsing.tree_sitter import TreeSitterParser
from app.domain.chunking.service import chunk_file

PARSER = TreeSitterParser()

PY = """\
def alpha(x):
    return x + 1


class Greeter:
    def hello(self, name):
        return f"hi {name}"
"""

TS = """\
export function add(a: number, b: number): number {
  return a + b;
}

export class Counter {
  value = 0;
  inc() {
    this.value += 1;
  }
}
"""


# --- positive ---


def test_python_chunks_have_symbols_and_line_ranges() -> None:
    chunks = chunk_file("r1", "calc.py", PY, PARSER)
    symbols = {c.symbol for c in chunks}
    assert {"alpha", "Greeter", "hello"} <= symbols
    assert all(c.lang == "python" for c in chunks)

    alpha = next(c for c in chunks if c.symbol == "alpha")
    assert alpha.start_line == 1 and alpha.end_line == 2
    assert alpha.kind == "function_definition"
    assert "def alpha" in alpha.text
    assert alpha.text.startswith("# calc.py")  # contextual prefix


def test_typescript_chunks_capture_functions_and_classes() -> None:
    chunks = chunk_file("r1", "util.ts", TS, PARSER)
    symbols = {c.symbol for c in chunks}
    assert "add" in symbols
    assert "Counter" in symbols
    assert all(c.lang == "typescript" for c in chunks)


def test_point_ids_unique_per_chunk_and_idempotent() -> None:
    a = chunk_file("r1", "calc.py", PY, PARSER)
    b = chunk_file("r1", "calc.py", PY, PARSER)
    ids_a = [c.point_id for c in a]
    assert len(set(ids_a)) == len(ids_a)  # unique within a file
    assert ids_a == [c.point_id for c in b]  # deterministic across runs


# --- negative / edge ---


def test_empty_source_yields_no_chunks() -> None:
    assert chunk_file("r1", "calc.py", "   \n\n", PARSER) == []


MODULE_FILE = '''\
"""Module docstring describing what this configuration module is for."""

MAX_RESULTS = 20
STOPWORDS = {"the", "a", "an"}


def helper():
    return MAX_RESULTS
'''


def test_module_level_docstring_and_constants_are_chunked() -> None:
    # Regression: top-level constants/docstrings (e.g. prompt SYSTEM strings) must be
    # indexed, not dropped by AST chunking — otherwise design/config questions can't retrieve them.
    chunks = chunk_file("r1", "config.py", MODULE_FILE, PARSER)
    module_text = " ".join(c.text for c in chunks if c.kind == "module")
    assert "module" in {c.kind for c in chunks}
    assert "MAX_RESULTS" in module_text
    assert "STOPWORDS" in module_text
    assert "Module docstring" in module_text
    assert any(c.symbol == "helper" for c in chunks)  # the function is still its own chunk


def test_unknown_language_falls_back_to_blocks() -> None:
    src = 'fn main() {\n    println!("hi");\n}\n' * 3
    chunks = chunk_file("r1", "main.rs", src, PARSER)
    assert chunks, "fallback must still produce retrievable chunks"
    assert all(c.kind == "block" and c.symbol is None for c in chunks)
    assert all(c.lang == "text" for c in chunks)
