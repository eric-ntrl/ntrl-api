"""add classification columns to stories_raw and classify stats to pipeline_run_summaries

Revision ID: 007_add_classification
Revises: b29c9075587e
Create Date: 2026-01-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = '007_add_classification'
down_revision: Union[str, Sequence[str], None] = 'b29c9075587e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add classification columns to stories_raw and classify stats to pipeline_run_summaries."""
    # Classification columns on stories_raw
    op.add_column('stories_raw', sa.Column('domain', sa.String(length=40), nullable=True))
    op.add_column('stories_raw', sa.Column('feed_category', sa.String(length=32), nullable=True))
    op.add_column('stories_raw', sa.Column('classification_tags', JSONB(), nullable=True))
    op.add_column('stories_raw', sa.Column('classification_confidence', sa.Float(), nullable=True))
    op.add_column('stories_raw', sa.Column('classification_model', sa.String(length=64), nullable=True))
    op.add_column('stories_raw', sa.Column('classification_method', sa.String(length=20), nullable=True))
    op.add_column('stories_raw', sa.Column('classified_at', sa.DateTime(timezone=True), nullable=True))

    # Indexes for classification queries
    op.create_index('ix_stories_raw_domain', 'stories_raw', ['domain'])
    op.create_index('ix_stories_raw_feed_category', 'stories_raw', ['feed_category'])
    op.create_index('ix_stories_raw_classified_at', 'stories_raw', ['classified_at'])
    op.create_index('ix_stories_raw_classification_method', 'stories_raw', ['classification_method'])

    # Classify stats on pipeline_run_summaries
    op.add_column('pipeline_run_summaries', sa.Column('classify_total', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('pipeline_run_summaries', sa.Column('classify_success', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('pipeline_run_summaries', sa.Column('classify_llm', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('pipeline_run_summaries', sa.Column('classify_keyword_fallback', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('pipeline_run_summaries', sa.Column('classify_failed', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Remove classification columns."""
    # Drop classify stats from pipeline_run_summaries
    op.drop_column('pipeline_run_summaries', 'classify_failed')
    op.drop_column('pipeline_run_summaries', 'classify_keyword_fallback')
    op.drop_column('pipeline_run_summaries', 'classify_llm')
    op.drop_column('pipeline_run_summaries', 'classify_success')
    op.drop_column('pipeline_run_summaries', 'classify_total')

    # Drop indexes
    op.drop_index('ix_stories_raw_classification_method', table_name='stories_raw')
    op.drop_index('ix_stories_raw_classified_at', table_name='stories_raw')
    op.drop_index('ix_stories_raw_feed_category', table_name='stories_raw')
    op.drop_index('ix_stories_raw_domain', table_name='stories_raw')

    # Drop classification columns from stories_raw
    op.drop_column('stories_raw', 'classified_at')
    op.drop_column('stories_raw', 'classification_method')
    op.drop_column('stories_raw', 'classification_model')
    op.drop_column('stories_raw', 'classification_confidence')
    op.drop_column('stories_raw', 'classification_tags')
    op.drop_column('stories_raw', 'feed_category')
    op.drop_column('stories_raw', 'domain')
