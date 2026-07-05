"""add raw bytes column to files (for PDF visual viewer)

Revision ID: b8e7f1a2c3d4
Revises: 5225ada06165
Create Date: 2026-06-28 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'b8e7f1a2c3d4'
down_revision: str | None = '5225ada06165'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('files', sa.Column('raw', sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column('files', 'raw')
