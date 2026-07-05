"""diff_manifests: pure set-algebra over two path→blob_sha manifests.

This is the version-comparison primitive (master↔dev, dev↔v2.3.5) and the basis
of incremental re-index. It must work on any two indexed versions with no git
invocation and no LLM. Positive / negative / edge coverage per CLAUDE.md.
"""

from __future__ import annotations

from app.domain.versioning.diff import diff_manifests


def test_added_removed_modified_partitioned() -> None:
    base = {"a.py": "blobA", "b.py": "blobB", "keep.py": "blobK"}
    head = {"a.py": "blobA2", "c.py": "blobC", "keep.py": "blobK"}

    diff = diff_manifests(base, head)

    assert [c.path for c in diff.added] == ["c.py"]
    assert diff.added[0].old_blob_sha is None
    assert diff.added[0].new_blob_sha == "blobC"

    assert [c.path for c in diff.removed] == ["b.py"]
    assert diff.removed[0].old_blob_sha == "blobB"
    assert diff.removed[0].new_blob_sha is None

    assert [c.path for c in diff.modified] == ["a.py"]
    assert diff.modified[0].old_blob_sha == "blobA"
    assert diff.modified[0].new_blob_sha == "blobA2"

    # keep.py is unchanged → appears in no bucket.
    all_paths = {c.path for c in diff.added + diff.removed + diff.modified}
    assert "keep.py" not in all_paths


def test_identical_manifests_yield_empty_diff() -> None:
    m = {"a.py": "blobA", "b.py": "blobB"}
    diff = diff_manifests(m, dict(m))
    assert diff.added == []
    assert diff.removed == []
    assert diff.modified == []
    assert not diff.has_changes


def test_empty_base_is_all_added() -> None:
    head = {"a.py": "blobA", "b.py": "blobB"}
    diff = diff_manifests({}, head)
    assert {c.path for c in diff.added} == {"a.py", "b.py"}
    assert diff.removed == []
    assert diff.modified == []


def test_empty_head_is_all_removed() -> None:
    base = {"a.py": "blobA", "b.py": "blobB"}
    diff = diff_manifests(base, {})
    assert {c.path for c in diff.removed} == {"a.py", "b.py"}
    assert diff.added == []
    assert diff.modified == []


def test_pure_rename_surfaces_as_add_plus_remove_with_matching_blob() -> None:
    # A pure rename: same content (blobX) moves old.py -> new.py. At the manifest
    # level this is remove(old) + add(new) where the blobs match, so the caller
    # (or code-review agent) can pair them by blob_sha equality.
    base = {"old.py": "blobX"}
    head = {"new.py": "blobX"}
    diff = diff_manifests(base, head)

    assert [c.path for c in diff.removed] == ["old.py"]
    assert [c.path for c in diff.added] == ["new.py"]
    assert diff.modified == []
    assert diff.removed[0].old_blob_sha == diff.added[0].new_blob_sha == "blobX"
