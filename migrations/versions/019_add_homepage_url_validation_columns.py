"""Add homepage_url, URL validation, and source_homepage_url columns.

Source.homepage_url: publisher homepage for "Visit Publisher" link.
StoryRaw URL validation: track reachability of original_url during ingestion.
DailyBriefItem.source_homepage_url: denormalized for fast reads.

Revision ID: 019_add_homepage_url_validation_columns
Revises: 018_add_body_truncated_flag
Create Date: 2026-02-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019_add_homepage_url_validation_columns"
down_revision: str | Sequence[str] | None = "018_add_body_truncated_flag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add homepage_url to sources, URL validation to stories_raw, source_homepage_url to daily_brief_items."""
    op.add_column("sources", sa.Column("homepage_url", sa.Text(), nullable=True))
    op.add_column("stories_raw", sa.Column("url_status", sa.String(16), nullable=True))
    op.add_column("stories_raw", sa.Column("url_checked_at", sa.DateTime(), nullable=True))
    op.add_column("stories_raw", sa.Column("url_http_status", sa.Integer(), nullable=True))
    op.add_column("stories_raw", sa.Column("url_final_location", sa.Text(), nullable=True))
    op.add_column("daily_brief_items", sa.Column("source_homepage_url", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove homepage_url, URL validation, and source_homepage_url columns."""
    op.drop_column("daily_brief_items", "source_homepage_url")
    op.drop_column("stories_raw", "url_final_location")
    op.drop_column("stories_raw", "url_http_status")
    op.drop_column("stories_raw", "url_checked_at")
    op.drop_column("stories_raw", "url_status")
    op.drop_column("sources", "homepage_url")
