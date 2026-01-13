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

## A. Meaning Preservation (Highest Priority)
- A1: No new facts may be introduced
- A2: Facts may not be removed if doing so changes meaning
- A3: Factual scope and quantifiers must be preserved (all, every, entire, more, multiple)
- A4: Compound factual terms are atomic (e.g., "domestic abuse", "sex work" - cannot split)
- A5: Epistemic certainty must be preserved exactly ("set to", "plans to", "expected to")
- A6: Causal facts are not motives (don't infer why something happened)

## B. Neutrality Enforcement
- B1: Remove urgency framing ("breaking", "just in", "developing")
- B2: Remove emotional amplification ("shocking", "devastating", "terrifying")
- B3: Remove agenda/ideological signaling unless quoted and attributed ("woke", "elite")
- B4: Remove conflict theater language ("slams", "destroys", "eviscerates")
- B5: Remove implied judgment

## C. Attribution & Agency Safety
- C1: No inferred ownership or affiliation
- C2: No possessive constructions involving named individuals unless explicit
- C3: No inferred intent or purpose
- C4: Attribution must be preserved

## D. Structural & Mechanical Constraints
- D1: Grammar must be intact
- D2: No ALL-CAPS emphasis except acronyms
- D3: Headlines must be ≤12 words
- D4: Neutral tone throughout

## Scoring Guidelines
- 10: Perfect neutralization - all rules followed, meaning preserved exactly
- 9: Excellent - minor style issues only, no rule violations
- 8: Good - very minor issues, acceptable for production
- 7: Acceptable - some issues but core meaning preserved
- 6: Borderline - noticeable issues that should be fixed
- 5: Below standard - multiple rule violations
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
            model="claude-3-5-haiku-latest",
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
