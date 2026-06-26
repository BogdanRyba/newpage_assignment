"""AST-aware chunking orchestration (the Strategy seam).

If the parser supports the file's language, chunk on symbol boundaries; otherwise —
and for oversized symbols — fall back to the recursive splitter. Every chunk gets a
contextual prefix (path + symbol) before embedding so short bodies stay distinguishable.
"""

from __future__ import annotations

from app.domain.chunking.fallback import recursive_split
from app.domain.models import Chunk
from app.ports.parser import Parser, SymbolSpan

MAX_SYMBOL_CHARS = 4000


def with_context(path: str, symbol: str | None, code: str) -> str:
    header = f"# {path}" + (f" · {symbol}" if symbol else "")
    return f"{header}\n{code}"


def chunk_file(repo_id: str, path: str, source: str, parser: Parser) -> list[Chunk]:
    if not source.strip():
        return []

    lang = parser.language_of(path)

    if parser.supports(path):
        spans = parser.parse_symbols(path, source)
        if spans:
            return _chunk_symbols(repo_id, path, lang, source.encode("utf-8"), spans)

    return _fallback(repo_id, path, lang, source)


def _chunk_symbols(
    repo_id: str, path: str, lang: str, data: bytes, spans: list[SymbolSpan]
) -> list[Chunk]:
    chunks: list[Chunk] = []
    idx = 0
    for span in spans:
        # tree-sitter offsets are byte offsets — slice bytes, then decode.
        code = data[span.start_byte : span.end_byte].decode("utf-8", "ignore")
        if len(code) <= MAX_SYMBOL_CHARS:
            chunks.append(
                Chunk(
                    repo_id=repo_id,
                    path=path,
                    lang=lang,
                    symbol=span.symbol,
                    kind=span.kind,
                    start_line=span.start_line,
                    end_line=span.end_line,
                    text=with_context(path, span.symbol, code),
                    index=idx,
                )
            )
            idx += 1
            continue
        # Oversized symbol: split its body but keep the symbol's identity.
        for block in recursive_split(code):
            chunks.append(
                Chunk(
                    repo_id=repo_id,
                    path=path,
                    lang=lang,
                    symbol=span.symbol,
                    kind=span.kind,
                    start_line=span.start_line + block.start_line - 1,
                    end_line=span.start_line + block.end_line - 1,
                    text=with_context(path, span.symbol, block.text),
                    index=idx,
                )
            )
            idx += 1
    return chunks


def _fallback(repo_id: str, path: str, lang: str, source: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for idx, block in enumerate(recursive_split(source)):
        chunks.append(
            Chunk(
                repo_id=repo_id,
                path=path,
                lang=lang,
                symbol=None,
                kind="block",
                start_line=block.start_line,
                end_line=block.end_line,
                text=with_context(path, None, block.text),
                index=idx,
            )
        )
    return chunks
