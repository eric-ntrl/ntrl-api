"""Article Neutralization v1 schema changes

Revision ID: 005_article_neutralization_v1
Revises: 004_model_prompts
Create Date: 2025-01-12

This migration updates the schema to support all 6 article outputs per the
Article Neutralization v1.0 PRD:
- Renames neutral_headline/neutral_summary to feed_title/feed_summary
- Adds detail_title, detail_brief, detail_full columns
- Removes deprecated structured fields (what_happened, etc.)
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '005_article_neutralization_v1'
down_revision = '004_model_prompts'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- stories_neutralized table ---

    # Rename existing columns to new naming convention
    op.alter_column('stories_neutralized', 'neutral_headline',
                    new_column_name='feed_title')
    op.alter_column('stories_neutralized', 'neutral_summary',
                    new_column_name='feed_summary')

    # Add new detail columns (nullable for gradual rollout)
    op.add_column('stories_neutralized',
                  sa.Column('detail_title', sa.Text(), nullable=True))
    op.add_column('stories_neutralized',
                  sa.Column('detail_brief', sa.Text(), nullable=True))
    op.add_column('stories_neutralized',
                  sa.Column('detail_full', sa.Text(), nullable=True))

    # Remove deprecated structured fields
    op.drop_column('stories_neutralized', 'what_happened')
    op.drop_column('stories_neutralized', 'why_it_matters')
    op.drop_column('stories_neutralized', 'what_is_known')
    op.drop_column('stories_neutralized', 'what_is_uncertain')

    # --- daily_brief_items table ---

    # Rename denormalized columns to match new naming
    op.alter_column('daily_brief_items', 'neutral_headline',
                    new_column_name='feed_title')
    op.alter_column('daily_brief_items', 'neutral_summary',
                    new_column_name='feed_summary')


def downgrade() -> None:
    # --- daily_brief_items table ---

    # Restore old column names
    op.alter_column('daily_brief_items', 'feed_title',
                    new_column_name='neutral_headline')
    op.alter_column('daily_brief_items', 'feed_summary',
                    new_column_name='neutral_summary')

    # --- stories_neutralized table ---

    # Re-add deprecated structured fields
    op.add_column('stories_neutralized',
                  sa.Column('what_is_uncertain', sa.Text(), nullable=True))
    op.add_column('stories_neutralized',
                  sa.Column('what_is_known', sa.Text(), nullable=True))
    op.add_column('stories_neutralized',
                  sa.Column('why_it_matters', sa.Text(), nullable=True))
    op.add_column('stories_neutralized',
                  sa.Column('what_happened', sa.Text(), nullable=True))

    # Remove new detail columns
    op.drop_column('stories_neutralized', 'detail_full')
    op.drop_column('stories_neutralized', 'detail_brief')
    op.drop_column('stories_neutralized', 'detail_title')

    # Restore old column names
    op.alter_column('stories_neutralized', 'feed_summary',
                    new_column_name='neutral_summary')
    op.alter_column('stories_neutralized', 'feed_title',
                    new_column_name='neutral_headline')
