"""Add quality control gate columns and indexes.

Adds QC columns to stories_neutralized, QC stats to pipeline_run_summaries,
and backfills articles currently in the active brief with qc_status='passed'.

Changes:
- stories_neutralized: add qc_status, qc_failures (JSONB), qc_checked_at
- stories_neutralized: add index on qc_status
- pipeline_run_summaries: add qc_total, qc_passed, qc_failed
- Backfill: existing articles in current brief get qc_status='passed'

Revision ID: 017_add_quality_gate
Revises: 016_backfill_publisher_sources
Create Date: 2026-02-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = '017_add_quality_gate'
down_revision: Union[str, Sequence[str], None] = '016_backfill_publisher_sources'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add quality control gate columns."""

    # 1. Add QC columns to stories_neutralized
    print("  Adding qc_status column to stories_neutralized...")
    op.add_column(
        'stories_neutralized',
        sa.Column('qc_status', sa.String(length=20), nullable=True)
    )

    print("  Adding qc_failures JSONB column to stories_neutralized...")
    op.add_column(
        'stories_neutralized',
        sa.Column('qc_failures', JSONB, nullable=True)
    )

    print("  Adding qc_checked_at column to stories_neutralized...")
    op.add_column(
        'stories_neutralized',
        sa.Column('qc_checked_at', sa.DateTime(timezone=True), nullable=True)
    )

    print("  Creating index on qc_status...")
    op.create_index(
        'ix_stories_neutralized_qc_status',
        'stories_neutralized',
        ['qc_status'],
        unique=False
    )

    # 2. Add QC stats to pipeline_run_summaries
    print("  Adding qc_total column to pipeline_run_summaries...")
    op.add_column(
        'pipeline_run_summaries',
        sa.Column('qc_total', sa.Integer(), nullable=False, server_default='0')
    )

    print("  Adding qc_passed column to pipeline_run_summaries...")
    op.add_column(
        'pipeline_run_summaries',
        sa.Column('qc_passed', sa.Integer(), nullable=False, server_default='0')
    )

    print("  Adding qc_failed column to pipeline_run_summaries...")
    op.add_column(
        'pipeline_run_summaries',
        sa.Column('qc_failed', sa.Integer(), nullable=False, server_default='0')
    )

    # 3. Backfill: mark articles in current brief as qc_status='passed'
    # This ensures existing articles continue to appear after QC gate is added
    print("  Backfilling qc_status='passed' for articles in current brief...")
    op.execute("""
        UPDATE stories_neutralized
        SET qc_status = 'passed',
            qc_checked_at = NOW()
        WHERE id IN (
            SELECT dbi.story_neutralized_id
            FROM daily_brief_items dbi
            JOIN daily_briefs db ON dbi.brief_id = db.id
            WHERE db.is_current = true
        )
    """)

    # Also mark all current neutralized articles with status='success' as passed,
    # since they were implicitly passing the checks that brief_assembly already ran
    print("  Backfilling qc_status='passed' for all current success articles...")
    op.execute("""
        UPDATE stories_neutralized
        SET qc_status = 'passed',
            qc_checked_at = NOW()
        WHERE is_current = true
          AND neutralization_status = 'success'
          AND qc_status IS NULL
    """)

    print("  Migration complete!")


def downgrade() -> None:
    """Remove quality control gate columns."""

    print("  Dropping qc_status index...")
    op.drop_index('ix_stories_neutralized_qc_status', table_name='stories_neutralized')

    print("  Dropping qc_checked_at column...")
    op.drop_column('stories_neutralized', 'qc_checked_at')

    print("  Dropping qc_failures column...")
    op.drop_column('stories_neutralized', 'qc_failures')

    print("  Dropping qc_status column...")
    op.drop_column('stories_neutralized', 'qc_status')

    print("  Dropping qc_total column...")
    op.drop_column('pipeline_run_summaries', 'qc_total')

    print("  Dropping qc_passed column...")
    op.drop_column('pipeline_run_summaries', 'qc_passed')

    print("  Dropping qc_failed column...")
    op.drop_column('pipeline_run_summaries', 'qc_failed')

    print("  Downgrade complete!")
