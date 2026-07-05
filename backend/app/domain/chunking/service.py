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


def chunk_file(
    repo_id: str, path: str, source: str, parser: Parser, blob_sha: str = ""
) -> list[Chunk]:
    if not source.strip():
        return []

    lang = parser.language_of(path)

    if parser.supports(path):
        spans = parser.parse_symbols(path, source)
        if spans:
            chunks = _chunk_symbols(repo_id, path, lang, source, spans)
        else:
            chunks = _fallback(repo_id, path, lang, source)
    else:
        chunks = _fallback(repo_id, path, lang, source)

    # All chunks of a file share its blob (the content address feeding point_id).
    for c in chunks:
        c.blob_sha = blob_sha
    return chunks


def _chunk_symbols(
    repo_id: str, path: str, lang: str, source: str, spans: list[SymbolSpan]
) -> list[Chunk]:
    data = source.encode("utf-8")
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
                    bases=span.bases,
                    implements=span.implements,
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
                    bases=span.bases,
                    implements=span.implements,
                )
            )
            idx += 1

    # Module-level residual: docstrings, top-level constants (e.g. prompt SYSTEM strings),
    # config values, imports — content NOT inside any symbol span, which AST chunking would
    # otherwise drop, leaving it unretrievable. Emit it as `module` chunks.
    _emit_module_chunks(chunks, repo_id, path, lang, source, spans, idx)
    return chunks


def _emit_module_chunks(
    chunks: list[Chunk],
    repo_id: str,
    path: str,
    lang: str,
    source: str,
    spans: list[SymbolSpan],
    idx: int,
) -> None:
    lines = source.splitlines()
    n = len(lines)
    covered = [False] * (n + 2)
    for span in spans:
        for ln in range(span.start_line, min(span.end_line, n) + 1):
            covered[ln] = True

    i = 1
    while i <= n:
        if covered[i]:
            i += 1
            continue
        j = i
        while j <= n and not covered[j]:
            j += 1
        run = lines[i - 1 : j - 1]
        if _meaningful(run):
            for block in recursive_split("\n".join(run)):
                chunks.append(
                    Chunk(
                        repo_id=repo_id,
                        path=path,
                        lang=lang,
                        symbol=None,
                        kind="module",
                        start_line=i + block.start_line - 1,
                        end_line=i + block.end_line - 1,
                        text=with_context(path, None, block.text),
                        index=idx,
                    )
                )
                idx += 1
        i = j


def _meaningful(run_lines: list[str]) -> bool:
    """Skip trivial gaps (blank lines, a lone import); keep docstrings/constants/config."""
    non_blank = [ln for ln in run_lines if ln.strip()]
    return len(non_blank) >= 2 or len("".join(non_blank).strip()) >= 40


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
