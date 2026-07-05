"""add repo versioning (content-addressed): repo_versions, version_files,
files.blob_sha, chunks.index, repos.needs_reingest

This migration is additive and safe to apply on a live system: new tables and
nullable/defaulted columns only. It does NOT yet swap the files unique constraint
(uq_files_repo_path -> UNIQUE(repo_id, blob_sha)); that swap lands together with the
content-addressed ingest rewrite, once every file row is guaranteed a blob_sha.

Existing ready repos are flagged needs_reingest=True: their Qdrant points were created
under the legacy path-based point_id scheme and cannot be matched under the new
blob-addressed scheme, so they require a one-time re-ingest.

Revision ID: c1a2b3d4e5f6
Revises: b8e7f1a2c3d4
Create Date: 2026-06-30 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'c1a2b3d4e5f6'
down_revision: str | None = 'b8e7f1a2c3d4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- additive columns on existing tables ---
    op.add_column(
        'repos',
        sa.Column('needs_reingest', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('files', sa.Column('blob_sha', sa.String(length=64), nullable=True))
    op.create_index('ix_files_blob_sha', 'files', ['blob_sha'])
    op.add_column(
        'chunks',
        sa.Column('index', sa.Integer(), nullable=False, server_default='0'),
    )

    # --- repo_versions: one indexed snapshot per commit ---
    op.create_table(
        'repo_versions',
        sa.Column('id', sa.String(length=32), primary_key=True),
        sa.Column(
            'repo_id',
            sa.String(length=32),
            sa.ForeignKey('repos.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('ref_name', sa.String(length=255), nullable=False),
        sa.Column('ref_type', sa.String(length=16), nullable=False, server_default='branch'),
        sa.Column('commit_sha', sa.String(length=64), nullable=False),
        sa.Column(
            'parent_version_id',
            sa.String(length=32),
            sa.ForeignKey('repo_versions.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('file_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('chunk_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('ingested_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('repo_id', 'commit_sha', name='uq_repo_versions_repo_commit'),
    )
    op.create_index('ix_repo_versions_repo_id', 'repo_versions', ['repo_id'])
    op.create_index('ix_repo_versions_repo_ref', 'repo_versions', ['repo_id', 'ref_name'])

    # --- version_files: the path->blob manifest (FK RESTRICT = refcount) ---
    op.create_table(
        'version_files',
        sa.Column(
            'version_id',
            sa.String(length=32),
            sa.ForeignKey('repo_versions.id', ondelete='CASCADE'),
            primary_key=True,
        ),
        sa.Column('path', sa.String(length=1024), primary_key=True),
        sa.Column(
            'file_id',
            sa.String(length=32),
            sa.ForeignKey('files.id', ondelete='RESTRICT'),
            nullable=False,
        ),
    )
    op.create_index('ix_version_files_file', 'version_files', ['file_id'])

    # --- flag legacy repos for one-time re-ingest under the new point_id scheme ---
    op.execute("UPDATE repos SET needs_reingest = true WHERE status = 'ready'")


def downgrade() -> None:
    op.drop_index('ix_version_files_file', table_name='version_files')
    op.drop_table('version_files')
    op.drop_index('ix_repo_versions_repo_ref', table_name='repo_versions')
    op.drop_index('ix_repo_versions_repo_id', table_name='repo_versions')
    op.drop_table('repo_versions')
    op.drop_column('chunks', 'index')
    op.drop_index('ix_files_blob_sha', table_name='files')
    op.drop_column('files', 'blob_sha')
    op.drop_column('repos', 'needs_reingest')
