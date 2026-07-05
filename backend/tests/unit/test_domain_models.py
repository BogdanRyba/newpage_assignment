"""Contract tests for domain value objects.

These pin behaviour we rely on everywhere: citation labels, idempotent point IDs,
and repo-scoped collection naming. If any of these change silently, retrieval and
citation rendering break — so the tests must fail loudly.
"""

from __future__ import annotations

from app.domain.models import Chunk, CodeLocation, RepoContext, point_id


def _chunk(index: int = 0, path: str = "a.py", blob_sha: str = "blobA") -> Chunk:
    return Chunk(
        repo_id="r1",
        path=path,
        blob_sha=blob_sha,
        lang="python",
        symbol="f",
        kind="function_definition",
        start_line=1,
        end_line=3,
        text="def f(): ...",
        index=index,
    )


# --- positive ---


def test_label_single_line_omits_range() -> None:
    loc = CodeLocation(path="a.py", start_line=7, end_line=7)
    assert loc.label == "a.py:7"


def test_label_multi_line_shows_range() -> None:
    loc = CodeLocation(path="a.py", start_line=7, end_line=12)
    assert loc.label == "a.py:7-12"


def test_point_id_is_deterministic() -> None:
    assert point_id("r1", "blobA", 0) == point_id("r1", "blobA", 0)
    assert _chunk().point_id == point_id("r1", "blobA", 0)


def test_point_id_is_content_addressed_not_path_addressed() -> None:
    # Same blob at two different paths → SAME id (shared, never re-embedded). And a chunk's
    # id is independent of its path — proving the scheme keys on content, not location.
    a = _chunk(path="src/a.py", blob_sha="blobX")
    b = _chunk(path="vendor/a.py", blob_sha="blobX")
    assert a.point_id == b.point_id
    # Different content → different id.
    assert _chunk(blob_sha="blobY").point_id != a.point_id


def test_repo_context_scopes_collection_and_namespace() -> None:
    ctx = RepoContext(repo_id="abc", name="demo")
    assert ctx.qdrant_collection == "repo_abc"
    assert ctx.graph_namespace == "abc"


# --- negative / edge ---


def test_point_id_differs_across_index_blob_and_repo() -> None:
    base = point_id("r1", "blobA", 0)
    assert point_id("r1", "blobA", 1) != base  # different chunk index
    assert point_id("r1", "blobB", 0) != base  # different content (blob)
    assert point_id("r2", "blobA", 0) != base  # different repo → isolation


def test_contains_is_inclusive_at_both_ends() -> None:
    loc = CodeLocation(path="a.py", start_line=10, end_line=20)
    assert loc.contains(10) and loc.contains(20)
    assert not loc.contains(9)
    assert not loc.contains(21)
