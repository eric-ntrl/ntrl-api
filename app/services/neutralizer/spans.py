# app/services/neutralizer/spans.py
"""
Span detection and filtering utilities.

Functions for finding manipulative phrase positions in text,
filtering spans inside quoted speech, and removing false positives.
"""

import logging
from typing import List

from app.models import SpanAction, SpanReason

logger = logging.getLogger(__name__)


# Quote character pairs for matching (opening -> closing)
# Using Unicode escapes to ensure curly quotes are correctly defined
QUOTE_PAIRS = {
    '"': '"',           # Straight double quote (U+0022)
    '\u201c': '\u201d', # Curly double quotes: \u201c -> \u201d (U+201C -> U+201D)
    "'": "'",           # Straight single quote (U+0027)
    '\u2018': '\u2019', # Curly single quotes: \u2018 -> \u2019 (U+2018 -> U+2019)
}

# All characters that can open a quote
QUOTE_CHARS_OPEN = set(QUOTE_PAIRS.keys())

# All characters that can close a quote
QUOTE_CHARS_CLOSE = set(QUOTE_PAIRS.values())


# Known false positive EXACT phrases that LLMs commonly flag incorrectly
# Only include multi-word phrases - single words are too likely to have legitimate uses
FALSE_POSITIVE_PHRASES = {
    # Medical terms (multi-word)
    "bowel cancer", "breast cancer", "lung cancer", "skin cancer",
    "prostate cancer", "colon cancer", "cancer treatment", "cancer diagnosis",
    "cancer research", "cancer patient", "cancer patients", "cancer tests",

    # Neutral news verb phrases
    "tests will", "will be", "according to", "reported that",

    # Factual descriptors (multi-word)
    "spot more", "getting worse", "getting better",

    # Temporal phrases
    "every year", "each year", "this week", "last week", "this year", "last year",

    # Data/statistics (multi-word)
    "highest cost", "lowest cost", "most affected", "least affected",

    # UI/metadata (multi-word)
    "minutes ago", "hours ago", "sign up", "read more", "continue reading",
    "health newsletter", "email address",

    # Professional service terms (legitimate professions)
    "crisis management", "reputation management", "crisis manager",
    "public relations", "media relations", "investor relations",
    "communications director", "crisis communications",
    "pr firm", "pr agency", "publicist",
}

# Patterns that match false positives (case-insensitive partial matches)
# Be SPECIFIC to avoid filtering legitimate manipulative language
FALSE_POSITIVE_PATTERNS: list = [
    # Don't use broad patterns like "cancer" - too aggressive
    # Only add very specific false positives here
]


def _parse_span_action(action_str: str) -> SpanAction:
    """Parse a span action string to SpanAction enum."""
    action_map = {
        "removed": SpanAction.REMOVED,
        "remove": SpanAction.REMOVED,
        "replaced": SpanAction.REPLACED,
        "replace": SpanAction.REPLACED,
        "softened": SpanAction.SOFTENED,
        "soften": SpanAction.SOFTENED,
    }
    return action_map.get(action_str.lower(), SpanAction.SOFTENED)


def _parse_span_reason(reason_str: str) -> SpanReason:
    """Parse a span reason string to SpanReason enum."""
    reason_map = {
        "clickbait": SpanReason.CLICKBAIT,
        "urgency_inflation": SpanReason.URGENCY_INFLATION,
        "emotional_trigger": SpanReason.EMOTIONAL_TRIGGER,
        "selling": SpanReason.SELLING,
        "agenda_signaling": SpanReason.AGENDA_SIGNALING,
        "rhetorical_framing": SpanReason.RHETORICAL_FRAMING,
        "editorial_voice": SpanReason.EDITORIAL_VOICE,
    }
    return reason_map.get(reason_str.lower(), SpanReason.RHETORICAL_FRAMING)


