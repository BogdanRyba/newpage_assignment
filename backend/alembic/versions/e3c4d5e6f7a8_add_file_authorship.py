"""add per-file authorship columns (who/when last changed a file + recent history)

Captured at ingest from git for changed files. Powers the dev-search agent ("who wrote
this code?"). Author names / commit subjects are untrusted repo data — sanitized before
they reach any prompt.

Revision ID: e3c4d5e6f7a8
Revises: d2b3c4d5e6f7
Create Date: 2026-06-30 00:00:02.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'e3c4d5e6f7a8'
down_revision: str | None = 'd2b3c4d5e6f7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('files', sa.Column('last_author', sa.String(length=255), nullable=True))
    op.add_column('files', sa.Column('last_author_email', sa.String(length=255), nullable=True))
    op.add_column('files', sa.Column('last_commit_sha', sa.String(length=64), nullable=True))
    op.add_column('files', sa.Column('last_commit_at', sa.String(length=40), nullable=True))
    op.add_column('files', sa.Column('commit_history', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('files', 'commit_history')
    op.drop_column('files', 'last_commit_at')
    op.drop_column('files', 'last_commit_sha')
    op.drop_column('files', 'last_author_email')
    op.drop_column('files', 'last_author')
