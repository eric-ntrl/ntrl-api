"""Add pipeline_jobs table for async pipeline execution.

Part of the async pipeline architecture redesign. The pipeline_jobs table
tracks background pipeline jobs that are started via the /scheduled-run-async
endpoint and execute without blocking the HTTP request.

Revision ID: 012_add_pipeline_jobs
Revises: 011_add_multi_pass_prompts
Create Date: 2026-01-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '012_add_pipeline_jobs'
down_revision: Union[str, Sequence[str], None] = '011_add_multi_pass_prompts'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create pipeline_jobs table."""
    op.create_table(
        'pipeline_jobs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('trace_id', sa.String(length=36), nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('current_stage', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('stage_progress', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('errors', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('pipeline_run_summary_id', sa.UUID(), nullable=True),
        sa.Column('cancel_requested', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['pipeline_run_summary_id'], ['pipeline_run_summaries.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_pipeline_jobs_trace_id', 'pipeline_jobs', ['trace_id'], unique=True)
    op.create_index('ix_pipeline_jobs_created_at', 'pipeline_jobs', ['created_at'], unique=False)
    op.create_index('ix_pipeline_jobs_status', 'pipeline_jobs', ['status'], unique=False)

    print("  Created pipeline_jobs table with indexes")


def downgrade() -> None:
    """Drop pipeline_jobs table."""
    op.drop_index('ix_pipeline_jobs_status', table_name='pipeline_jobs')
    op.drop_index('ix_pipeline_jobs_created_at', table_name='pipeline_jobs')
    op.drop_index('ix_pipeline_jobs_trace_id', table_name='pipeline_jobs')
    op.drop_table('pipeline_jobs')

    print("  Dropped pipeline_jobs table")
