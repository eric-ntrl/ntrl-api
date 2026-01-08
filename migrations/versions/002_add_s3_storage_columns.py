"""Add S3 storage columns to stories_raw

Revision ID: 002_s3_storage
Revises: 001_ntrl_phase1
Create Date: 2024-01-06

This migration:
- Removes original_body and raw_payload columns from stories_raw
- Adds S3 reference columns for raw content storage
- Raw article bodies are now stored in S3, not Postgres
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '002_s3_storage'
down_revision = '001_ntrl_phase1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add S3 storage columns
    op.add_column('stories_raw', sa.Column('raw_content_uri', sa.String(512), nullable=True))
    op.add_column('stories_raw', sa.Column('raw_content_hash', sa.String(64), nullable=True))
    op.add_column('stories_raw', sa.Column('raw_content_type', sa.String(64), nullable=True))
    op.add_column('stories_raw', sa.Column('raw_content_encoding', sa.String(16), nullable=True))
    op.add_column('stories_raw', sa.Column('raw_content_size', sa.Integer, nullable=True))
    op.add_column('stories_raw', sa.Column('raw_content_available', sa.Boolean, server_default='true', nullable=False))
    op.add_column('stories_raw', sa.Column('raw_content_expired_at', sa.DateTime, nullable=True))
    op.add_column('stories_raw', sa.Column('feed_entry_id', sa.String(512), nullable=True))

    # Create index for content availability queries
    op.create_index('ix_stories_raw_content_available', 'stories_raw', ['raw_content_available'])

    # Drop old columns that stored content directly in Postgres
    op.drop_column('stories_raw', 'original_body')
    op.drop_column('stories_raw', 'raw_payload')


def downgrade() -> None:
    # Restore old columns
    op.add_column('stories_raw', sa.Column('original_body', sa.Text, nullable=True))
    op.add_column('stories_raw', sa.Column('raw_payload', sa.JSON, nullable=True))

    # Drop S3 columns
    op.drop_index('ix_stories_raw_content_available', table_name='stories_raw')
    op.drop_column('stories_raw', 'feed_entry_id')
    op.drop_column('stories_raw', 'raw_content_expired_at')
    op.drop_column('stories_raw', 'raw_content_available')
    op.drop_column('stories_raw', 'raw_content_size')
    op.drop_column('stories_raw', 'raw_content_encoding')
    op.drop_column('stories_raw', 'raw_content_type')
    op.drop_column('stories_raw', 'raw_content_hash')
    op.drop_column('stories_raw', 'raw_content_uri')
