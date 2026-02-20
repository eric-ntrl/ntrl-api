# app/services/evaluation_service.py
"""
Teacher LLM evaluation service for automated prompt optimization.

Uses a teacher LLM to evaluate the quality of classification,
neutralization, and span detection produced by production LLMs.

The evaluation results drive prompt improvements and rollback decisions.
"""

import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------

# Model pricing (per 1M tokens) - Updated Feb 2026
MODEL_PRICING = {
    # Claude 4.6 series
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-opus-4-6": {"input": 5.00, "output": 25.00},
    # Claude 4.5 series
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-opus-4-5": {"input": 5.00, "output": 25.00},
    # OpenAI
    "gpt-5-nano": {"input": 0.05, "output": 0.40},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-5.1": {"input": 1.25, "output": 10.00},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "o3": {"input": 2.00, "output": 8.00},
    "o3-mini": {"input": 0.55, "output": 2.20},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
    # Legacy (backwards compat)
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
}


def _calculate_cost(input_tokens: int, output_tokens: int, model: str = "claude-opus-4-5") -> float:
    """Calculate estimated cost in USD."""
    # Find matching pricing tier
    for model_key, pricing in MODEL_PRICING.items():
        if model_key in model:
            return input_tokens * pricing["input"] / 1_000_000 + output_tokens * pricing["output"] / 1_000_000
    return 0.0


# ---------------------------------------------------------------------------
# Teacher prompts
# ---------------------------------------------------------------------------

CLASSIFICATION_EVAL_PROMPT = """You are a senior news editor evaluating article classification quality.

Given an article and its assigned classification, judge whether the classification is correct.

CLASSIFICATION TAXONOMY:
- domain: One of 20 internal categories (global_affairs, governance_politics, law_justice, security_defense, crime_public_safety, economy_macroeconomics, finance_markets, business_industry, labor_demographics, infrastructure_systems, energy, environment_climate, science_research, health_medicine, technology, media_information, sports_competition, society_culture, lifestyle_personal, incidents_disasters)
- feed_category: User-facing category (world, us, local, business, technology, science, health, environment, sports, culture)

DOMAIN → FEED_CATEGORY MAPPING RULES:
- Most domains map directly regardless of geography
- Geography-dependent domains (governance_politics, law_justice, security_defense, crime_public_safety, incidents_disasters):
  - international → world
  - us → us
  - local → local
  - mixed → us

BOUNDARY CASES — articles often span multiple domains. Classify by PRIMARY subject:
- Sports broadcasting, punditry, athlete personal lives → sports_competition
- Cybersecurity, hacking, data breaches → technology (not crime_public_safety)
- Movie/entertainment/celebrity news → lifestyle_personal (not media_information)
- Shopping deals, product promotions → business_industry

Evaluate:
1. Is the assigned domain correct for this article?
2. Does the feed_category correctly follow from domain + geography?
3. What domain/feed_category would you assign?

IMPORTANT RULES:
- If the assigned domain is REASONABLE for the article (even if you might choose differently), mark domain_correct as TRUE. Only mark FALSE when the classification is clearly wrong.
- If you mark domain_correct as FALSE, you MUST provide a specific expected_domain from the taxonomy above. Never leave expected_domain null/empty when marking incorrect.
- Many articles legitimately span multiple domains. Give the classifier the benefit of the doubt on borderline cases.

Respond with JSON:
{
  "domain_correct": true/false,
  "expected_domain": "<correct domain if different, REQUIRED when domain_correct is false>",
  "feed_category_correct": true/false,
  "expected_feed_category": "<correct category if different>",
  "confidence": 0.0-1.0,
  "reasoning": "<brief explanation>",
  "prompt_improvement_suggestion": "<how to improve the classification prompt, or null if correct>"
}"""

NEUTRALIZATION_EVAL_PROMPT = """You are a senior editor evaluating news neutralization quality.

Given an original article and its neutralized outputs, score the quality of neutralization.

SCORING CRITERIA (0-10 each):
1. MEANING PRESERVATION: Does the neutralized version accurately convey the same facts and events?
2. NEUTRALITY: Is manipulative, sensational, or biased language removed while keeping the text readable?
3. GRAMMAR: Is the output grammatically correct and professionally written?

NTRL RULES TO CHECK:
1. Emotional triggers removed (shocking, devastating, slammed)
2. Urgency inflation removed (BREAKING, JUST IN, scrambling)
3. Clickbait removed (You won't believe, Here's what happened)
4. Agenda signaling removed (radical left, extremist)
5. Editorial voice removed (we believe, as it should)
6. Loaded verbs neutralized (slammed→criticized, blasted→said)
7. Quoted speech preserved exactly
8. Facts preserved accurately
9. Grammar maintained or improved

For each rule violation found, note:
- The rule that was violated
- The specific text that violates it
- Whether it's in the original (and should have been caught) or introduced by neutralization

Respond with JSON:
{
  "overall_score": 0.0-10.0,
  "meaning_preservation_score": 0.0-10.0,
  "neutrality_score": 0.0-10.0,
  "grammar_score": 0.0-10.0,
  "rule_violations": [
    {"rule_id": "emotional_triggers", "text": "...", "location": "feed_title|detail_brief|detail_full", "severity": "high|medium|low"}
  ],
  "reasoning": "<brief overall assessment>",
  "prompt_improvement_suggestion": "<how to improve the neutralization prompt, or null if good>"
}"""

