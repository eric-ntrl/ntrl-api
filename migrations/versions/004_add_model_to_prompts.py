"""Add model column to prompts table for per-model prompt tuning

Revision ID: 004_model_prompts
Revises: 003_prompts
Create Date: 2026-01-12

This migration adds a model column to prompts table so prompts can be
tuned per-model (e.g., different prompts for gpt-4o-mini vs gemini-2.0-flash).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '004_model_prompts'
down_revision = '003_prompts'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add model column (nullable for generic/fallback prompts)
    op.add_column('prompts', sa.Column('model', sa.String(64), nullable=True))

    # Drop the old unique constraint on name only
    op.drop_constraint('prompts_name_key', 'prompts', type_='unique')

    # Create new unique constraint on (name, model)
    # Note: NULL values are treated as distinct in PostgreSQL unique constraints,
    # so we need a partial unique index for the NULL case
    op.create_unique_constraint('prompts_name_model_key', 'prompts', ['name', 'model'])

    # Create partial unique index for name where model IS NULL (generic prompts)
    op.execute(
        "CREATE UNIQUE INDEX prompts_name_null_model_idx ON prompts (name) WHERE model IS NULL"
    )

    # Update existing prompts to be tagged with gpt-4o-mini (they were tuned for OpenAI)
    op.execute(
        "UPDATE prompts SET model = 'gpt-4o-mini' WHERE model IS NULL"
    )


def downgrade() -> None:
    # Remove the partial index
    op.execute("DROP INDEX IF EXISTS prompts_name_null_model_idx")

    # Remove the composite unique constraint
    op.drop_constraint('prompts_name_model_key', 'prompts', type_='unique')

    # Restore the original unique constraint on name only
    op.create_unique_constraint('prompts_name_key', 'prompts', ['name'])

    # Drop the model column
    op.drop_column('prompts', 'model')
