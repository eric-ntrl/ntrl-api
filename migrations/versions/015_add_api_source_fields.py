"""Add source_type and api_source_id fields to stories_raw.

Supports multi-source ingestion from RSS, Perigon, and NewsData.io APIs.

Changes:
- Add source_type column (default 'rss' for existing records)
- Add api_source_id column for external article IDs
- Add index on source_type for efficient filtering

Revision ID: 015_add_api_source_fields
Revises: 014_add_search_indexes
Create Date: 2026-02-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '015_add_api_source_fields'
down_revision: Union[str, Sequence[str], None] = '014_add_search_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add source tracking columns to stories_raw."""

    print("  Adding source_type column to stories_raw...")
    op.add_column(
        'stories_raw',
        sa.Column(
            'source_type',
            sa.String(length=32),
            nullable=False,
            server_default='rss'
        )
    )

    print("  Adding api_source_id column to stories_raw...")
    op.add_column(
        'stories_raw',
        sa.Column(
            'api_source_id',
            sa.String(length=255),
            nullable=True
        )
    )

    print("  Creating index on source_type...")
    op.create_index(
        'ix_stories_raw_source_type',
        'stories_raw',
        ['source_type'],
        unique=False
    )

    print("  Migration complete!")


def downgrade() -> None:
    """Remove source tracking columns from stories_raw."""

    print("  Dropping source_type index...")
    op.drop_index('ix_stories_raw_source_type', table_name='stories_raw')

    print("  Dropping api_source_id column...")
    op.drop_column('stories_raw', 'api_source_id')

    print("  Dropping source_type column...")
    op.drop_column('stories_raw', 'source_type')

    print("  Downgrade complete!")
