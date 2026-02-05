# app/services/quality_scorer.py
"""
LLM-based quality scorer for neutralization outputs.

This service uses an LLM to evaluate neutralized text against the NTRL Canon.
It provides a quality score (0-10), feedback, and identifies rule violations.

This is for development iteration only - not for production use.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Literal

logger = logging.getLogger(__name__)


# Canon rules for grading rubric
CANON_RUBRIC = """
# NTRL Neutralization Canon v1.0 - Grading Rubric

## CRITICAL: Quote Preservation Rule
DIRECT QUOTES MUST BE PRESERVED VERBATIM. If text appears inside quotation marks with attribution
(e.g., Senator X said "..."), the quote content should NOT be neutralized. This is NOT a violation.
Emotional language inside attributed quotes is acceptable because we're reporting what someone said.
Only UNATTRIBUTED narrative text (the journalist's words) should be neutralized.

## A. Meaning Preservation (Highest Priority)
- A1: No new facts may be introduced
- A2: Facts may not be removed if doing so changes meaning
- A3: Factual scope and quantifiers must be preserved (all, every, entire, more, multiple)
- A4: Compound factual terms are atomic (e.g., "domestic abuse", "sex work" - cannot split)
- A5: Epistemic certainty must be preserved exactly ("set to", "plans to", "expected to")
- A6: Causal facts are not motives (don't infer why something happened)

## B. Neutrality Enforcement (ONLY applies to unattributed narrative text)
- B1: Remove urgency framing ("breaking", "just in", "developing story")
- B2: Remove emotional amplification ("shocking", "devastating", "terrifying") - BUT PRESERVE IN QUOTES
- B3: Remove agenda/ideological signaling unless quoted and attributed ("woke", "elite")
- B4: Remove conflict theater language ("slams", "destroys", "eviscerates") - BUT PRESERVE IN QUOTES
- B5: Remove implied judgment from narrative, not from quoted opinions

## C. Attribution & Agency Safety
- C1: No inferred ownership or affiliation
- C2: No possessive constructions involving named individuals unless explicit
- C3: No inferred intent or purpose (but people CAN state their own intent in quotes)
- C4: Attribution must be preserved

## D. Structural & Mechanical Constraints
- D1: Grammar must be intact
- D2: No ALL-CAPS emphasis except acronyms
- D3: Headlines must be ≤12 words
- D4: Neutral tone in narrative (quotes exempt)

## What IS a violation:
- Urgency words in journalist's narrative (not quotes): "BREAKING: X happened"
- Emotional amplifiers in journalist's narrative: "In a shocking move, X did Y"
- Conflict theater in journalist's narrative: "X slams Y" (outside of quotes)

## What is NOT a violation:
- Senator saying "This is a historic investment" (it's their opinion, quoted)
- CEO saying "demand is growing rapidly" (it's their statement, quoted)
- Environmental group calling something "a crisis" (it's their characterization, quoted)
- Factual use of intense words: "45 people died" (factual, not emotional)

## Scoring Guidelines
- 10: Perfect neutralization - narrative neutral, quotes preserved, meaning intact
- 9: Excellent - minor style issues only, no rule violations
- 8: Good - very minor issues, acceptable for production
- 7: Acceptable - some issues but core meaning preserved
- 6: Borderline - noticeable issues that should be fixed
- 5: Below standard - multiple rule violations in narrative text
- 4: Poor - significant meaning distortion or missed manipulation
- 3: Bad - major rule violations
- 2: Very bad - fundamental failures
- 1: Unacceptable - completely wrong approach
- 0: Harmful - introduces misinformation or bias
"""

SCORING_PROMPT = """You are a quality scorer for NTRL neutralization outputs.

Your task is to evaluate how well a neutralized text follows the NTRL Neutralization Canon.

{rubric}

## Your Task

Compare the original text to the neutralized text and:
1. Identify any rule violations (cite specific rule IDs like A1, B2, etc.)
2. Assess overall quality on a 0-10 scale
3. Provide specific, actionable feedback

## Original Text
{original_text}

## Neutralized Text
{neutral_text}

Respond with JSON only:
{{
  "score": <float 0-10>,
  "feedback": "<2-3 sentences of specific feedback>",
  "rule_violations": [
    {{"rule": "<rule_id>", "description": "<what was violated>"}},
    ...
  ]
}}

Be strict but fair. A score of 8.5+ means production-ready quality."""


# Feed outputs rubric - for compressed headlines and summaries
FEED_OUTPUTS_RUBRIC = """
# NTRL Feed Outputs Grading Rubric

## Context
Feed outputs are COMPRESSED versions of an article - they are NOT meant to preserve all details.
A feed_title is ≤12 words. A feed_summary is ≤100 characters. A detail_title is ≤12 words.
These are meant to give readers enough to decide if they want to read more - NOT full coverage.

## What to Grade

### Neutrality (Most Important)
- No urgency framing: "BREAKING", "just in", "developing"
- No emotional amplifiers: "shocking", "devastating", "terrifying", "historic"
- No conflict theater: "slams", "destroys", "eviscerates"
- No clickbait: questions, teasers, "you won't believe", "here's why"
- No selling language: "exclusive", "secret", "revealed"
- No agenda signaling: "woke", "radical left", partisan framing

### Accuracy
- No new facts invented
- Key fact from article is represented correctly
- No misleading framing or implications

### Completeness (for compression)
- Captures the core news event
- Appropriate level of detail for format (headline vs summary)
- NOT expected to include all details from source

## What is NOT a violation for feed outputs:
- Omitting details that don't fit in ≤12 words or ≤100 chars
- Not preserving every scope marker from a 1000-word article in a 6-word headline
- Simplifying complex facts for brevity
- Not including quotes (they often don't fit)

## Scoring Guidelines
- 10: Perfect - neutral, accurate, well-compressed
- 9: Excellent - minor style issues only
- 8: Good - accurate and neutral, acceptable for production
- 7: Acceptable - minor issues, captures core fact
- 6: Borderline - some neutrality or accuracy issues
- 5: Below standard - noticeable problems
- 4: Poor - significant issues with neutrality or accuracy
- 3: Bad - misleading or manipulative
- 2: Very bad - major problems
- 1: Unacceptable - fails basic criteria
- 0: Harmful - introduces bias or misinformation
"""

FEED_OUTPUTS_SCORING_PROMPT = """You are a quality scorer for NTRL feed outputs (compressed headlines and summaries).

Your task is to evaluate how well compressed feed outputs follow the NTRL Canon for neutral news presentation.

{rubric}

## Your Task

The original article is provided for reference. Evaluate the feed outputs for:
1. Neutrality - no urgency, emotional language, conflict theater, or clickbait
2. Accuracy - core fact is represented correctly
3. Appropriate compression - captures essential news in limited space

## Original Article
{original_text}

## Feed Outputs to Grade
{neutral_text}

Respond with JSON only:
{{
  "score": <float 0-10>,
  "feedback": "<2-3 sentences of specific feedback>",
  "rule_violations": [
    {{"rule": "<rule_id>", "description": "<what was violated>"}},
    ...
  ]
}}

Remember: These are compressed outputs. Omitting details for brevity is NOT a violation.
Grade based on neutrality, accuracy, and appropriate compression for the format."""


@dataclass
class QualityScore:
    """Result from quality scoring."""
    score: float
    feedback: str
    rule_violations: List[dict]


def score_quality(
    original_text: str,
    neutral_text: str,
    provider: Literal["openai", "anthropic"] = "openai",
    original_headline: Optional[str] = None,
    neutral_headline: Optional[str] = None,
) -> QualityScore:
    """
    Score neutralization quality using an LLM.

    Args:
        original_text: The original source text
        neutral_text: The neutralized output text
        provider: Which LLM provider to use ("openai" or "anthropic")
        original_headline: Optional original headline
        neutral_headline: Optional neutralized headline

    Returns:
        QualityScore with score (0-10), feedback, and rule_violations list
    """
    # Build the full text to evaluate
    orig_full = original_text
    neutral_full = neutral_text

    if original_headline:
        orig_full = f"HEADLINE: {original_headline}\n\nBODY: {original_text}"
    if neutral_headline:
        neutral_full = f"HEADLINE: {neutral_headline}\n\nBODY: {neutral_text}"

    prompt = SCORING_PROMPT.format(
        rubric=CANON_RUBRIC,
        original_text=orig_full,
        neutral_text=neutral_full,
    )

    if provider == "openai":
        return _score_with_openai(prompt)
    elif provider == "anthropic":
        return _score_with_anthropic(prompt)
    else:
        raise ValueError(f"Unknown provider: {provider}")


def _score_with_openai(prompt: str) -> QualityScore:
    """Score using OpenAI API."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        data = json.loads(response.choices[0].message.content)
        return QualityScore(
            score=float(data.get("score", 0)),
            feedback=data.get("feedback", ""),
            rule_violations=data.get("rule_violations", []),
        )

    except Exception as e:
        logger.error(f"OpenAI scoring failed: {e}")
        raise


def _score_with_anthropic(prompt: str) -> QualityScore:
    """Score using Anthropic API."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt},
            ],
        )

        # Extract JSON from response
        text = response.content[0].text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        data = json.loads(text.strip())
        return QualityScore(
            score=float(data.get("score", 0)),
            feedback=data.get("feedback", ""),
            rule_violations=data.get("rule_violations", []),
        )

    except Exception as e:
        logger.error(f"Anthropic scoring failed: {e}")
        raise


def score_feed_outputs(
    original_text: str,
    feed_title: str,
    feed_summary: str,
    detail_title: str,
    provider: Literal["openai", "anthropic"] = "openai",
) -> QualityScore:
    """
    Score feed outputs (compressed headlines and summaries) using an LLM.

    Uses a specialized rubric that understands compression constraints.

    Args:
        original_text: The original source article text
        feed_title: The compressed feed title (≤12 words)
        feed_summary: The compressed feed summary (≤100 chars)
        detail_title: The detail page title (≤12 words)
        provider: Which LLM provider to use ("openai" or "anthropic")

    Returns:
        QualityScore with score (0-10), feedback, and rule_violations list
    """
    # Format the feed outputs for scoring
    feed_outputs = f"""FEED TITLE: {feed_title}

FEED SUMMARY: {feed_summary}

DETAIL TITLE: {detail_title}"""

    prompt = FEED_OUTPUTS_SCORING_PROMPT.format(
        rubric=FEED_OUTPUTS_RUBRIC,
        original_text=original_text,
        neutral_text=feed_outputs,
    )

    if provider == "openai":
        return _score_with_openai(prompt)
    elif provider == "anthropic":
        return _score_with_anthropic(prompt)
    else:
        raise ValueError(f"Unknown provider: {provider}")


def score_quality_batch(
    items: List[dict],
    provider: Literal["openai", "anthropic"] = "openai",
) -> List[QualityScore]:
    """
    Score multiple items.

    Args:
        items: List of dicts with original_text, neutral_text, and optional headlines
        provider: Which LLM provider to use

    Returns:
        List of QualityScore results
    """
    results = []
    for item in items:
        try:
            score = score_quality(
                original_text=item["original_text"],
                neutral_text=item["neutral_text"],
                provider=provider,
                original_headline=item.get("original_headline"),
                neutral_headline=item.get("neutral_headline"),
            )
            results.append(score)
        except Exception as e:
            logger.error(f"Failed to score item: {e}")
            results.append(QualityScore(
                score=0.0,
                feedback=f"Scoring failed: {e}",
                rule_violations=[],
            ))
    return results