SPAN_EVAL_PROMPT = """You are a senior editor evaluating manipulation span detection quality.

Given an original article and the detected manipulation spans, evaluate precision and recall.

A CORRECT SPAN must:
1. Be genuinely manipulative (emotional trigger, urgency inflation, clickbait, editorial voice, etc.)
2. NOT be a full direct quote used neutrally for attribution (e.g., He said "we will review the policy"). However, cherry-picked inflammatory quote fragments, scare quotes ("so-called 'expert'"), or selectively chosen quotes that frame a narrative ARE valid manipulative spans categorized as "selective_quoting".
3. NOT be a false positive (professional terms, medical terminology, etc.)

MANIPULATION CATEGORIES (8 canonical + recognized aliases):
- emotional_trigger: Emotional language designed to provoke reactions (shocking, devastating, heartbreaking)
- urgency_inflation: False urgency or BREAKING/JUST IN when not warranted
- clickbait: "You won't believe", "Here's what happened next"
- selling: Promotional framing, hype language, sports/entertainment hyperbole
- agenda_signaling: Loaded labels (radical left, extremist), partisan framing
- rhetorical_framing: Loaded verbs (slammed, blasted), false equivalence, manufactured consensus, horse race framing, corporate anthropomorphism
- editorial_voice: First-person opinion (we believe, as it should), value judgments presented as fact
- selective_quoting: Cherry-picked inflammatory quotes, scare quotes, quote fragments chosen to frame narrative. Action is SOFTENED (not REMOVED). This is a valid detection — do NOT count as false positive.

ALIASES (map to canonical categories above):
- false_equivalence → rhetorical_framing
- manufactured_consensus → rhetorical_framing
- horse_race_framing → framing_bias / rhetorical_framing
- corporate_anthropomorphism → rhetorical_framing

CONTENT-TYPE CALIBRATION:
When evaluating span detection quality, consider the article's genre:
- Travel/lifestyle articles may legitimately use descriptive superlatives ("stunning views", "breathtaking scenery")
- Horoscope/astrology content uses speculative language ("destined", "cosmic") by genre convention
- Sports reporting uses more vivid language ("brilliant performance", "dominant display") than hard news
- Entertainment/culture reviews use evaluative language ("masterful", "riveting") as critical vocabulary
- Promotional content (competitions, giveaways) should flag promotional framing but not product descriptions
- Quote selection itself is an editorial technique — choosing the most inflammatory or dramatic quote when
  more measured alternatives exist is a framing decision. Flag these as "selective_quoting".
Adjust your precision/recall estimates accordingly — a "false positive" in hard news
may be a correct detection in tabloid celebrity coverage, and vice versa.

Evaluate:
1. PRECISION: What fraction of detected spans are correctly manipulative?
2. RECALL: What fraction of actual manipulative phrases were detected?
3. FALSE POSITIVES: Spans that shouldn't have been flagged
4. MISSED MANIPULATIONS: Phrases that should have been flagged but weren't

TITLE-BODY CONSISTENCY CHECK:
Each span has a "field" attribute ("title" or "body"). Check:
- If a manipulative phrase appears in the TITLE, is it flagged with field="title"?
- If a manipulative phrase appears in the BODY, is it flagged with field="body"?
- If a phrase appears in BOTH title AND body, BOTH occurrences should be flagged.
Report any inconsistencies where a phrase appears in one location but is only flagged in the other.

Respond with JSON:
{
  "estimated_precision": 0.0-1.0,
  "estimated_recall": 0.0-1.0,
  "false_positives": [
    {"phrase": "...", "reason_incorrect": "..."}
  ],
  "missed_manipulations": [
    {"phrase": "...", "reason_should_flag": "...", "category": "emotional_trigger|urgency_inflation|clickbait|selling|agenda_signaling|rhetorical_framing|editorial_voice|selective_quoting", "location": "title|body|both"}
  ],
  "title_body_inconsistencies": [
    {"phrase": "...", "found_in": "title|body|both", "flagged_in": "title|body|neither", "issue": "..."}
  ],
  "title_spans_count": <number of spans with field="title">,
  "body_spans_count": <number of spans with field="body">,
  "reasoning": "<brief assessment>",
  "prompt_improvement_suggestion": "<how to improve span detection, or null if good>"
}"""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class EvalInput:
    """Pre-extracted data for evaluating a single article (no ORM references)."""

    story_raw_id: str
    original_title: str
    original_description: str | None
    body: str
    spans: list[dict]
    domain: str | None
    feed_category: str | None
    feed_title: str
    feed_summary: str
    detail_brief: str
    detail_full: str


@dataclass
class ArticleEvaluationData:
    """Evaluation data for a single article."""

    story_raw_id: str
    original_title: str

    # Classification
    classification_correct: bool | None = None
    expected_domain: str | None = None
    expected_feed_category: str | None = None
    classification_feedback: str | None = None

    # Neutralization
    neutralization_score: float | None = None
    meaning_preservation_score: float | None = None
    neutrality_score: float | None = None
    grammar_score: float | None = None
    rule_violations: list[dict] | None = None
    neutralization_feedback: str | None = None

    # Spans
    span_precision: float | None = None
    span_recall: float | None = None
    missed_manipulations: list[dict] | None = None
    false_positives: list[dict] | None = None
    span_feedback: str | None = None
    # Title-body consistency (new)
    title_spans_count: int | None = None
    body_spans_count: int | None = None
    title_body_inconsistencies: list[dict] | None = None

    # Suggestions
    classification_prompt_suggestion: str | None = None
    neutralization_prompt_suggestion: str | None = None
    span_prompt_suggestion: str | None = None


