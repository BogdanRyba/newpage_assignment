---
name: code-chunking
description: How Ariadne splits source files into retrievable chunks. Use when touching ingestion parsing, tree-sitter, chunk boundaries, fallback splitting, or chunk metadata.
---

# Code chunking

Chunk on **AST boundaries**, not fixed token windows — function/class/method spans are the
natural unit of "what does this do", and they make citations land on a whole symbol.

## Procedure
1. Look up a tree-sitter grammar by file extension (`tree_sitter_language_pack.get_parser`).
   Supported in MVP: Python, TypeScript, TSX, JavaScript.
2. **Unknown extension → do not drop the file.** Route it to the recursive splitter
   (`domain/chunking/fallback.py`, ~1200 chars, ~120 overlap) so its content stays retrievable.
3. Walk the tree; emit a chunk per top-level + nested `function_definition` / `class_definition` /
   method. Keep a chunk if it's within size bounds; split oversized symbols with the fallback.
4. Prepend a **contextual prefix** before embedding: `path` + enclosing symbol + docstring/leading
   comment. This disambiguates short bodies ("`__init__`" appears everywhere).
5. Assign `index` in file order → `point_id = uuid5(repo_id:path:index)` (idempotent upsert).

## Chunk metadata (must be present)
`{repo_id, path, lang, symbol, kind, start_line, end_line, text, index}` — lines are **1-based,
inclusive** (citations depend on this). `symbol` may be None for fallback blocks; `kind` records the
node type (`function_definition`, `class_definition`, `block`).

## Tests (per `testing` skill)
- positive: a known Python file yields one chunk per function with correct line ranges + symbol.
- negative/edge: empty file → no chunks; a file with only comments → fallback block.
- combination: Python vs TS produce equivalent structure; an unknown extension (`.rs`) hits fallback.
