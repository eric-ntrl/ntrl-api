"""Add body_is_truncated flag to stories_raw.

Flags articles where the API source (Perigon) truncated the body
and web scraping failed to recover the full content.

Revision ID: 018_add_body_truncated_flag
Revises: 017_add_quality_gate
Create Date: 2026-02-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '018_add_body_truncated_flag'
down_revision: Union[str, Sequence[str], None] = '017_add_quality_gate'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add body_is_truncated column to stories_raw."""
    op.add_column(
        'stories_raw',
        sa.Column('body_is_truncated', sa.Boolean(),
                  server_default='false', nullable=False),
    )


def downgrade() -> None:
    """Remove body_is_truncated column."""
    op.drop_column('stories_raw', 'body_is_truncated')