@dataclass
class EvaluationResult:
    """Result of a complete evaluation run."""

    evaluation_run_id: str
    pipeline_run_id: str
    sample_size: int

    # Aggregate metrics
    classification_accuracy: float = 0.0
    avg_neutralization_score: float = 0.0
    avg_span_precision: float = 0.0
    avg_span_recall: float = 0.0
    overall_quality_score: float = 0.0

    # Recommendations
    recommendations: list[dict] = field(default_factory=list)

    # Token tracking
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0

    # Status
    status: str = "completed"
    error: str | None = None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def analyze_evaluations(db: Session, limit: int = 5) -> dict:
    """
    Aggregate evaluation data across recent runs for data-driven analysis.

    Cross-references teacher feedback with the FALSE_POSITIVE_PHRASES list
    to identify over-filters and missing FP entries.

    Args:
        db: Database session
        limit: Number of recent evaluation runs to analyze

    Returns:
        Dict matching EvaluationAnalysisResponse schema
    """
    from collections import Counter

    from app.services.neutralizer.spans import FALSE_POSITIVE_PATTERNS, FALSE_POSITIVE_PHRASES

    # Get recent completed evaluation runs
    runs = (
        db.query(models.EvaluationRun)
        .filter(models.EvaluationRun.status == "completed")
        .order_by(models.EvaluationRun.finished_at.desc())
        .limit(limit)
        .all()
    )

    if not runs:
        return {
            "runs_analyzed": 0,
            "articles_evaluated": 0,
            "false_positives": {"total": 0, "top_phrases": [], "would_be_filtered": []},
            "missed_manipulations": {"total": 0, "by_category": {}, "top_phrases": [], "blocked_by_fp_list": []},
            "classification": {"accuracy_by_run": [], "confusion_pairs": []},
        }

    run_ids = [r.id for r in runs]

    # Load all article evaluations for these runs
    article_evals = (
        db.query(models.ArticleEvaluation).filter(models.ArticleEvaluation.evaluation_run_id.in_(run_ids)).all()
    )

    # --- False Positives ---
    fp_phrase_counter: Counter = Counter()
    fp_reasons: dict[str, list[str]] = {}
    all_fp_phrases: list[str] = []

    for ae in article_evals:
        if not ae.false_positives:
            continue
        for fp in ae.false_positives:
            phrase = fp.get("phrase", "").strip()
            if not phrase:
                continue
            phrase_lower = phrase.lower()
            fp_phrase_counter[phrase_lower] += 1
            all_fp_phrases.append(phrase_lower)
            reason = fp.get("reason_incorrect", "") or fp.get("reason", "")
            if reason:
                fp_reasons.setdefault(phrase_lower, []).append(reason)

    # Check which FPs are already in the FALSE_POSITIVE_PHRASES set
    fp_lower_set = {p.lower() for p in FALSE_POSITIVE_PHRASES}
    would_be_filtered = sorted(set(p for p in all_fp_phrases if p in fp_lower_set))

    top_fp_phrases = [
        {
            "phrase": phrase,
            "count": count,
            "sample_reasons": fp_reasons.get(phrase, [])[:3],
        }
        for phrase, count in fp_phrase_counter.most_common(20)
    ]

    # --- Missed Manipulations ---
    missed_phrase_counter: Counter = Counter()
    missed_categories: Counter = Counter()
    missed_phrase_category: dict[str, str] = {}
    all_missed_phrases: list[str] = []

    for ae in article_evals:
        if not ae.missed_manipulations:
            continue
        for m in ae.missed_manipulations:
            phrase = m.get("phrase", "").strip()
            if not phrase:
                continue
            phrase_lower = phrase.lower()
            missed_phrase_counter[phrase_lower] += 1
            all_missed_phrases.append(phrase_lower)
            cat = m.get("category", "other")
            missed_categories[cat] += 1
            missed_phrase_category[phrase_lower] = cat

    # Check which missed phrases are blocked by the FP list
    def _matches_fp_list(phrase: str) -> bool:
        if phrase in fp_lower_set:
            return True
        for pattern in FALSE_POSITIVE_PATTERNS:
            if pattern.search(phrase):
                return True
        return False

    blocked_by_fp = sorted(set(p for p in all_missed_phrases if _matches_fp_list(p)))

    top_missed_phrases = [
        {
            "phrase": phrase,
            "count": count,
            "category": missed_phrase_category.get(phrase, ""),
        }
        for phrase, count in missed_phrase_counter.most_common(20)
    ]

    # --- Classification ---
    accuracy_by_run = []
    confusion_counter: Counter = Counter()

    for run in runs:
        run_evals = [ae for ae in article_evals if ae.evaluation_run_id == run.id]
        if not run_evals:
            continue
        correct = sum(1 for ae in run_evals if ae.classification_correct is True)
        accuracy_by_run.append(round(correct / len(run_evals), 2) if run_evals else 0.0)

        for ae in run_evals:
            if ae.classification_correct is False and ae.expected_domain:
                # Get the assigned domain from the story
                story = db.query(models.StoryRaw).filter(models.StoryRaw.id == ae.story_raw_id).first()
                assigned = story.domain if story else "unknown"
                confusion_counter[(ae.expected_domain, assigned)] += 1

    confusion_pairs = [
        {"expected": pair[0], "assigned": pair[1], "count": count} for pair, count in confusion_counter.most_common(10)
    ]

    return {
        "runs_analyzed": len(runs),
        "articles_evaluated": len(article_evals),
        "false_positives": {
            "total": len(all_fp_phrases),
            "top_phrases": top_fp_phrases,
            "would_be_filtered": would_be_filtered,
        },
        "missed_manipulations": {
            "total": len(all_missed_phrases),
            "by_category": dict(missed_categories),
            "top_phrases": top_missed_phrases,
            "blocked_by_fp_list": blocked_by_fp,
        },
        "classification": {
            "accuracy_by_run": accuracy_by_run,
            "confusion_pairs": confusion_pairs,
        },
    }


