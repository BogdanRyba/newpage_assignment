"""swap files uniqueness to content-addressed: drop uq_files_repo_path, add
UNIQUE(repo_id, blob_sha)

This is the constraint half of content-addressing, split from the additive migration A
so A could land safely on a live system first. Under versioning a single path can hold
different blobs across versions (a changed file), so (repo_id, path) can no longer be
unique; instead one row exists per distinct (repo, blob) and is shared across the
versions/paths that contain that content. Legacy rows have blob_sha NULL (NULLs are
distinct in Postgres uniqueness) and belong to repos flagged needs_reingest.

Revision ID: d2b3c4d5e6f7
Revises: c1a2b3d4e5f6
Create Date: 2026-06-30 00:00:01.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = 'd2b3c4d5e6f7'
down_revision: str | None = 'c1a2b3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint('uq_files_repo_path', 'files', type_='unique')
    op.create_unique_constraint('uq_files_repo_blob', 'files', ['repo_id', 'blob_sha'])


def downgrade() -> None:
    op.drop_constraint('uq_files_repo_blob', 'files', type_='unique')
    op.create_unique_constraint('uq_files_repo_path', 'files', ['repo_id', 'path'])
