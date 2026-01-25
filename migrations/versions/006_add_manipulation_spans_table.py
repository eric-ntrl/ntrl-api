"""Add manipulation_spans table for NTRL Filter v2

Revision ID: 006_add_manipulation_spans
Revises: 005_article_neutralization_v1
Create Date: 2026-01-24

This migration adds the manipulation_spans table to support the NTRL Filter v2
architecture with its 80+ type canonical taxonomy. Each span represents a
detected manipulation instance with:
- Full taxonomy binding (type_id_primary + secondary)
- Precise location (segment, span_start, span_end)
- Scoring (confidence, severity, severity_weighted)
- Action taken (remove/replace/rewrite/annotate/preserve)
- Audit trail (detector_source, exemptions_applied)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '006_add_manipulation_spans'
down_revision = '005_article_neutralization_v1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the manipulation_spans table
    op.create_table(
        'manipulation_spans',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('story_neutralized_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('stories_neutralized.id'), nullable=False),

        # Taxonomy binding
        sa.Column('type_id_primary', sa.String(10), nullable=False),
        sa.Column('type_ids_secondary', postgresql.ARRAY(sa.String), default=[]),

        # Location in original text
        sa.Column('segment', sa.String(20), nullable=False),
        sa.Column('span_start', sa.Integer, nullable=False),
        sa.Column('span_end', sa.Integer, nullable=False),
        sa.Column('original_text', sa.Text, nullable=False),

        # Scoring
        sa.Column('confidence', sa.Float, nullable=False),
        sa.Column('severity', sa.Integer, nullable=False),
        sa.Column('severity_weighted', sa.Float, nullable=True),

        # Decision
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('rewritten_text', sa.Text, nullable=True),
        sa.Column('rationale', sa.Text, nullable=True),

        # Audit / Provenance
        sa.Column('detector_source', sa.String(20), nullable=False),
        sa.Column('exemptions_applied', postgresql.ARRAY(sa.String), default=[]),
        sa.Column('rewrite_template_id', sa.String(64), nullable=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime, nullable=False,
                  server_default=sa.func.now()),
    )

    # Create indexes for common queries
    op.create_index('ix_manipulation_spans_story', 'manipulation_spans',
                    ['story_neutralized_id'])
    op.create_index('ix_manipulation_spans_type', 'manipulation_spans',
                    ['type_id_primary'])
    op.create_index('ix_manipulation_spans_segment', 'manipulation_spans',
                    ['segment'])
    op.create_index('ix_manipulation_spans_severity', 'manipulation_spans',
                    ['severity'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_manipulation_spans_severity', 'manipulation_spans')
    op.drop_index('ix_manipulation_spans_segment', 'manipulation_spans')
    op.drop_index('ix_manipulation_spans_type', 'manipulation_spans')
    op.drop_index('ix_manipulation_spans_story', 'manipulation_spans')

    # Drop the table
    op.drop_table('manipulation_spans')