def find_phrase_positions(body: str, llm_phrases: list) -> list:
    """
    Find character positions for LLM-identified manipulative phrases.

    This is the position matching step of the hybrid LLM + pattern approach:
    1. LLM identifies phrases with context awareness (no positions)
    2. This function finds exact positions in the original body

    Args:
        body: The original article body text
        llm_phrases: List of dicts from LLM with {phrase, reason, action, replacement}

    Returns:
        List of TransparencySpan objects with accurate character positions
    """
    # Import here to avoid circular import
    from app.services.neutralizer import TransparencySpan

    if not body or not llm_phrases:
        return []

    spans = []
    body_lower = body.lower()

    for phrase_data in llm_phrases:
        phrase = phrase_data.get("phrase", "")
        if not phrase:
            continue

        reason_str = phrase_data.get("reason", "emotional_trigger")
        action_str = phrase_data.get("action", "softened")
        replacement = phrase_data.get("replacement")

        reason = _parse_span_reason(reason_str)
        action = _parse_span_action(action_str)

        # Find all occurrences of the phrase
        start = 0
        phrase_lower = phrase.lower()

        while True:
            # Try exact match first
            pos = body.find(phrase, start)

            # If not found, try case-insensitive
            if pos == -1:
                pos = body_lower.find(phrase_lower, start)
                if pos != -1:
                    phrase = body[pos:pos + len(phrase)]

            if pos == -1:
                break

            spans.append(TransparencySpan(
                field="body",
                start_char=pos,
                end_char=pos + len(phrase),
                original_text=body[pos:pos + len(phrase)],
                action=action,
                reason=reason,
                replacement_text=replacement if action == SpanAction.REPLACED else None,
            ))

            start = pos + 1

    # Sort by position and remove overlaps
    spans.sort(key=lambda s: s.start_char)
    non_overlapping = []
    last_end = -1
    for span in spans:
        if span.start_char >= last_end:
            non_overlapping.append(span)
            last_end = span.end_char

    return non_overlapping


def is_contraction_apostrophe(body: str, pos: int) -> bool:
    """
    Check if apostrophe at position is part of a contraction, not a quote boundary.

    Contractions have letters on both sides of the apostrophe, like:
    won't, can't, don't, it's, he's, they're, I've, I'll, I'd
    """
    if pos <= 0 or pos >= len(body) - 1:
        return False

    char_before = body[pos - 1]
    char_after = body[pos + 1]

    # Core rule: letters on both sides = contraction
    if char_before.isalpha() and char_after.isalpha():
        return True

    return False


def filter_spans_in_quotes(body: str, spans: list) -> list:
    """
    Remove spans that fall inside quotation marks.

    Handles multiple quote types: straight/curly double/single quotes.
    Distinguishes between apostrophes used as quote marks vs contractions.
    """
    if not body or not spans:
        return spans

    # Find all quote boundaries using a stack for nested quotes
    quote_ranges = []
    stack = []

    for i, char in enumerate(body):
        # Skip apostrophes that are part of contractions
        if char in ("'", "\u2019") and is_contraction_apostrophe(body, i):
            continue

        if char in QUOTE_CHARS_OPEN:
            if char in ('"', "'"):
                # Ambiguous quote - toggle behavior
                if stack and stack[-1][0] == char:
                    open_char, start = stack.pop()
                    quote_ranges.append((start, i + 1))
                else:
                    stack.append((char, i))
            else:
                # Unambiguous opening quote (curly open quotes)
                stack.append((char, i))
        elif char in QUOTE_CHARS_CLOSE and char not in QUOTE_CHARS_OPEN:
            # Unambiguous closing quote (curly close quotes)
            if stack:
                open_char, start = stack[-1]
                expected_close = QUOTE_PAIRS.get(open_char)
                if expected_close == char:
                    stack.pop()
                    quote_ranges.append((start, i + 1))

    if not quote_ranges:
        return spans

    # Filter out spans inside quotes
    filtered = []
    for span in spans:
        inside_quote = any(
            start <= span.start_char and span.end_char <= end
            for start, end in quote_ranges
        )
        if not inside_quote:
            filtered.append(span)

    filtered_count = len(spans) - len(filtered)
    if filtered_count > 0:
        logger.info(f"Filtered out {filtered_count} spans inside quotes")

    return filtered


def filter_false_positives(spans: list) -> list:
    """
    Remove known false positive spans that LLMs commonly flag incorrectly.
    """
    logger.debug(f"[SPAN_DETECTION] False positive filter input: {len(spans)} spans")

    if not spans:
        return spans

    filtered = []
    removed_texts = []
    for span in spans:
        text_lower = span.original_text.lower().strip()

        # Check exact matches
        if text_lower in FALSE_POSITIVE_PHRASES:
            removed_texts.append(span.original_text)
            continue

        # Check pattern matches
        is_false_positive = False
        for pattern in FALSE_POSITIVE_PATTERNS:
            if pattern in text_lower:
                is_false_positive = True
                removed_texts.append(span.original_text)
                break

        if not is_false_positive:
            filtered.append(span)

    filtered_count = len(spans) - len(filtered)
    if filtered_count > 0:
        logger.info(f"[SPAN_DETECTION] False positive filter removed {filtered_count}: {removed_texts[:5]}")

    return filtered
