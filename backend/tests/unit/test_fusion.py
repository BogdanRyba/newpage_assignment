"""RRF contract — combines lists, rewards agreement, stays order-stable."""

from __future__ import annotations

from app.domain.models import Chunk, Hit
from app.domain.retrieval.fusion import reciprocal_rank_fusion


def _hit(idx: int, score: float = 1.0) -> Hit:
    chunk = Chunk(
        repo_id="r",
        path="f.py",
        lang="python",
        symbol=f"s{idx}",
        kind="function_definition",
        start_line=1,
        end_line=2,
        text=f"def s{idx}(): ...",
        index=idx,
    )
    return Hit(chunk=chunk, score=score, source="dense")


def test_chunk_ranked_high_in_both_lists_wins() -> None:
    a = [_hit(1), _hit(2), _hit(3)]
    b = [_hit(2), _hit(1), _hit(3)]  # chunk 2 top of one, second in other
    fused = reciprocal_rank_fusion([a, b], k=60)
    ids = [h.chunk.index for h in fused]
    assert ids[0] in (1, 2)  # the two mutually-high chunks lead
    assert set(ids) == {1, 2, 3}  # no loss, no duplication


def test_dedup_across_lists() -> None:
    a = [_hit(1)]
    b = [_hit(1)]
    fused = reciprocal_rank_fusion([a, b], k=60)
    assert len(fused) == 1
    # appears in both lists at rank 0 → score = 2/(k+0)
    assert fused[0].score == 2.0 / 60
    assert fused[0].source == "fused"


def test_empty_lists_yield_empty() -> None:
    assert reciprocal_rank_fusion([[], []], k=60) == []