class EvaluationService:
    """
    Orchestrates teacher LLM evaluation of pipeline output quality.

    After a pipeline run, this service:
    1. Samples articles using stratified sampling (tabloid vs quality sources)
    2. Uses teacher LLM to evaluate classification, neutralization, and spans
    3. Stores detailed results in article_evaluations
    4. Computes aggregate metrics and recommendations
    """

    def __init__(self, teacher_model: str | None = None):
        """Initialize the evaluation service."""
        from app.config import get_settings

        self.teacher_model = teacher_model or get_settings().EVAL_MODEL
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._token_lock = threading.Lock()

    def run_evaluation(
        self,
        db: Session,
        pipeline_run_id: str,
        sample_size: int = 50,
    ) -> EvaluationResult:
        """
        Run a complete evaluation for a pipeline run.

        Args:
            db: Database session
            pipeline_run_id: ID of the PipelineRunSummary to evaluate
            sample_size: Number of articles to sample (default 10)

        Returns:
            EvaluationResult with aggregate metrics and recommendations
        """
        started_at = datetime.now(UTC)
        self._total_input_tokens = 0
        self._total_output_tokens = 0

        logger.info(f"[EVAL] Starting evaluation for pipeline run {pipeline_run_id}")

        # Create evaluation run record
        eval_run = models.EvaluationRun(
            id=uuid.uuid4(),
            pipeline_run_id=uuid.UUID(pipeline_run_id),
            teacher_model=self.teacher_model,
            sample_size=sample_size,
            status="running",
            started_at=started_at,
        )
        db.add(eval_run)
        db.flush()

        try:
            # Select sample articles
            sample = self._select_sample(db, pipeline_run_id, sample_size)
            if not sample:
                logger.warning("[EVAL] No articles found for evaluation")
                eval_run.status = "completed"
                eval_run.finished_at = datetime.now(UTC)
                db.commit()
                return EvaluationResult(
                    evaluation_run_id=str(eval_run.id),
                    pipeline_run_id=pipeline_run_id,
                    sample_size=0,
                    status="completed",
                )

            logger.info(f"[EVAL] Selected {len(sample)} articles for evaluation")

            # 1. Pre-fetch ALL data on main thread (extract from ORM)
            eval_inputs: list[EvalInput] = []
            for story_raw, story_neutralized in sample:
                body = self._get_body(story_raw)
                spans = [
                    {
                        "phrase": span.original_text,
                        "field": span.field,
                        "reason": span.reason,
                        "action": span.action,
                    }
                    for span in story_neutralized.spans
                ]
                eval_inputs.append(
                    EvalInput(
                        story_raw_id=str(story_raw.id),
                        original_title=story_raw.original_title,
                        original_description=story_raw.original_description,
                        body=body,
                        spans=spans,
                        domain=story_raw.domain,
                        feed_category=story_raw.feed_category,
                        feed_title=story_neutralized.feed_title,
                        feed_summary=story_neutralized.feed_summary,
                        detail_brief=story_neutralized.detail_brief or "",
                        detail_full=story_neutralized.detail_full or "",
                    )
                )

            logger.info(f"[EVAL] Pre-fetched data for {len(eval_inputs)} articles")

            # 2. Parallel evaluation — NO DB, NO ORM objects
            # Use 3 article-level workers (conservative for Anthropic rate limits)
            eval_start = time.monotonic()
            token_lock = threading.Lock()
            article_evals: list[ArticleEvaluationData] = []

            def _evaluate_safe(ei: EvalInput) -> ArticleEvaluationData:
                return self._evaluate_article_from_input(ei, token_lock)

            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(_evaluate_safe, ei): ei.story_raw_id for ei in eval_inputs}
                for future in as_completed(futures):
                    sid = futures[future]
                    try:
                        eval_data = future.result()
                        article_evals.append(eval_data)
                    except Exception as e:
                        logger.error(f"[EVAL] Evaluation failed for {sid}: {e}")
                        article_evals.append(
                            ArticleEvaluationData(
                                story_raw_id=sid,
                                original_title="",
                            )
                        )

            eval_elapsed = time.monotonic() - eval_start
            logger.info(f"[EVAL_PARALLEL] Completed {len(article_evals)} articles in {eval_elapsed:.1f}s (3 workers)")

            # 3. Sequential DB writes (main thread)
            for eval_data in article_evals:
                article_eval = models.ArticleEvaluation(
                    id=uuid.uuid4(),
                    evaluation_run_id=eval_run.id,
                    story_raw_id=uuid.UUID(eval_data.story_raw_id),
                    classification_correct=eval_data.classification_correct,
                    expected_domain=eval_data.expected_domain,
                    expected_feed_category=eval_data.expected_feed_category,
                    classification_feedback=eval_data.classification_feedback,
                    neutralization_score=eval_data.neutralization_score,
                    meaning_preservation_score=eval_data.meaning_preservation_score,
                    neutrality_score=eval_data.neutrality_score,
                    grammar_score=eval_data.grammar_score,
                    rule_violations=eval_data.rule_violations,
                    neutralization_feedback=eval_data.neutralization_feedback,
                    span_precision=eval_data.span_precision,
                    span_recall=eval_data.span_recall,
                    missed_manipulations=eval_data.missed_manipulations,
                    false_positives=eval_data.false_positives,
                    span_feedback=eval_data.span_feedback,
                    classification_prompt_suggestion=eval_data.classification_prompt_suggestion,
                    neutralization_prompt_suggestion=eval_data.neutralization_prompt_suggestion,
                    span_prompt_suggestion=eval_data.span_prompt_suggestion,
                )
                db.add(article_eval)

            # Compute aggregate metrics
            # Only count articles where the teacher gave a definitive answer:
            # - classification_correct=True → correct
            # - classification_correct=False AND expected_domain is not None → incorrect
            # - classification_correct=False AND expected_domain is None → ambiguous, exclude
            definitive_evals = [
                e
                for e in article_evals
                if e.classification_correct is True or (e.classification_correct is False and e.expected_domain)
            ]
            classification_correct_count = sum(1 for e in definitive_evals if e.classification_correct is True)
            classification_accuracy = classification_correct_count / len(definitive_evals) if definitive_evals else 0.0
            ambiguous_count = len(article_evals) - len(definitive_evals)
            if ambiguous_count > 0:
                logger.info(
                    f"[EVAL] Classification: {ambiguous_count} ambiguous articles excluded "
                    f"(teacher marked wrong but provided no expected_domain)"
                )

            neutralization_scores = [
                e.neutralization_score for e in article_evals if e.neutralization_score is not None
            ]
            avg_neutralization_score = (
                sum(neutralization_scores) / len(neutralization_scores) if neutralization_scores else 0.0
            )

            span_precisions = [e.span_precision for e in article_evals if e.span_precision is not None]
            avg_span_precision = sum(span_precisions) / len(span_precisions) if span_precisions else 0.0

            span_recalls = [e.span_recall for e in article_evals if e.span_recall is not None]
            avg_span_recall = sum(span_recalls) / len(span_recalls) if span_recalls else 0.0

            # Overall quality score (weighted average)
            overall_quality_score = (
                0.2 * (classification_accuracy * 10)
                + 0.5 * avg_neutralization_score
                + 0.3 * ((avg_span_precision + avg_span_recall) / 2 * 10)
            )

            # Generate recommendations
            recommendations = self._generate_recommendations(article_evals)

            # Calculate cost
            estimated_cost = _calculate_cost(
                self._total_input_tokens,
                self._total_output_tokens,
                self.teacher_model,
            )

            # Update evaluation run
            finished_at = datetime.now(UTC)
            duration_ms = int((finished_at - started_at).total_seconds() * 1000)

            eval_run.classification_accuracy = classification_accuracy
            eval_run.avg_neutralization_score = avg_neutralization_score
            eval_run.avg_span_precision = avg_span_precision
            eval_run.avg_span_recall = avg_span_recall
            eval_run.overall_quality_score = overall_quality_score
            eval_run.recommendations = recommendations
            eval_run.input_tokens = self._total_input_tokens
            eval_run.output_tokens = self._total_output_tokens
            eval_run.estimated_cost_usd = estimated_cost
            eval_run.finished_at = finished_at
            eval_run.duration_ms = duration_ms
            eval_run.status = "completed"

            db.commit()

            logger.info(
                f"[EVAL] Completed: accuracy={classification_accuracy:.2%}, "
                f"neutralization={avg_neutralization_score:.1f}/10, "
                f"span_precision={avg_span_precision:.2%}, span_recall={avg_span_recall:.2%}, "
                f"overall={overall_quality_score:.1f}/10, "
                f"cost=${estimated_cost:.2f}"
            )

            return EvaluationResult(
                evaluation_run_id=str(eval_run.id),
                pipeline_run_id=pipeline_run_id,
                sample_size=len(sample),
                classification_accuracy=classification_accuracy,
                avg_neutralization_score=avg_neutralization_score,
                avg_span_precision=avg_span_precision,
                avg_span_recall=avg_span_recall,
                overall_quality_score=overall_quality_score,
                recommendations=recommendations,
                input_tokens=self._total_input_tokens,
                output_tokens=self._total_output_tokens,
                estimated_cost_usd=estimated_cost,
                status="completed",
            )

        except Exception as e:
            logger.error(f"[EVAL] Evaluation failed: {e}")
            eval_run.status = "failed"
            eval_run.finished_at = datetime.now(UTC)
            db.commit()

            return EvaluationResult(
                evaluation_run_id=str(eval_run.id),
                pipeline_run_id=pipeline_run_id,
                sample_size=0,
                status="failed",
                error=str(e),
            )

    def _select_sample(
        self,
        db: Session,
        pipeline_run_id: str,
        sample_size: int,
    ) -> list[tuple]:
        """
        Select a stratified sample of articles for evaluation.

        Strategy: 30% tabloid sources, 30% quality sources, 40% mixed
        This ensures we evaluate across source quality levels.

        Returns list of (StoryRaw, StoryNeutralized) tuples.
        """
        # Tabloid sources (higher manipulation density)
        tabloid_slugs = {"daily-mail", "the-sun", "new-york-post", "tmz"}

        # Quality sources (lower manipulation, better baseline)
        quality_slugs = {"ap", "reuters", "bbc", "npr"}

        # Get pipeline run to find the time window
        pipeline_run = (
            db.query(models.PipelineRunSummary)
            .filter(models.PipelineRunSummary.id == uuid.UUID(pipeline_run_id))
            .first()
        )

        if not pipeline_run:
            logger.warning(f"[EVAL] Pipeline run {pipeline_run_id} not found")
            return []

        # Find neutralized stories from this pipeline run's time window
        base_query = (
            db.query(models.StoryRaw, models.StoryNeutralized)
            .join(models.StoryNeutralized, models.StoryRaw.id == models.StoryNeutralized.story_raw_id)
            .join(models.Source, models.StoryRaw.source_id == models.Source.id)
            .filter(models.StoryNeutralized.is_current == True)
            .filter(models.StoryNeutralized.neutralization_status == "success")
            .filter(models.StoryNeutralized.created_at >= pipeline_run.started_at)
            .filter(models.StoryNeutralized.created_at <= pipeline_run.finished_at)
        )

        # Calculate sample distribution
        tabloid_count = int(sample_size * 0.3)
        quality_count = int(sample_size * 0.3)
        mixed_count = sample_size - tabloid_count - quality_count

        sample = []

        # Get tabloid samples
        tabloid_stories = (
            base_query.filter(models.Source.slug.in_(tabloid_slugs))
            .order_by(models.StoryRaw.ingested_at.desc())
            .limit(tabloid_count)
            .all()
        )
        sample.extend(tabloid_stories)

        # Get quality samples
        quality_stories = (
            base_query.filter(models.Source.slug.in_(quality_slugs))
            .order_by(models.StoryRaw.ingested_at.desc())
            .limit(quality_count)
            .all()
        )
        sample.extend(quality_stories)

        # Get mixed samples (any other sources)
        mixed_stories = (
            base_query.filter(~models.Source.slug.in_(tabloid_slugs | quality_slugs))
            .order_by(models.StoryRaw.ingested_at.desc())
            .limit(mixed_count)
            .all()
        )
        sample.extend(mixed_stories)

        # If we didn't get enough, fill from any source within pipeline window
        if len(sample) < sample_size:
            remaining = sample_size - len(sample)
            existing_ids = {s[0].id for s in sample}
            more = (
                base_query.filter(~models.StoryRaw.id.in_(existing_ids))
                .order_by(models.StoryRaw.ingested_at.desc())
                .limit(remaining)
                .all()
            )
            sample.extend(more)

        # Fallback: if pipeline window returned too few articles (e.g. re-neutralized
        # articles via /v1/neutralize/run fall outside the pipeline run window),
        # expand to a 24-hour time-based window
        if len(sample) < sample_size:
            remaining = sample_size - len(sample)
            existing_ids = {s[0].id for s in sample}
            cutoff = datetime.now(UTC) - timedelta(hours=24)
            fallback_query = (
                db.query(models.StoryRaw, models.StoryNeutralized)
                .join(models.StoryNeutralized, models.StoryRaw.id == models.StoryNeutralized.story_raw_id)
                .filter(models.StoryNeutralized.is_current == True)
                .filter(models.StoryNeutralized.neutralization_status == "success")
                .filter(models.StoryNeutralized.created_at >= cutoff)
                .filter(~models.StoryRaw.id.in_(existing_ids))
                .order_by(models.StoryNeutralized.created_at.desc())
                .limit(remaining)
                .all()
            )
            if fallback_query:
                logger.info(
                    f"[EVAL] Pipeline window had {len(sample)} articles, "
                    f"expanded to 24h window: +{len(fallback_query)} articles"
                )
                sample.extend(fallback_query)

        return sample[:sample_size]

    def _evaluate_article_from_input(
        self,
        ei: EvalInput,
        token_lock: threading.Lock,
    ) -> ArticleEvaluationData:
        """Evaluate a single article using pre-extracted data (thread-safe, no DB)."""
        eval_data = ArticleEvaluationData(
            story_raw_id=ei.story_raw_id,
            original_title=ei.original_title,
        )

        # Run all 3 eval calls concurrently within this article
        class_result = None
        neut_result = None
        span_result = None

        def _eval_classification():
            return self._evaluate_classification(
                original_title=ei.original_title,
                original_description=ei.original_description,
                original_body=ei.body[:8000] if ei.body else "",
                assigned_domain=ei.domain,
                assigned_feed_category=ei.feed_category,
            )

        def _eval_neutralization():
            return self._evaluate_neutralization(
                original_title=ei.original_title,
                original_body=ei.body,
                feed_title=ei.feed_title,
                feed_summary=ei.feed_summary,
                detail_brief=ei.detail_brief,
                detail_full=ei.detail_full,
            )

        def _eval_spans():
            return self._evaluate_spans(
                original_title=ei.original_title,
                original_body=ei.body,
                detected_spans=ei.spans,
                feed_category=ei.feed_category,
            )

        # Run the 3 eval calls concurrently within this article
        with ThreadPoolExecutor(max_workers=3) as inner_executor:
            class_future = inner_executor.submit(_eval_classification)
            neut_future = inner_executor.submit(_eval_neutralization)
            span_future = inner_executor.submit(_eval_spans)

            try:
                class_result = class_future.result()
            except Exception as e:
                logger.error(f"[EVAL] Classification eval failed for {ei.story_raw_id}: {e}")
                eval_data.classification_feedback = f"ERROR: {str(e)}"

            try:
                neut_result = neut_future.result()
            except Exception as e:
                logger.error(f"[EVAL] Neutralization eval failed for {ei.story_raw_id}: {e}")
                eval_data.neutralization_feedback = f"ERROR: {str(e)}"

            try:
                span_result = span_future.result()
            except Exception as e:
                logger.error(f"[EVAL] Span eval failed for {ei.story_raw_id}: {e}")
                eval_data.span_feedback = f"ERROR: {str(e)}"

        # Process classification result
        if class_result:
            eval_data.classification_correct = class_result.get("domain_correct", False) and class_result.get(
                "feed_category_correct", False
            )
            eval_data.expected_domain = class_result.get("expected_domain")
            eval_data.expected_feed_category = class_result.get("expected_feed_category")
            eval_data.classification_feedback = class_result.get("reasoning")
            eval_data.classification_prompt_suggestion = class_result.get("prompt_improvement_suggestion")

        # Process neutralization result
        if neut_result:
            eval_data.neutralization_score = neut_result.get("overall_score")
            eval_data.meaning_preservation_score = neut_result.get("meaning_preservation_score")
            eval_data.neutrality_score = neut_result.get("neutrality_score")
            eval_data.grammar_score = neut_result.get("grammar_score")
            eval_data.rule_violations = neut_result.get("rule_violations", [])
            eval_data.neutralization_feedback = neut_result.get("reasoning")
            eval_data.neutralization_prompt_suggestion = neut_result.get("prompt_improvement_suggestion")

        # Process span result
        if span_result:
            eval_data.span_precision = span_result.get("estimated_precision")
            eval_data.span_recall = span_result.get("estimated_recall")
            eval_data.missed_manipulations = span_result.get("missed_manipulations", [])
            eval_data.false_positives = span_result.get("false_positives", [])
            eval_data.span_feedback = span_result.get("reasoning")
            eval_data.span_prompt_suggestion = span_result.get("prompt_improvement_suggestion")
            eval_data.title_spans_count = span_result.get("title_spans_count")
            eval_data.body_spans_count = span_result.get("body_spans_count")
            eval_data.title_body_inconsistencies = span_result.get("title_body_inconsistencies", [])

        return eval_data

    def _get_body(self, story_raw: models.StoryRaw) -> str:
        """Get article body from storage, with content cleaning applied."""
        if not story_raw.raw_content_uri or not story_raw.raw_content_available:
            return ""

        try:
            from app.storage.factory import get_storage_provider
            from app.utils.content_cleaner import clean_article_body

            storage = get_storage_provider()
            result = storage.download(story_raw.raw_content_uri)
            if result and result.exists:
                raw = result.content.decode("utf-8", errors="replace")
                return clean_article_body(raw)
        except Exception as e:
            logger.warning(f"[EVAL] Failed to get body for {story_raw.id}: {e}")

        return ""

    def _evaluate_classification(
        self,
        original_title: str,
        original_description: str,
        original_body: str,
        assigned_domain: str,
        assigned_feed_category: str,
    ) -> dict[str, Any]:
        """Use teacher LLM to evaluate classification correctness."""
        user_prompt = f"""ARTICLE:
Title: {original_title}
Description: {original_description or "(none)"}
Body excerpt: {original_body[:4000]}

ASSIGNED CLASSIFICATION:
- Domain: {assigned_domain or "(unassigned)"}
- Feed Category: {assigned_feed_category or "(unassigned)"}

Evaluate if this classification is correct."""

        return self._call_teacher(CLASSIFICATION_EVAL_PROMPT, user_prompt)

    def _evaluate_neutralization(
        self,
        original_title: str,
        original_body: str,
        feed_title: str,
        feed_summary: str,
        detail_brief: str,
        detail_full: str,
    ) -> dict[str, Any]:
        """Use teacher LLM to evaluate neutralization quality."""
        user_prompt = f"""ORIGINAL ARTICLE:
Title: {original_title}
Body: {original_body}

NEUTRALIZED OUTPUTS:
Feed Title: {feed_title}
Feed Summary: {feed_summary}
Detail Brief: {detail_brief[:4000] if detail_brief else "(none)"}
Detail Full: {detail_full[:8000] if detail_full else "(none)"}

Evaluate the neutralization quality."""

        return self._call_teacher(NEUTRALIZATION_EVAL_PROMPT, user_prompt)

    def _evaluate_spans(
        self,
        original_title: str,
        original_body: str,
        detected_spans: list[dict],
        feed_category: str | None = None,
    ) -> dict[str, Any]:
        """Use teacher LLM to evaluate span detection quality."""
        spans_text = json.dumps(detected_spans, indent=2) if detected_spans else "[]"

        category_line = f"\nArticle Category: {feed_category}" if feed_category else ""

        user_prompt = f"""ORIGINAL ARTICLE:
Title: {original_title}{category_line}
Body: {original_body}

DETECTED MANIPULATION SPANS:
{spans_text}

Evaluate the span detection quality (precision and recall)."""

        return self._call_teacher(SPAN_EVAL_PROMPT, user_prompt)

    def _call_teacher(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Call the teacher LLM (supports OpenAI and Anthropic)."""
        # Match both old and new Claude model naming conventions
        # Old: claude-3-5-sonnet-latest, claude-3-5-sonnet
        # New: claude-sonnet-4-5, claude-haiku-4-5, claude-opus-4-5
        if "claude" in self.teacher_model.lower():
            return self._call_teacher_anthropic(system_prompt, user_prompt)
        else:
            return self._call_teacher_openai(system_prompt, user_prompt)

    def _call_teacher_anthropic(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Call Anthropic Claude for evaluation."""
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, timeout=90.0)

            response = client.messages.create(
                model=self.teacher_model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            # Track tokens (thread-safe)
            if response.usage:
                with self._token_lock:
                    self._total_input_tokens += response.usage.input_tokens
                    self._total_output_tokens += response.usage.output_tokens

            content = response.content[0].text.strip()

            # Try direct JSON parse first
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # Extract first valid JSON object from response
                # (Claude may include text before/after, or multiple objects)
                decoder = json.JSONDecoder()
                for i, char in enumerate(content):
                    if char == "{":
                        try:
                            obj, _ = decoder.raw_decode(content, i)
                            return obj
                        except json.JSONDecodeError:
                            continue
                raise ValueError(f"No valid JSON found in response: {content[:200]}")

        except Exception as e:
            logger.error(f"[EVAL] Anthropic teacher LLM call failed: {e}")
            raise

    def _call_teacher_openai(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Call OpenAI GPT for evaluation."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")

        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, timeout=30.0)

            response = client.chat.completions.create(
                model=self.teacher_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )

            # Track tokens (thread-safe)
            if response.usage:
                with self._token_lock:
                    self._total_input_tokens += response.usage.prompt_tokens
                    self._total_output_tokens += response.usage.completion_tokens

            content = response.choices[0].message.content.strip()
            return json.loads(content)

        except Exception as e:
            logger.error(f"[EVAL] OpenAI teacher LLM call failed: {e}")
            raise

    def _generate_recommendations(
        self,
        article_evals: list[ArticleEvaluationData],
    ) -> list[dict]:
        """Generate actionable recommendations from evaluation results.

        CONTINUOUS IMPROVEMENT MODE (Jan 2026):
        Always generates recommendations when metrics are below 99% targets,
        not just when they fall below "failure" thresholds. This enables
        the system to continuously improve toward 99%+ quality.

        Target thresholds (overall score 9-10):
        - Classification: 100% accuracy
        - Neutralization: 9.0+/10 average score
        - Span precision: 90%+
        - Span recall: 90%+
        """
        recommendations = []

        # Collect all suggestions from teacher LLM
        classification_suggestions = [
            e.classification_prompt_suggestion for e in article_evals if e.classification_prompt_suggestion
        ]
        neutralization_suggestions = [
            e.neutralization_prompt_suggestion for e in article_evals if e.neutralization_prompt_suggestion
        ]
        span_suggestions = [e.span_prompt_suggestion for e in article_evals if e.span_prompt_suggestion]

        # Calculate aggregate metrics (exclude ambiguous: teacher said wrong but gave no alternative)
        definitive_evals = [
            e
            for e in article_evals
            if e.classification_correct is True or (e.classification_correct is False and e.expected_domain)
        ]
        classification_correct_count = sum(1 for e in definitive_evals if e.classification_correct is True)
        classification_accuracy = classification_correct_count / len(definitive_evals) if definitive_evals else 0.0

        neutralization_scores = [e.neutralization_score for e in article_evals if e.neutralization_score is not None]
        avg_neutralization = sum(neutralization_scores) / len(neutralization_scores) if neutralization_scores else 0.0

        span_precisions = [e.span_precision for e in article_evals if e.span_precision is not None]
        avg_span_precision = sum(span_precisions) / len(span_precisions) if span_precisions else 0.0

        span_recalls = [e.span_recall for e in article_evals if e.span_recall is not None]
        avg_span_recall = sum(span_recalls) / len(span_recalls) if span_recalls else 0.0

        # =====================================================================
        # CLASSIFICATION RECOMMENDATIONS
        # =====================================================================

        # Critical: any misclassifications
        incorrect_classifications = [e for e in article_evals if e.classification_correct is False]
        if incorrect_classifications:
            # Group by expected domain to find patterns
            domain_misses = {}
            for e in incorrect_classifications:
                if e.expected_domain:
                    domain_misses.setdefault(e.expected_domain, []).append(e.story_raw_id)

            for domain, article_ids in domain_misses.items():
                if len(article_ids) >= 2:  # Pattern: 2+ misses for same domain
                    recommendations.append(
                        {
                            "prompt_name": "classification_system_prompt",
                            "issue_category": "classification",
                            "issue_description": f"Multiple articles misclassified (should be {domain})",
                            "suggested_change": classification_suggestions[0]
                            if classification_suggestions
                            else f"Improve examples for {domain} domain",
                            "priority": "high" if len(article_ids) >= 3 else "medium",
                            "affected_articles": article_ids,
                        }
                    )

        # Continuous improvement: classification below 100%
        if classification_accuracy < 1.0 and incorrect_classifications:
            recommendations.append(
                {
                    "prompt_name": "classification_system_prompt",
                    "issue_category": "continuous_improvement",
                    "issue_description": f"Classification accuracy at {classification_accuracy:.1%}, targeting 100%",
                    "suggested_change": classification_suggestions[0]
                    if classification_suggestions
                    else "Review misclassified examples and add clarifying guidance",
                    "priority": "low" if classification_accuracy >= 0.95 else "medium",
                    "affected_articles": [e.story_raw_id for e in incorrect_classifications],
                }
            )

        # =====================================================================
        # NEUTRALIZATION RECOMMENDATIONS
        # =====================================================================

        # Critical: articles with low neutralization scores (<7.0)
        low_neutralization_scores = [
            e for e in article_evals if e.neutralization_score is not None and e.neutralization_score < 7.0
        ]
        if low_neutralization_scores:
            recommendations.append(
                {
                    "prompt_name": "article_system_prompt",
                    "issue_category": "neutralization",
                    "issue_description": f"{len(low_neutralization_scores)} articles scored below 7.0",
                    "suggested_change": neutralization_suggestions[0]
                    if neutralization_suggestions
                    else "Review neutralization rules",
                    "priority": "high" if len(low_neutralization_scores) >= 3 else "medium",
                    "affected_articles": [e.story_raw_id for e in low_neutralization_scores],
                }
            )

        # Continuous improvement: neutralization below 9.0/10 (target: 9-10)
        if avg_neutralization < 9.0 and neutralization_scores:
            below_target = [
                e for e in article_evals if e.neutralization_score is not None and e.neutralization_score < 9.0
            ]
            if below_target:
                recommendations.append(
                    {
                        "prompt_name": "article_system_prompt",
                        "issue_category": "continuous_improvement",
                        "issue_description": f"Neutralization avg {avg_neutralization:.1f}/10, targeting 9.0+/10",
                        "suggested_change": neutralization_suggestions[0]
                        if neutralization_suggestions
                        else "Refine neutralization rules for edge cases",
                        "priority": "low" if avg_neutralization >= 8.5 else "medium",
                        "affected_articles": [e.story_raw_id for e in below_target[:5]],
                    }
                )

        # =====================================================================
        # SPAN DETECTION RECOMMENDATIONS
        # =====================================================================

        # Collect all false positives and missed manipulations (with story_raw_id)
        all_fps = []
        all_misses = []
        for e in article_evals:
            if e.false_positives:
                for fp in e.false_positives:
                    fp_copy = dict(fp)
                    fp_copy["story_raw_id"] = e.story_raw_id
                    all_fps.append(fp_copy)
            if e.missed_manipulations:
                for m in e.missed_manipulations:
                    m_copy = dict(m)
                    m_copy["story_raw_id"] = e.story_raw_id
                    all_misses.append(m_copy)

        # Critical: precision below 80%
        low_precision = [e for e in article_evals if e.span_precision is not None and e.span_precision < 0.8]
        if low_precision:
            recommendations.append(
                {
                    "prompt_name": "span_detection_prompt",
                    "issue_category": "span_detection",
                    "issue_description": f"{len(low_precision)} articles with low span precision (<80%)",
                    "suggested_change": span_suggestions[0]
                    if span_suggestions
                    else "Add false positives to exclusion list",
                    "priority": "high",
                    "affected_articles": [e.story_raw_id for e in low_precision],
                    "false_positives_sample": all_fps[:5],
                }
            )

        # Critical: recall below 70%
        low_recall = [e for e in article_evals if e.span_recall is not None and e.span_recall < 0.7]
        if low_recall:
            recommendations.append(
                {
                    "prompt_name": "span_detection_prompt",
                    "issue_category": "span_detection",
                    "issue_description": f"{len(low_recall)} articles with low span recall (<70%)",
                    "suggested_change": span_suggestions[0]
                    if span_suggestions
                    else "Add missing categories to detection prompt",
                    "priority": "high",
                    "affected_articles": [e.story_raw_id for e in low_recall],
                    "missed_phrases_sample": all_misses[:5],
                }
            )

        # Continuous improvement: precision below 90% (target: 90%+)
        if avg_span_precision < 0.90 and span_precisions and all_fps:
            recommendations.append(
                {
                    "prompt_name": "span_detection_prompt",
                    "issue_category": "continuous_improvement",
                    "issue_description": f"Span precision at {avg_span_precision:.1%}, targeting 90%+",
                    "suggested_change": span_suggestions[0]
                    if span_suggestions
                    else "Review and add false positive patterns to exclusion list",
                    "priority": "low" if avg_span_precision >= 0.80 else "medium",
                    "affected_articles": [e.story_raw_id for e in article_evals if e.false_positives][:5],
                    "false_positives_sample": all_fps[:10],
                }
            )

        # Continuous improvement: recall below 90% (target: 90%+)
        if avg_span_recall < 0.90 and span_recalls and all_misses:
            recommendations.append(
                {
                    "prompt_name": "span_detection_prompt",
                    "issue_category": "continuous_improvement",
                    "issue_description": f"Span recall at {avg_span_recall:.1%}, targeting 90%+",
                    "suggested_change": span_suggestions[0]
                    if span_suggestions
                    else "Add missed manipulation patterns to detection prompt",
                    "priority": "low" if avg_span_recall >= 0.80 else "medium",
                    "affected_articles": [e.story_raw_id for e in article_evals if e.missed_manipulations][:5],
                    "missed_phrases_sample": all_misses[:10],
                }
            )

        # =====================================================================
        # TITLE-BODY CONSISTENCY RECOMMENDATIONS
        # =====================================================================

        # Collect all title-body inconsistencies
        all_inconsistencies = []
        for e in article_evals:
            if e.title_body_inconsistencies:
                for inc in e.title_body_inconsistencies:
                    inc["story_raw_id"] = e.story_raw_id
                    all_inconsistencies.append(inc)

        # Check for title-specific misses in missed_manipulations
        title_misses = []
        for m in all_misses:
            location = m.get("location", "")
            if location in ("title", "both"):
                title_misses.append(m)

        if title_misses:
            recommendations.append(
                {
                    "prompt_name": "span_detection_prompt",
                    "issue_category": "title_detection_consistency",
                    "issue_description": f"{len(title_misses)} phrases missed in titles",
                    "suggested_change": "Emphasize that HEADLINE section should be analyzed with same rigor as body. Ensure title manipulations are detected.",
                    "priority": "high" if len(title_misses) >= 3 else "medium",
                    "affected_articles": list(
                        set(m.get("story_raw_id") for m in title_misses if m.get("story_raw_id"))
                    )[:5],
                    "missed_title_phrases": title_misses[:5],
                }
            )

        # Check for title-body inconsistencies (phrase in both but only flagged in one)
        if all_inconsistencies:
            recommendations.append(
                {
                    "prompt_name": "span_detection_prompt",
                    "issue_category": "title_body_inconsistency",
                    "issue_description": f"{len(all_inconsistencies)} title-body inconsistencies detected",
                    "suggested_change": "If a phrase appears in BOTH the title and body, ensure BOTH occurrences are flagged.",
                    "priority": "high" if len(all_inconsistencies) >= 2 else "medium",
                    "affected_articles": list(set(inc.get("story_raw_id") for inc in all_inconsistencies))[:5],
                    "inconsistencies_sample": all_inconsistencies[:5],
                }
            )

        logger.info(
            f"[EVAL] Generated {len(recommendations)} recommendations "
            f"(class_acc={classification_accuracy:.1%}, neut={avg_neutralization:.1f}, "
            f"precision={avg_span_precision:.1%}, recall={avg_span_recall:.1%})"
        )

        return recommendations
