"""Merge parallel persona answers into one, unioning + deduping their citations.

Cite-or-refuse holds by construction: the merged citation set is exactly the union of the
non-refused sub-answers' citations (keyed by location+symbol), renumbered [1..M]; each
sub-answer's local [n] markers are mechanically remapped to the merged numbers. If every
persona refused, the merge is a refusal. The LLM is not involved here — this is pure code, so
no fabricated citation can be introduced at the merge step.
"""

from __future__ import annotations

import re

from app.domain.models import Answer, Citation

_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def _key(c: Citation) -> tuple[str, int, int, str | None]:
    loc = c.location
    return (loc.path, loc.start_line, loc.end_line, c.symbol)


def _remap_markers(text: str, local_to_merged: dict[int, int]) -> str:
    def sub(m: re.Match[str]) -> str:
        nums = [int(p) for p in m.group(1).split(",")]
        mapped = [str(local_to_merged[n]) for n in nums if n in local_to_merged]
        return "[" + ", ".join(mapped) + "]" if mapped else ""

    return _MARKER.sub(sub, text)


def merge_answers(results: list[tuple[str, Answer]]) -> Answer:
    """Combine (persona, answer) pairs into one answer with unified citations."""
    grounded = [(p, a) for p, a in results if not a.refused]
    if not grounded:
        reason = results[0][1].refusal_reason if results else "empty"
        return Answer(
            text="I couldn't find a grounded answer to that in this repository.",
            refused=True,
            refusal_reason=reason,
        )

    merged_citations: list[Citation] = []
    key_to_n: dict[tuple[str, int, int, str | None], int] = {}
    for _persona, a in grounded:
        for c in a.citations:
            k = _key(c)
            if k not in key_to_n:
                n = len(merged_citations) + 1
                key_to_n[k] = n
                merged_citations.append(Citation(n=n, location=c.location, symbol=c.symbol))

    parts: list[str] = []
    for _persona, a in grounded:
        local_to_merged = {c.n: key_to_n[_key(c)] for c in a.citations}
        parts.append(_remap_markers(a.text, local_to_merged))

    return Answer(text="\n\n".join(p for p in parts if p.strip()), citations=merged_citations)
