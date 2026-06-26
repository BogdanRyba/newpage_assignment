"""Citation build + validation + pruning.

Citation-*validity* is deterministic and lives here (every [n] must map to a real source);
*faithfulness* (is the claim supported?) is the LLM critic's job. `drop_unsupported` removes
sentences the critic couldn't support, as the last step before refusing.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.domain.models import Citation
from app.domain.retrieval.context import Source

_MARKER = re.compile(r"\[(\d+)\]")
_SENTENCE = re.compile(r"[^.!?]*[.!?]|[^.!?]+$")


class CitationCheck(BaseModel):
    has_any: bool
    invalid_markers: list[int]
    is_valid: bool


def markers_in(text: str) -> list[int]:
    return [int(m) for m in _MARKER.findall(text)]


def build_citations(text: str, sources: list[Source]) -> list[Citation]:
    by_n = {s.n: s for s in sources}
    out: list[Citation] = []
    seen: set[int] = set()
    for n in markers_in(text):
        if n in by_n and n not in seen:
            seen.add(n)
            s = by_n[n]
            out.append(Citation(n=n, location=s.location, symbol=s.symbol))
    return out


def check_validity(text: str, sources: list[Source]) -> CitationCheck:
    valid_ns = {s.n for s in sources}
    used = markers_in(text)
    invalid = sorted({n for n in used if n not in valid_ns})
    return CitationCheck(
        has_any=bool(used),
        invalid_markers=invalid,
        is_valid=bool(used) and not invalid,
    )


def drop_unsupported(text: str, sources: list[Source], unsupported: list[str]) -> str:
    """Keep only sentences that are cited, valid, and not flagged unsupported by the critic."""
    valid_ns = {s.n for s in sources}
    kept: list[str] = []
    for raw in _SENTENCE.findall(text):
        sentence = raw.strip()
        if not sentence:
            continue
        ns = markers_in(sentence)
        if not ns or any(n not in valid_ns for n in ns):
            continue  # uncited or hallucinated marker
        if any(_overlaps(sentence, frag) for frag in unsupported):
            continue  # critic-flagged
        kept.append(sentence)
    return " ".join(kept).strip()


def _overlaps(sentence: str, fragment: str) -> bool:
    frag = fragment.strip().strip('"').lower()
    return len(frag) > 8 and frag in sentence.lower()
