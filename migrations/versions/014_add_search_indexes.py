"""Add full-text search support to stories_neutralized.

Implements server-side search with PostgreSQL full-text search:
- Add tsvector column `search_vector` as a generated column
- Create GIN index for fast full-text search queries
- Weights: A=feed_title, B=feed_summary, C=detail_brief

Note: Using GENERATED ALWAYS AS (stored) for the tsvector column
allows automatic updates when source columns change.

Revision ID: 014_add_search_indexes
Revises: 013_add_retention_system
Create Date: 2026-02-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '014_add_search_indexes'
down_revision: Union[str, Sequence[str], None] = '013_add_retention_system'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add full-text search column and index."""

    print("  Adding full-text search support to stories_neutralized...")

    # -------------------------------------------------------------------------
    # 1. Add tsvector generated column
    # -------------------------------------------------------------------------
    # PostgreSQL GENERATED ALWAYS AS (stored) creates a column that is
    # automatically maintained when source columns change.
    # Weights: A=feed_title (most important), B=feed_summary, C=detail_brief
    print("  Adding search_vector column (generated tsvector)...")

    op.execute("""
        ALTER TABLE stories_neutralized
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(feed_title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(feed_summary, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(detail_brief, '')), 'C')
        ) STORED
    """)

    print("  Created search_vector column")

    # -------------------------------------------------------------------------
    # 2. Create GIN index for fast full-text search
    # -------------------------------------------------------------------------
    print("  Creating GIN index on search_vector...")

    op.execute("""
        CREATE INDEX ix_stories_neutralized_search
        ON stories_neutralized USING GIN (search_vector)
    """)

    print("  Created GIN index ix_stories_neutralized_search")

    # -------------------------------------------------------------------------
    # 3. Add index on feed_category for facet queries
    # -------------------------------------------------------------------------
    # This index helps with efficient aggregation of category facets
    # The stories_raw table already has this index, but we need it on
    # the joined query path as well
    print("  Migration complete!")


def downgrade() -> None:
    """Remove full-text search column and index."""

    print("  Removing full-text search support from stories_neutralized...")

    # Drop in reverse order
    print("  Dropping GIN index...")
    op.execute("DROP INDEX IF EXISTS ix_stories_neutralized_search")

    print("  Dropping search_vector column...")
    op.drop_column('stories_neutralized', 'search_vector')

    print("  Downgrade complete!")
