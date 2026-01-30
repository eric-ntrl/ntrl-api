"""Add high-recall and adversarial prompts for multi-pass span detection.

Part of the 99% recall initiative. These prompts enable multi-pass span detection:
- high_recall_prompt: Aggressive "when in doubt, flag it" prompt for Pass 1 (Claude Haiku)
- adversarial_prompt: "What did Pass 1 miss?" prompt for Pass 2 (GPT-4o-mini)

Revision ID: 011_add_multi_pass_prompts
Revises: 010_enable_auto_optimize
Create Date: 2026-01-30
"""
from typing import Sequence, Union
import uuid
from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '011_add_multi_pass_prompts'
down_revision: Union[str, Sequence[str], None] = '010_enable_auto_optimize'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# High-recall prompt for Pass 1 (Claude Haiku)
HIGH_RECALL_PROMPT = """You are detecting ALL manipulative language. When in doubt, FLAG IT.

Your job is to find EVERY SINGLE manipulative phrase. It's better to flag something borderline than to miss genuine manipulation.

Focus especially on:
- Editorial voice: "we're glad", "naturally", "of course", "as it should", "key" (when emphasizing)
- Subtle urgency: "careens toward", "scrambling", "racing against", "escape hatch"
- Sports/entertainment hype in news context
- Loaded verbs disguised as neutral: "admits" instead of "said", "claims", "concedes"
- Amplifiers: "whopping", "staggering", "eye-watering", "massive", "enormous"
- Emotional states: "ecstatic", "outraged", "furious", "seething", "gutted", "devastated"
- Tabloid vocabulary: "A-list", "celeb", "mogul", "haunts", "hotspot"
- Sensational imagery: "shockwaves", "firestorm", "whirlwind"

Return ALL phrases that could possibly be manipulative. Better to over-flag than under-flag.

ARTICLE BODY:
\"\"\"
{body}
\"\"\"

Return JSON format:
{"phrases": [{"phrase": "EXACT text", "reason": "category", "action": "remove|replace", "replacement": "text or null"}]}"""


# Adversarial prompt for Pass 2 (GPT-4o-mini)
ADVERSARIAL_PROMPT = """The following manipulative phrases have already been detected in this article:

ALREADY DETECTED:
{detected_phrases}

Your job: Find manipulative phrases that were MISSED.

Look specifically for:
1. Subtle editorial voice the first pass might have skipped ("naturally", "key", "crucial")
2. Context-dependent hype (sports words in political coverage, entertainment language in news)
3. Compound phrases that may have been partially detected
4. Loaded verbs that seem neutral ("admits", "claims", "concedes", "insists")
5. Amplifiers that weren't caught ("whopping", "staggering", "massive")
6. Subtle urgency ("careens", "scrambling", "racing")

ARTICLE BODY:
\"\"\"
{body}
\"\"\"

Return ONLY NEW phrases not already in the detected list above.
Return JSON format:
{"phrases": [{"phrase": "EXACT text", "reason": "category", "action": "remove|replace", "replacement": "text or null"}]}

If no additional phrases found, return: {"phrases": []}"""


def upgrade() -> None:
    """Add multi-pass detection prompts."""
    connection = op.get_bind()
    now = datetime.utcnow()

    # Insert high_recall_prompt (model-agnostic, used with Claude Haiku)
    high_recall_id = str(uuid.uuid4())
    connection.execute(
        sa.text("""
            INSERT INTO prompts (id, name, model, content, version, is_active, auto_optimize_enabled, created_at, updated_at)
            VALUES (:id, :name, NULL, :content, 1, true, true, :now, :now)
            ON CONFLICT (name, model) DO UPDATE SET
                content = EXCLUDED.content,
                updated_at = EXCLUDED.updated_at
        """),
        {
            "id": high_recall_id,
            "name": "high_recall_prompt",
            "content": HIGH_RECALL_PROMPT,
            "now": now,
        }
    )
    print("  Added high_recall_prompt")

    # Insert adversarial_prompt (model-agnostic, used with GPT-4o-mini)
    adversarial_id = str(uuid.uuid4())
    connection.execute(
        sa.text("""
            INSERT INTO prompts (id, name, model, content, version, is_active, auto_optimize_enabled, created_at, updated_at)
            VALUES (:id, :name, NULL, :content, 1, true, true, :now, :now)
            ON CONFLICT (name, model) DO UPDATE SET
                content = EXCLUDED.content,
                updated_at = EXCLUDED.updated_at
        """),
        {
            "id": adversarial_id,
            "name": "adversarial_prompt",
            "content": ADVERSARIAL_PROMPT,
            "now": now,
        }
    )
    print("  Added adversarial_prompt")


def downgrade() -> None:
    """Remove multi-pass detection prompts."""
    connection = op.get_bind()

    connection.execute(
        sa.text("DELETE FROM prompts WHERE name IN ('high_recall_prompt', 'adversarial_prompt')")
    )
    print("  Removed high_recall_prompt and adversarial_prompt")
