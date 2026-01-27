"""Add index on neutralization_status for brief query filtering.

Revision ID: c7f3a1b2d4e5
Revises: 007_add_classification
Create Date: 2026-01-27 00:00:00.000000
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c7f3a1b2d4e5'
down_revision = '007_add_classification'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        'ix_stories_neutralized_status',
        'stories_neutralized',
        ['neutralization_status'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_stories_neutralized_status', table_name='stories_neutralized')
