"""Add prompt optimization and evaluation tables.

Creates:
- prompt_versions: Full version history for prompts
- evaluation_runs: Per-pipeline evaluation results
- article_evaluations: Per-article evaluation details

Updates prompts table with:
- current_version_id, auto_optimize_enabled, min_score_threshold, rollback_threshold

Revision ID: 008_add_prompt_optimization
Revises: c7f3a1b2d4e5
Create Date: 2026-01-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision: str = '008_add_prompt_optimization'
down_revision: Union[str, Sequence[str], None] = 'c7f3a1b2d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create prompt optimization and evaluation tables."""

    # 1. Create prompt_versions table
    op.create_table(
        'prompt_versions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('prompt_id', UUID(as_uuid=True), sa.ForeignKey('prompts.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('change_reason', sa.Text(), nullable=True),
        sa.Column('change_source', sa.String(32), nullable=False),  # manual, auto_optimize, rollback
        sa.Column('parent_version_id', UUID(as_uuid=True), sa.ForeignKey('prompt_versions.id'), nullable=True),
        sa.Column('avg_score_at_creation', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('prompt_id', 'version', name='uq_prompt_version'),
    )
    op.create_index('ix_prompt_versions_prompt_id', 'prompt_versions', ['prompt_id'])
    op.create_index('ix_prompt_versions_created_at', 'prompt_versions', ['created_at'])

    # 2. Create evaluation_runs table
    op.create_table(
        'evaluation_runs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('pipeline_run_id', UUID(as_uuid=True), sa.ForeignKey('pipeline_run_summaries.id'), nullable=False),
        sa.Column('teacher_model', sa.String(64), nullable=False),
        sa.Column('sample_size', sa.Integer(), nullable=False),
        # Aggregate results
        sa.Column('classification_accuracy', sa.Float(), nullable=True),
        sa.Column('avg_neutralization_score', sa.Float(), nullable=True),
        sa.Column('avg_span_precision', sa.Float(), nullable=True),
        sa.Column('avg_span_recall', sa.Float(), nullable=True),
        sa.Column('overall_quality_score', sa.Float(), nullable=True),
        # Teacher recommendations
        sa.Column('recommendations', JSONB(), nullable=True),
        # Actions taken
        sa.Column('prompts_updated', JSONB(), nullable=True),
        sa.Column('rollback_triggered', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('rollback_details', JSONB(), nullable=True),
        # Cost tracking
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('estimated_cost_usd', sa.Float(), nullable=False, server_default='0'),
        # Timing
        sa.Column('started_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        # Status
        sa.Column('status', sa.String(20), nullable=False, server_default='running'),
    )
    op.create_index('ix_evaluation_runs_pipeline_run_id', 'evaluation_runs', ['pipeline_run_id'])
    op.create_index('ix_evaluation_runs_started_at', 'evaluation_runs', ['started_at'])
    op.create_index('ix_evaluation_runs_status', 'evaluation_runs', ['status'])

    # 3. Create article_evaluations table
    op.create_table(
        'article_evaluations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('evaluation_run_id', UUID(as_uuid=True), sa.ForeignKey('evaluation_runs.id'), nullable=False),
        sa.Column('story_raw_id', UUID(as_uuid=True), sa.ForeignKey('stories_raw.id'), nullable=False),
        # Classification evaluation
        sa.Column('classification_correct', sa.Boolean(), nullable=True),
        sa.Column('expected_domain', sa.String(40), nullable=True),
        sa.Column('expected_feed_category', sa.String(32), nullable=True),
        sa.Column('classification_feedback', sa.Text(), nullable=True),
        # Neutralization evaluation
        sa.Column('neutralization_score', sa.Float(), nullable=True),
        sa.Column('meaning_preservation_score', sa.Float(), nullable=True),
        sa.Column('neutrality_score', sa.Float(), nullable=True),
        sa.Column('grammar_score', sa.Float(), nullable=True),
        sa.Column('rule_violations', JSONB(), nullable=True),
        sa.Column('neutralization_feedback', sa.Text(), nullable=True),
        # Span evaluation
        sa.Column('span_precision', sa.Float(), nullable=True),
        sa.Column('span_recall', sa.Float(), nullable=True),
        sa.Column('missed_manipulations', JSONB(), nullable=True),
        sa.Column('false_positives', JSONB(), nullable=True),
        sa.Column('span_feedback', sa.Text(), nullable=True),
        # Prompt improvement suggestions
        sa.Column('classification_prompt_suggestion', sa.Text(), nullable=True),
        sa.Column('neutralization_prompt_suggestion', sa.Text(), nullable=True),
        sa.Column('span_prompt_suggestion', sa.Text(), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_article_evaluations_evaluation_run_id', 'article_evaluations', ['evaluation_run_id'])
    op.create_index('ix_article_evaluations_story_raw_id', 'article_evaluations', ['story_raw_id'])

    # 4. Add new columns to prompts table
    op.add_column('prompts', sa.Column('current_version_id', UUID(as_uuid=True), nullable=True))
    op.add_column('prompts', sa.Column('auto_optimize_enabled', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('prompts', sa.Column('min_score_threshold', sa.Float(), nullable=False, server_default='7.0'))
    op.add_column('prompts', sa.Column('rollback_threshold', sa.Float(), nullable=False, server_default='0.5'))

    # 5. Insert initial classification prompts if they don't exist
    # Using raw SQL for data migration
    connection = op.get_bind()

    # Check if classification prompts already exist
    result = connection.execute(
        sa.text("SELECT COUNT(*) FROM prompts WHERE name = 'classification_system_prompt'")
    )
    if result.scalar() == 0:
        # Insert classification system prompt
        connection.execute(
            sa.text("""
                INSERT INTO prompts (id, name, model, content, version, is_active, created_at, updated_at, auto_optimize_enabled, min_score_threshold, rollback_threshold)
                VALUES (
                    gen_random_uuid(),
                    'classification_system_prompt',
                    NULL,
                    :content,
                    1,
                    true,
                    NOW(),
                    NOW(),
                    false,
                    7.0,
                    0.5
                )
            """),
            {
                "content": """You are a news article classifier. Classify articles into exactly one domain and detect geographic scope.

DOMAINS (pick exactly one):
- global_affairs: International relations, diplomacy, foreign policy, UN/NATO, treaties, summits
- governance_politics: Government, legislation, elections, political parties, policy, regulation
- law_justice: Courts, legal rulings, lawsuits, constitutional issues, civil rights law
- security_defense: Military, defense, intelligence, national security, cybersecurity threats
- crime_public_safety: Crime, policing, public safety, arrests, investigations, violence
- economy_macroeconomics: GDP, inflation, interest rates, monetary/fiscal policy, economic indicators
- finance_markets: Stock markets, trading, banking, investments, cryptocurrency, IPOs
- business_industry: Companies, corporate news, mergers, startups, revenue, products
- labor_demographics: Workers, unions, wages, employment, immigration, population trends
- infrastructure_systems: Transportation, roads, bridges, utilities, broadband, housing
- energy: Oil, gas, renewable energy, power grid, electric vehicles, energy policy
- environment_climate: Climate change, pollution, conservation, wildlife, sustainability
- science_research: Scientific discoveries, space, physics, biology, research studies
- health_medicine: Medical, diseases, treatments, public health, mental health, pharmaceuticals
- technology: AI, software, hardware, internet, tech companies, innovation
- media_information: Journalism, social media, misinformation, content moderation, press
- sports_competition: Professional/amateur sports, competitions, athletes, leagues
- society_culture: Social issues, education, arts, religion, cultural movements
- lifestyle_personal: Celebrity, entertainment, food, travel, fashion, personal finance
- incidents_disasters: Natural disasters, accidents, emergencies, mass incidents, weather events

GEOGRAPHY (pick exactly one):
- international: Non-US or multi-country focus
- us: US national scope
- local: City/county/neighborhood scope within US
- mixed: Both US and international elements

Respond with valid JSON only. No markdown, no explanation.

Output schema:
{
  "domain": "<one of the domain values above>",
  "confidence": <0.0-1.0>,
  "tags": {
    "geography": "<international|us|local|mixed>",
    "geography_detail": "<brief geographic note>",
    "actors": ["<key actors mentioned>"],
    "action_type": "<legislation|ruling|announcement|report|incident|other>",
    "topic_keywords": ["<2-5 key topic words>"]
  }
}"""
            }
        )

    result = connection.execute(
        sa.text("SELECT COUNT(*) FROM prompts WHERE name = 'classification_simplified_prompt'")
    )
    if result.scalar() == 0:
        # Insert classification simplified prompt
        connection.execute(
            sa.text("""
                INSERT INTO prompts (id, name, model, content, version, is_active, created_at, updated_at, auto_optimize_enabled, min_score_threshold, rollback_threshold)
                VALUES (
                    gen_random_uuid(),
                    'classification_simplified_prompt',
                    NULL,
                    :content,
                    1,
                    true,
                    NOW(),
                    NOW(),
                    false,
                    7.0,
                    0.5
                )
            """),
            {
                "content": """Classify this news article. Pick one domain and one geography.

DOMAINS: global_affairs, governance_politics, law_justice, security_defense, crime_public_safety, economy_macroeconomics, finance_markets, business_industry, labor_demographics, infrastructure_systems, energy, environment_climate, science_research, health_medicine, technology, media_information, sports_competition, society_culture, lifestyle_personal, incidents_disasters

GEOGRAPHY: international, us, local, mixed

Respond with JSON only:
{"domain": "...", "confidence": 0.9, "tags": {"geography": "...", "geography_detail": "", "actors": [], "action_type": "", "topic_keywords": []}}"""
            }
        )


def downgrade() -> None:
    """Remove prompt optimization and evaluation tables."""

    # Remove columns from prompts
    op.drop_column('prompts', 'rollback_threshold')
    op.drop_column('prompts', 'min_score_threshold')
    op.drop_column('prompts', 'auto_optimize_enabled')
    op.drop_column('prompts', 'current_version_id')

    # Drop article_evaluations
    op.drop_index('ix_article_evaluations_story_raw_id', table_name='article_evaluations')
    op.drop_index('ix_article_evaluations_evaluation_run_id', table_name='article_evaluations')
    op.drop_table('article_evaluations')

    # Drop evaluation_runs
    op.drop_index('ix_evaluation_runs_status', table_name='evaluation_runs')
    op.drop_index('ix_evaluation_runs_started_at', table_name='evaluation_runs')
    op.drop_index('ix_evaluation_runs_pipeline_run_id', table_name='evaluation_runs')
    op.drop_table('evaluation_runs')

    # Drop prompt_versions
    op.drop_index('ix_prompt_versions_created_at', table_name='prompt_versions')
    op.drop_index('ix_prompt_versions_prompt_id', table_name='prompt_versions')
    op.drop_table('prompt_versions')
