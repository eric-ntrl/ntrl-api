"""Enable auto_optimize on all active prompts.

Part of the continuous improvement initiative to achieve 99% quality targets.
This removes the "double-gate" problem where prompts had auto_optimize_enabled=False
by default, causing the optimizer to silently skip them even when improvements
were identified.

Revision ID: 010_enable_auto_optimize_all_prompts
Revises: 009_seed_neutralizer_prompts
Create Date: 2026-01-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '010_enable_auto_optimize_all_prompts'
down_revision: Union[str, Sequence[str], None] = '009_seed_neutralizer_prompts'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable auto_optimize_enabled on all active prompts."""
    connection = op.get_bind()

    # Enable auto-optimize on all active prompts
    result = connection.execute(
        sa.text("""
            UPDATE prompts
            SET auto_optimize_enabled = true,
                updated_at = NOW()
            WHERE is_active = true
        """)
    )
    print(f"  Enabled auto_optimize on {result.rowcount} prompts")


def downgrade() -> None:
    """Revert auto_optimize_enabled to false on prompts that were previously false.

    Note: This is a best-effort rollback. We can't know which prompts were
    previously disabled, so we only disable the article_system_prompt which
    was the one intentionally disabled in migration 009.
    """
    connection = op.get_bind()

    # Only disable article_system_prompt (was intentionally disabled)
    connection.execute(
        sa.text("""
            UPDATE prompts
            SET auto_optimize_enabled = false,
                updated_at = NOW()
            WHERE name = 'article_system_prompt' AND model IS NULL
        """)
    )
    print("  Disabled auto_optimize on article_system_prompt")
