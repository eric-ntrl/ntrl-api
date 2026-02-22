"""Add is_blocked column to sources table

Revision ID: 020_add_is_blocked
Revises: 019_add_homepage_url_cols
Create Date: 2026-02-21

Adds is_blocked boolean to sources for blocking spam/junk publishers.
Distinct from is_active (RSS fetching) — is_blocked prevents articles
from any ingestion path from appearing in the brief.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "020_add_is_blocked"
down_revision: str = "019_add_homepage_url_cols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("sources", "is_blocked")
