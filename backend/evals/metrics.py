"""Retrieval + answer metrics for the eval-runner.

- recall@k: fraction of a case's expected files that appear in the top-k retrieved.
- MRR: reciprocal rank of the first retrieved chunk from an expected file.
- citation_validity: every [n] in the answer maps to a real source.
"""

from __future__ import annotations

from app.domain.citation.service import check_validity
from app.domain.models import Hit
from app.domain.retrieval.context import Source


def recall_at_k(ranked: list[Hit], expected_files: list[str]) -> float:
    if not expected_files:
        return 1.0
    retrieved = {h.chunk.path for h in ranked}
    hit = sum(1 for f in expected_files if f in retrieved)
    return hit / len(expected_files)


def reciprocal_rank(ranked: list[Hit], expected_files: list[str]) -> float:
    if not expected_files:
        return 1.0
    for i, h in enumerate(ranked):
        if h.chunk.path in expected_files:
            return 1.0 / (i + 1)
    return 0.0


def citation_validity(answer_text: str, sources: list[Source]) -> bool:
    return check_validity(answer_text, sources).is_valid
