"""NTRL Phase 1 Schema

Revision ID: 001_ntrl_phase1
Revises: 4eb5c6286d76
Create Date: 2024-01-06

This migration replaces the old schema with the new NTRL Phase 1 POC schema.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_ntrl_phase1'
down_revision = '4eb5c6286d76'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old tables (in correct order for foreign keys)
    op.drop_table('cluster_articles', if_exists=True)
    op.drop_table('article_clusters', if_exists=True)
    op.drop_table('pipeline_runs', if_exists=True)
    op.drop_table('article_summaries', if_exists=True)
    op.drop_table('articles_raw', if_exists=True)
    op.drop_table('system_prompts', if_exists=True)
    op.drop_table('sources', if_exists=True)

    # Create new sources table
    op.create_table(
        'sources',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(64), unique=True, nullable=False),
        sa.Column('rss_url', sa.Text, nullable=False),
        sa.Column('is_active', sa.Boolean, default=True, nullable=False),
        sa.Column('default_section', sa.String(32), nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=True),
    )

    # Create stories_raw table
    op.create_table(
        'stories_raw',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sources.id'), nullable=False),
        sa.Column('original_url', sa.Text, nullable=False),
        sa.Column('original_title', sa.Text, nullable=False),
        sa.Column('original_description', sa.Text, nullable=True),
        sa.Column('original_body', sa.Text, nullable=True),
        sa.Column('original_author', sa.String(255), nullable=True),
        sa.Column('url_hash', sa.String(64), nullable=False),
        sa.Column('title_hash', sa.String(64), nullable=False),
        sa.Column('published_at', sa.DateTime, nullable=False),
        sa.Column('ingested_at', sa.DateTime, nullable=False),
        sa.Column('section', sa.String(32), nullable=True),
        sa.Column('is_duplicate', sa.Boolean, default=False, nullable=False),
        sa.Column('duplicate_of_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('stories_raw.id'), nullable=True),
        sa.Column('raw_payload', postgresql.JSONB, nullable=True),
    )
    op.create_index('ix_stories_raw_url_hash', 'stories_raw', ['url_hash'])
    op.create_index('ix_stories_raw_title_hash', 'stories_raw', ['title_hash'])
    op.create_index('ix_stories_raw_published_at', 'stories_raw', ['published_at'])
    op.create_index('ix_stories_raw_section', 'stories_raw', ['section'])
    op.create_index('ix_stories_raw_ingested_at', 'stories_raw', ['ingested_at'])

    # Create stories_neutralized table
    op.create_table(
        'stories_neutralized',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('story_raw_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('stories_raw.id'), nullable=False),
        sa.Column('version', sa.Integer, default=1, nullable=False),
        sa.Column('is_current', sa.Boolean, default=True, nullable=False),
        sa.Column('neutral_headline', sa.Text, nullable=False),
        sa.Column('neutral_summary', sa.Text, nullable=False),
        sa.Column('what_happened', sa.Text, nullable=True),
        sa.Column('why_it_matters', sa.Text, nullable=True),
        sa.Column('what_is_known', sa.Text, nullable=True),
        sa.Column('what_is_uncertain', sa.Text, nullable=True),
        sa.Column('disclosure', sa.String(255), default='Manipulative language removed.', nullable=False),
        sa.Column('has_manipulative_content', sa.Boolean, default=False, nullable=False),
        sa.Column('model_name', sa.String(128), nullable=True),
        sa.Column('prompt_version', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.UniqueConstraint('story_raw_id', 'version', name='uq_story_version'),
    )
    op.create_index('ix_stories_neutralized_is_current', 'stories_neutralized', ['is_current'])

    # Create transparency_spans table
    op.create_table(
        'transparency_spans',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('story_neutralized_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('stories_neutralized.id'), nullable=False),
        sa.Column('field', sa.String(32), nullable=False),
        sa.Column('start_char', sa.Integer, nullable=False),
        sa.Column('end_char', sa.Integer, nullable=False),
        sa.Column('original_text', sa.Text, nullable=False),
        sa.Column('action', sa.String(16), nullable=False),
        sa.Column('reason', sa.String(32), nullable=False),
        sa.Column('replacement_text', sa.Text, nullable=True),
    )
    op.create_index('ix_transparency_spans_story', 'transparency_spans', ['story_neutralized_id'])

    # Create daily_briefs table
    op.create_table(
        'daily_briefs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('brief_date', sa.DateTime, nullable=False),
        sa.Column('version', sa.Integer, default=1, nullable=False),
        sa.Column('total_stories', sa.Integer, default=0, nullable=False),
        sa.Column('cutoff_time', sa.DateTime, nullable=False),
        sa.Column('is_current', sa.Boolean, default=True, nullable=False),
        sa.Column('is_empty', sa.Boolean, default=False, nullable=False),
        sa.Column('empty_reason', sa.String(255), nullable=True),
        sa.Column('assembled_at', sa.DateTime, nullable=False),
        sa.Column('assembly_duration_ms', sa.Integer, nullable=True),
    )
    op.create_index('ix_daily_briefs_date', 'daily_briefs', ['brief_date'])
    op.create_index('ix_daily_briefs_is_current', 'daily_briefs', ['is_current'])

    # Create daily_brief_items table
    op.create_table(
        'daily_brief_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('brief_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('daily_briefs.id'), nullable=False),
        sa.Column('story_neutralized_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('stories_neutralized.id'), nullable=False),
        sa.Column('section', sa.String(32), nullable=False),
        sa.Column('section_order', sa.Integer, nullable=False),
        sa.Column('position', sa.Integer, nullable=False),
        sa.Column('neutral_headline', sa.Text, nullable=False),
        sa.Column('neutral_summary', sa.Text, nullable=False),
        sa.Column('source_name', sa.String(255), nullable=False),
        sa.Column('original_url', sa.Text, nullable=False),
        sa.Column('published_at', sa.DateTime, nullable=False),
        sa.Column('has_manipulative_content', sa.Boolean, default=False, nullable=False),
    )
    op.create_index('ix_brief_items_brief_section', 'daily_brief_items', ['brief_id', 'section'])

    # Create pipeline_logs table
    op.create_table(
        'pipeline_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('stage', sa.String(32), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('story_raw_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('stories_raw.id'), nullable=True),
        sa.Column('brief_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('daily_briefs.id'), nullable=True),
        sa.Column('started_at', sa.DateTime, nullable=False),
        sa.Column('finished_at', sa.DateTime, nullable=True),
        sa.Column('duration_ms', sa.Integer, nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('metadata', postgresql.JSONB, nullable=True),
    )
    op.create_index('ix_pipeline_logs_stage', 'pipeline_logs', ['stage'])
    op.create_index('ix_pipeline_logs_started_at', 'pipeline_logs', ['started_at'])


def downgrade() -> None:
    # Drop new tables
    op.drop_table('pipeline_logs')
    op.drop_table('daily_brief_items')
    op.drop_table('daily_briefs')
    op.drop_table('transparency_spans')
    op.drop_table('stories_neutralized')
    op.drop_table('stories_raw')
    op.drop_table('sources')
