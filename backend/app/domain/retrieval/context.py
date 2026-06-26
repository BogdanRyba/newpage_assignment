"""Context assembly (Builder): turn ranked hits into numbered sources + a prompt block.

Rules: dedup chunks from the same (path, symbol) keeping the strongest; number sources [1..];
fence each as untrusted data; trim to a character budget (~4 chars/token) so we never blow the
context window. The numbering is the contract the synthesis prompt and citation builder share.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.models import CodeLocation, Hit


class Source(BaseModel):
    n: int
    path: str
    symbol: str | None
    lang: str
    start_line: int
    end_line: int
    text: str

    @property
    def location(self) -> CodeLocation:
        return CodeLocation(path=self.path, start_line=self.start_line, end_line=self.end_line)

    @property
    def label(self) -> str:
        return self.location.label


def assemble(hits: list[Hit], *, token_budget: int = 12_000) -> tuple[list[Source], str]:
    char_budget = token_budget * 4
    sources: list[Source] = []
    seen: set[tuple[str, str | None]] = set()
    used = 0
    n = 0

    for hit in hits:
        ch = hit.chunk
        key = (ch.path, ch.symbol)
        if key in seen:
            continue
        if used + len(ch.text) > char_budget and sources:
            break
        seen.add(key)
        n += 1
        used += len(ch.text)
        sources.append(
            Source(
                n=n,
                path=ch.path,
                symbol=ch.symbol,
                lang=ch.lang,
                start_line=ch.start_line,
                end_line=ch.end_line,
                text=ch.text,
            )
        )

    return sources, render_sources(sources)


def render_sources(sources: list[Source]) -> str:
    """Numbered, fenced source block. The fences mark content as untrusted data."""
    blocks = []
    for s in sources:
        head = f"[{s.n}] {s.label}" + (f" ({s.symbol})" if s.symbol else "")
        blocks.append(f"{head}\n<<<SOURCE {s.n}\n{s.text}\nSOURCE {s.n}>>>")
    return "\n\n".join(blocks)
