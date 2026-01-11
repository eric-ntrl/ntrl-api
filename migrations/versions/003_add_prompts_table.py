"""Add prompts table for hot-reloadable LLM prompts

Revision ID: 003_prompts
Revises: 002_s3_storage
Create Date: 2026-01-10

This migration adds the prompts table for storing LLM prompts in the database.
Allows updating prompts without redeploying the application.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '003_prompts'
down_revision = '002_s3_storage'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'prompts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(64), unique=True, nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('version', sa.Integer, default=1, nullable=False),
        sa.Column('is_active', sa.Boolean, default=True, nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table('prompts')
