"""Add retention system: columns, policies, and lifecycle events.

Implements the 3-tier retention system:
- Tier 1 (Active): 0-7 days, full access
- Tier 2 (Compliance): 7d-12mo, archived content
- Tier 3 (Deleted): >12mo, permanent removal

Changes:
- Add retention columns to stories_raw (soft delete, archive tracking, legal hold)
- Create retention_policies table for configurable retention windows
- Create content_lifecycle_events table for immutable audit trail

Revision ID: 013_add_retention_system
Revises: 012_add_pipeline_jobs
Create Date: 2026-02-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '013_add_retention_system'
down_revision: Union[str, Sequence[str], None] = '012_add_pipeline_jobs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add retention columns and tables."""

    # -------------------------------------------------------------------------
    # 1. Add retention columns to stories_raw
    # -------------------------------------------------------------------------
    print("  Adding retention columns to stories_raw...")

    # Soft delete columns
    op.add_column('stories_raw', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.add_column('stories_raw', sa.Column('deletion_reason', sa.String(length=64), nullable=True))

    # Archive tracking columns
    op.add_column('stories_raw', sa.Column('archived_at', sa.DateTime(), nullable=True))
    op.add_column('stories_raw', sa.Column('archive_status', sa.String(length=20), nullable=True))
    op.add_column('stories_raw', sa.Column('archive_reference', sa.String(length=512), nullable=True))

    # User preservation / legal hold columns
    op.add_column('stories_raw', sa.Column('preserve_until', sa.DateTime(), nullable=True))
    op.add_column('stories_raw', sa.Column('legal_hold', sa.Boolean(), nullable=False, server_default='false'))

    # Create indexes for efficient retention queries
    op.create_index('ix_stories_raw_deleted_at', 'stories_raw', ['deleted_at'], unique=False)
    op.create_index('ix_stories_raw_archived_at', 'stories_raw', ['archived_at'], unique=False)
    op.create_index('ix_stories_raw_legal_hold', 'stories_raw', ['legal_hold'], unique=False)

    print("  Added 7 columns and 3 indexes to stories_raw")

    # -------------------------------------------------------------------------
    # 2. Create retention_policies table
    # -------------------------------------------------------------------------
    print("  Creating retention_policies table...")

    op.create_table(
        'retention_policies',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('active_days', sa.Integer(), nullable=False, server_default='7'),
        sa.Column('compliance_days', sa.Integer(), nullable=False, server_default='365'),
        sa.Column('auto_archive', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('hard_delete_mode', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_retention_policies_name')
    )
    op.create_index('ix_retention_policies_is_active', 'retention_policies', ['is_active'], unique=False)

    print("  Created retention_policies table")

    # -------------------------------------------------------------------------
    # 3. Create content_lifecycle_events table
    # -------------------------------------------------------------------------
    print("  Creating content_lifecycle_events table...")

    op.create_table(
        'content_lifecycle_events',
        sa.Column('id', sa.UUID(), nullable=False),
        # Note: No FK to stories_raw - events persist after story deletion
        sa.Column('story_raw_id', sa.UUID(), nullable=False),
        sa.Column('event_type', sa.String(length=32), nullable=False),
        sa.Column('event_timestamp', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('initiated_by', sa.String(length=64), nullable=False),
        sa.Column('idempotency_key', sa.String(length=128), nullable=True),
        sa.Column('event_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key', name='uq_lifecycle_events_idempotency')
    )
    op.create_index('ix_lifecycle_events_story_raw_id', 'content_lifecycle_events', ['story_raw_id'], unique=False)
    op.create_index('ix_lifecycle_events_event_type', 'content_lifecycle_events', ['event_type'], unique=False)
    op.create_index('ix_lifecycle_events_timestamp', 'content_lifecycle_events', ['event_timestamp'], unique=False)
    op.create_index('ix_lifecycle_events_idempotency', 'content_lifecycle_events', ['idempotency_key'], unique=False)

    print("  Created content_lifecycle_events table with 4 indexes")

    # -------------------------------------------------------------------------
    # 4. Seed default retention policies
    # -------------------------------------------------------------------------
    print("  Seeding default retention policies...")

    # Insert default policies using raw SQL
    op.execute("""
        INSERT INTO retention_policies (id, name, active_days, compliance_days, auto_archive, hard_delete_mode, is_active, created_at)
        VALUES
            (gen_random_uuid(), 'development', 7, 30, false, true, false, NOW()),
            (gen_random_uuid(), 'production', 7, 365, true, false, false, NOW())
    """)

    print("  Created 'development' and 'production' retention policies")
    print("  Migration complete!")


def downgrade() -> None:
    """Remove retention columns and tables."""

    print("  Dropping content_lifecycle_events table...")
    op.drop_index('ix_lifecycle_events_idempotency', table_name='content_lifecycle_events')
    op.drop_index('ix_lifecycle_events_timestamp', table_name='content_lifecycle_events')
    op.drop_index('ix_lifecycle_events_event_type', table_name='content_lifecycle_events')
    op.drop_index('ix_lifecycle_events_story_raw_id', table_name='content_lifecycle_events')
    op.drop_table('content_lifecycle_events')

    print("  Dropping retention_policies table...")
    op.drop_index('ix_retention_policies_is_active', table_name='retention_policies')
    op.drop_table('retention_policies')

    print("  Removing retention columns from stories_raw...")
    op.drop_index('ix_stories_raw_legal_hold', table_name='stories_raw')
    op.drop_index('ix_stories_raw_archived_at', table_name='stories_raw')
    op.drop_index('ix_stories_raw_deleted_at', table_name='stories_raw')

    op.drop_column('stories_raw', 'legal_hold')
    op.drop_column('stories_raw', 'preserve_until')
    op.drop_column('stories_raw', 'archive_reference')
    op.drop_column('stories_raw', 'archive_status')
    op.drop_column('stories_raw', 'archived_at')
    op.drop_column('stories_raw', 'deletion_reason')
    op.drop_column('stories_raw', 'deleted_at')

    print("  Downgrade complete!")
