"""Version comparison — pure set-algebra over path→blob_sha manifests.

A *manifest* is the snapshot of one indexed version: a mapping of repo-relative
path → git blob OID. Comparing two manifests is the single primitive behind both
incremental re-index (parent vs head) and user-facing version comparison
(master↔dev, dev↔v2.3.5). No git, no LLM — just set operations, so it runs on any
two already-indexed versions and is fully deterministic.

A pure rename (same content moved to a new path) surfaces as remove(old) +
add(new) whose blob OIDs are equal; callers that care can pair them by blob_sha.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

Manifest = dict[str, str]  # path -> blob_sha


class FileChange(BaseModel, frozen=True):
    """One path that differs between two versions."""

    path: str
    status: str  # "added" | "removed" | "modified"
    old_blob_sha: str | None = None
    new_blob_sha: str | None = None


class VersionDiff(BaseModel):
    """The partitioned difference between a base and a head manifest."""

    added: list[FileChange] = Field(default_factory=list)
    removed: list[FileChange] = Field(default_factory=list)
    modified: list[FileChange] = Field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.modified)


def diff_manifests(base: Manifest, head: Manifest) -> VersionDiff:
    """Partition head vs base into added / removed / modified file changes.

    added    = paths in head but not base
    removed  = paths in base but not head
    modified = paths in both whose blob_sha differs
    Unchanged paths (present in both with equal blob) appear in no bucket.
    Output lists are sorted by path for deterministic ordering.
    """
    added = [
        FileChange(path=p, status="added", new_blob_sha=head[p])
        for p in head.keys() - base.keys()
    ]
    removed = [
        FileChange(path=p, status="removed", old_blob_sha=base[p])
        for p in base.keys() - head.keys()
    ]
    modified = [
        FileChange(path=p, status="modified", old_blob_sha=base[p], new_blob_sha=head[p])
        for p in base.keys() & head.keys()
        if base[p] != head[p]
    ]
    return VersionDiff(
        added=sorted(added, key=lambda c: c.path),
        removed=sorted(removed, key=lambda c: c.path),
        modified=sorted(modified, key=lambda c: c.path),
    )
