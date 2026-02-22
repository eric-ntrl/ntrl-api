"""Add api_categories column to stories_raw table

Revision ID: 021_add_api_cats
Revises: 020_add_is_blocked
Create Date: 2026-02-22

Stores raw categories from Perigon/NewsData APIs for classification bypass.
When api_categories is populated, the CLASSIFY stage can skip LLM and use
the API-provided categories directly via PERIGON_CATEGORY_MAP.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "021_add_api_cats"
down_revision: str = "020_add_is_blocked"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stories_raw",
        sa.Column("api_categories", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stories_raw", "api_categories")
