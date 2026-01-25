# app/services/neutralizer.py
"""
Neutralization service.

Removes manipulative language and produces:
- Neutral headline (1 line, no hype)
- Neutral summary (2-3 lines max) answering:
  - What happened
  - Why it matters
  - What is known
  - What is uncertain
- Transparency spans with what was removed/changed and why

The NeutralizerProvider is an abstraction for LLM integration.
A mock provider is included for deterministic testing.
"""

import logging
import os
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app import models
from app.models import PipelineStage, PipelineStatus, SpanAction, SpanReason
from app.storage.factory import get_storage_provider
from app.services.auditor import Auditor, AuditVerdict

logger = logging.getLogger(__name__)

MAX_RETRY_ATTEMPTS = 2  # Max retries for audit failures


def _get_body_from_storage(story: models.StoryRaw) -> Optional[str]:
    """Retrieve body content from object storage."""
    if not story.raw_content_available or not story.raw_content_uri:
        return None
    try:
        storage = get_storage_provider()
        result = storage.download(story.raw_content_uri)
        if result and result.exists:
            return result.content.decode("utf-8")
    except Exception as e:
        logger.warning(f"Failed to retrieve body from storage: {e}")
    return None


# -----------------------------------------------------------------------------
# Data classes
# -----------------------------------------------------------------------------

@dataclass
class TransparencySpan:
    """A span of manipulative content."""
    field: str  # "title", "description", "body"
    start_char: int
    end_char: int
    original_text: str
    action: SpanAction
    reason: SpanReason
    replacement_text: Optional[str] = None


@dataclass
class NeutralizationResult:
    """Result from neutralizing a story."""
    feed_title: str
    feed_summary: str
    detail_title: Optional[str]
    detail_brief: Optional[str]
    detail_full: Optional[str]
    has_manipulative_content: bool
    spans: List[TransparencySpan]
    removed_phrases: List[str] = None  # For legacy compatibility with old neutralize() method


# -----------------------------------------------------------------------------
# Provider abstraction
# -----------------------------------------------------------------------------

@dataclass
class DetailFullResult:
    """Result from filtering an article body (Call 1: Filter & Track)."""
    detail_full: str
    spans: List[TransparencySpan]


class NeutralizerProvider(ABC):
    """Abstract base class for neutralization providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model being used."""
        pass

    @abstractmethod
    def neutralize(
        self,
        title: str,
        description: Optional[str],
        body: Optional[str],
        repair_instructions: Optional[str] = None,
    ) -> NeutralizationResult:
        """
        Neutralize content and return result with spans.

        Args:
            repair_instructions: If provided, additional instructions from auditor
                                 to correct a previous failed attempt.
        """
        pass

    @abstractmethod
    def _neutralize_detail_full(self, body: str) -> DetailFullResult:
        """
        Filter an article body to produce detail_full (Call 1: Filter & Track).

        Uses shared system prompt (article_system_prompt) + filter user prompt
        to remove manipulative language while preserving structure and facts.

        Args:
            body: The original article body text to filter

        Returns:
            DetailFullResult containing:
            - detail_full: The filtered article text
            - spans: List of TransparencySpan objects tracking each change
        """
        pass

    @abstractmethod
    def _neutralize_detail_brief(self, body: str) -> str:
        """
        Synthesize an article body into a neutral brief (Call 2: Synthesize).

        Uses shared system prompt (article_system_prompt) + synthesis user prompt
        to create a 3-5 paragraph prose brief following the implicit structure:
        grounding -> context -> state of knowledge -> uncertainty.

        Args:
            body: The original article body text to synthesize

        Returns:
            detail_brief as plain text string (3-5 paragraphs, no headers/bullets)
        """
        pass

    @abstractmethod
    def _neutralize_feed_outputs(self, body: str, detail_brief: str) -> dict:
        """
        Generate compressed feed outputs (Call 3: Compress).

        Uses shared system prompt (article_system_prompt) + compression user prompt
        to generate three outputs optimized for different display contexts.

        Args:
            body: The original article body text
            detail_brief: The already-generated detail brief (for context)

        Returns:
            dict with:
            - feed_title: Short headline (50-60 chars, max 65)
            - feed_summary: 2 sentence preview (90-105 chars, soft max 115)
            - detail_title: Precise headline for article page
        """
        pass


# -----------------------------------------------------------------------------
# Mock provider for testing
# -----------------------------------------------------------------------------

# Manipulative patterns to detect (for mock)
MANIPULATIVE_PATTERNS = {
    SpanReason.CLICKBAIT: [
        r'\b(shocking|unbelievable|you won\'t believe|mind-blowing|jaw-dropping)\b',
        r'\b(must see|must read|can\'t miss|don\'t miss)\b',
        r'\b(secret|hidden|exposed|revealed)\b',
        r'\b(stunning|explosive|bombshell)\b',
    ],
    SpanReason.URGENCY_INFLATION: [
        r'\b(breaking|urgent|just in|developing|happening now)\b',
        r'\b(alert|emergency|crisis|chaos)\b',
        r'\b(grinds to a halt|comes to a standstill|at a standstill)\b',
        r'\b(huge delays|massive delays|major delays)\b',
        r'\bROAD CLOSED\b',  # All-caps urgency
        r'\b[A-Z]{4,}\s+[A-Z]{4,}\b',  # Consecutive all-caps words (e.g., "ROAD CLOSED")
    ],
    SpanReason.EMOTIONAL_TRIGGER: [
        r'\b(outrage|fury|furious|enraged|livid)\b',
        r'\b(slams|blasts|destroys|demolishes|eviscerates)\b',
        r'\b(heartbreaking|devastating|horrifying|terrifying)\b',
        r'\b(horror|nightmare|nightmare scenario)\b',
        r'\bhorror\s+\w+\b',  # "horror smash", "horror crash", etc.
        r'\b(sparking|sparks|sparked)\s+(huge|massive|widespread|major)\b',
    ],
    SpanReason.SELLING: [
        r'\b(exclusive|insider|behind the scenes)\b',
        r'\b(viral|trending|everyone is talking)\b',
    ],
    SpanReason.AGENDA_SIGNALING: [
        r'\b(radical|extremist|dangerous)\b',
        r'\b(the truth about|what they don\'t want you to know)\b',
    ],
    SpanReason.RHETORICAL_FRAMING: [
        r'\b(some say|critics say|experts warn)\b',
        r'\b(could|might|may|potentially)\s+(be\s+)?(devastating|catastrophic|huge)\b',
    ],
}

# Replacements for common patterns
REPLACEMENTS = {
    'shocking': 'notable',
    'slams': 'criticizes',
    'blasts': 'criticizes',
    'destroys': 'challenges',
    'demolishes': 'disputes',
    'furious': 'concerned',
    'outrage': 'disagreement',
    'breaking': '',
    'urgent': '',
    'just in': '',
    'must see': '',
    'must read': '',
    'horror': '',
    'nightmare': '',
    'stunning': 'notable',
    'explosive': '',
    'bombshell': '',
    'grinds to a halt': 'stops',
    'comes to a standstill': 'stops',
    'huge delays': 'delays',
    'massive delays': 'delays',
    'major delays': 'delays',
    'road closed': 'road closure',
}


class MockNeutralizerProvider(NeutralizerProvider):
    """
    Deterministic mock provider for testing.
    Uses pattern matching to detect and replace manipulative language.
    """

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-v1"

    def _find_spans(self, text: str, field: str) -> List[TransparencySpan]:
        """Find manipulative spans in text."""
        if not text:
            return []

        spans = []
        text_lower = text.lower()

        for reason, patterns in MANIPULATIVE_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, text_lower, re.IGNORECASE):
                    original = text[match.start():match.end()]
                    replacement = REPLACEMENTS.get(original.lower())

                    if replacement is not None:
                        action = SpanAction.REPLACED if replacement else SpanAction.REMOVED
                    else:
                        action = SpanAction.SOFTENED
                        replacement = None

                    spans.append(TransparencySpan(
                        field=field,
                        start_char=match.start(),
                        end_char=match.end(),
                        original_text=original,
                        action=action,
                        reason=reason,
                        replacement_text=replacement,
                    ))

        # Sort by position and remove overlaps
        spans.sort(key=lambda s: s.start_char)
        non_overlapping = []
        last_end = -1
        for span in spans:
            if span.start_char >= last_end:
                non_overlapping.append(span)
                last_end = span.end_char

        return non_overlapping

    def _neutralize_text(self, text: str, spans: List[TransparencySpan]) -> str:
        """Apply span replacements to text."""
        if not spans:
            return text

        result = []
        last_end = 0

        for span in sorted(spans, key=lambda s: s.start_char):
            # Add text before this span
            result.append(text[last_end:span.start_char])

            # Add replacement (or nothing if removed)
            if span.replacement_text:
                result.append(span.replacement_text)

            last_end = span.end_char

        # Add remaining text
        result.append(text[last_end:])

        # Clean up extra spaces
        neutralized = ' '.join(''.join(result).split())
        return neutralized

    def neutralize(
        self,
        title: str,
        description: Optional[str],
        body: Optional[str],
        repair_instructions: Optional[str] = None,
    ) -> NeutralizationResult:
        """Neutralize content using pattern matching."""
        # Note: repair_instructions ignored in mock provider
        # Find spans in each field
        title_spans = self._find_spans(title, "title")
        desc_spans = self._find_spans(description or "", "description") if description else []
        body_spans = self._find_spans(body or "", "body") if body else []

        all_spans = title_spans + desc_spans + body_spans
        has_manipulative = len(all_spans) > 0

        # Neutralize title
        neutral_headline = self._neutralize_text(title, title_spans)
        # Ensure no trailing punctuation issues
        neutral_headline = neutral_headline.strip().rstrip(':').strip()

        # Neutralize description for summary
        neutral_desc = self._neutralize_text(description or "", desc_spans) if description else ""

        # Build summary (2-3 lines max)
        if neutral_desc:
            neutral_summary = neutral_desc[:500]
        elif body:
            neutral_body = self._neutralize_text(body, body_spans)
            neutral_summary = neutral_body[:500]
        else:
            neutral_summary = neutral_headline

        # Truncate to 2-3 sentences
        sentences = re.split(r'(?<=[.!?])\s+', neutral_summary)
        neutral_summary = ' '.join(sentences[:3])

        return NeutralizationResult(
            feed_title=neutral_headline,
            feed_summary=neutral_summary,
            detail_title=None,  # Not generated by mock provider
            detail_brief=None,  # Not generated by mock provider
            detail_full=None,   # Not generated by mock provider
            has_manipulative_content=has_manipulative,
            spans=all_spans,
            removed_phrases=[s.original_text for s in all_spans],  # Extract from spans
        )

    def _neutralize_detail_full(self, body: str) -> DetailFullResult:
        """
        Filter an article body using pattern matching (mock implementation).

        Uses the same pattern matching logic as neutralize() but focused on body text.
        """
        if not body:
            return DetailFullResult(detail_full="", spans=[])

        # Find spans in body
        body_spans = self._find_spans(body, "body")

        # Apply neutralization
        filtered_body = self._neutralize_text(body, body_spans)

        return DetailFullResult(
            detail_full=filtered_body,
            spans=body_spans,
        )

    def _neutralize_detail_brief(self, body: str) -> str:
        """
        Synthesize an article body into a brief (mock implementation).

        Creates a simple 3-paragraph summary by extracting key sentences.
        This is a deterministic mock for testing purposes.
        """
        if not body:
            return ""

        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', body.strip())
        if not sentences:
            return ""

        # Filter out very short sentences and apply neutralization
        body_spans = self._find_spans(body, "body")
        filtered_body = self._neutralize_text(body, body_spans)
        filtered_sentences = re.split(r'(?<=[.!?])\s+', filtered_body.strip())
        filtered_sentences = [s for s in filtered_sentences if len(s) > 20]

        if not filtered_sentences:
            return filtered_body[:500] if filtered_body else ""

        # Build 3-paragraph brief
        paragraphs = []

        # Paragraph 1: Grounding (first 2-3 sentences)
        grounding = ' '.join(filtered_sentences[:min(3, len(filtered_sentences))])
        paragraphs.append(grounding)

        # Paragraph 2: Context (next 2-3 sentences if available)
        if len(filtered_sentences) > 3:
            context = ' '.join(filtered_sentences[3:min(6, len(filtered_sentences))])
            paragraphs.append(context)

        # Paragraph 3: Remaining (if available)
        if len(filtered_sentences) > 6:
            remaining = ' '.join(filtered_sentences[6:min(9, len(filtered_sentences))])
            paragraphs.append(remaining)

        return '\n\n'.join(paragraphs)

    def _neutralize_feed_outputs(self, body: str, detail_brief: str) -> dict:
        """
        Generate compressed feed outputs (mock implementation).

        Creates simple feed outputs by extracting from the original content.
        This is a deterministic mock for testing purposes.
        """
        if not body and not detail_brief:
            return {
                "feed_title": "",
                "feed_summary": "",
                "detail_title": "",
                "section": "world",
            }

        # Use detail_brief if available, otherwise use body
        source = detail_brief or body or ""

        # Split into sentences for processing
        sentences = re.split(r'(?<=[.!?])\s+', source.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        # Apply neutralization to the source
        body_spans = self._find_spans(source, "body")
        filtered_source = self._neutralize_text(source, body_spans)
        filtered_sentences = re.split(r'(?<=[.!?])\s+', filtered_source.strip())
        filtered_sentences = [s.strip() for s in filtered_sentences if s.strip()]

        # Generate feed_title: Extract key phrase from first sentence, max 12 words
        feed_title = ""
        if filtered_sentences:
            first_sentence = filtered_sentences[0]
            words = first_sentence.split()
            # Take first 6-12 words, stopping at natural break
            feed_title_words = words[:min(6, len(words))]
            feed_title = ' '.join(feed_title_words)
            # Remove trailing punctuation except periods
            feed_title = feed_title.rstrip(',:;')
            if not feed_title.endswith('.'):
                feed_title = feed_title.rstrip('.')

        # Generate feed_summary: First 1-2 sentences, max ~120 chars
        feed_summary = ""
        if filtered_sentences:
            feed_summary = filtered_sentences[0]
            if len(filtered_sentences) > 1 and len(feed_summary) < 60:
                combined = f"{filtered_sentences[0]} {filtered_sentences[1]}"
                if len(combined) <= 120:
                    feed_summary = combined

        # Generate detail_title: Slightly longer version of feed_title
        detail_title = ""
        if filtered_sentences:
            first_sentence = filtered_sentences[0]
            words = first_sentence.split()
            # Take up to 15 words for detail_title
            detail_title_words = words[:min(15, len(words))]
            detail_title = ' '.join(detail_title_words)
            # Clean up punctuation
            detail_title = detail_title.rstrip(',:;')

        return {
            "feed_title": feed_title,
            "feed_summary": feed_summary,
            "detail_title": detail_title,
            "section": "world",  # Mock always returns world (LLM providers do real classification)
        }


# -----------------------------------------------------------------------------
# Shared prompts (used by all LLM providers)
# -----------------------------------------------------------------------------

# Default prompts (fallback if DB is empty or unavailable)

# Article System Prompt - The shared DNA for all 3 generation calls
# Contains: All A1-D4 canon rules, manipulation patterns, content spec constraints
DEFAULT_ARTICLE_SYSTEM_PROMPT = """You are the NTRL neutralization filter.

NTRL is not a publisher, explainer, or editor. It is a FILTER.
Your role is to REMOVE manipulative language while preserving all facts, tension, conflict, and uncertainty exactly as they exist in the source.

Neutrality is discipline, not balance.
Clarity is achieved through removal, not replacement.

═══════════════════════════════════════════════════════════════════════════════
CANON RULES (Priority Order - Higher overrides lower)
═══════════════════════════════════════════════════════════════════════════════

A. MEANING PRESERVATION (Highest Priority)
──────────────────────────────────────────
A1: No new facts may be introduced
A2: Facts may not be removed if doing so changes meaning
A3: Factual scope and quantifiers must be preserved (all/some/many/few)
A4: Compound factual terms are atomic (e.g., "domestic abuse", "sex work" - do not alter)
A5: Epistemic certainty must be preserved exactly (alleged, confirmed, suspected, etc.)
A6: Causal facts are not motives (report cause without inferring intent)

B. NEUTRALITY ENFORCEMENT
──────────────────────────────────────────
B1: Remove urgency framing (BREAKING, JUST IN, developing, happening now)
B2: Remove emotional amplification (shocking, terrifying, devastating, outrage)
B3: Remove agenda or ideological signaling UNLESS quoted and attributed
B4: Remove conflict theater language (slams, blasts, destroys, eviscerates, rips)
B5: Remove implied judgment (controversial, embattled, troubled, disgraced - unless factual)

C. ATTRIBUTION & AGENCY SAFETY
──────────────────────────────────────────
C1: No inferred ownership or affiliation (don't say "his company" unless explicitly stated)
C2: No possessive constructions involving named individuals unless explicit in source
C3: No inferred intent or purpose (report actions, not assumed motivations)
C4: Attribution must be preserved (who said it, who claims it, who reported it)

D. STRUCTURAL & MECHANICAL CONSTRAINTS (Lowest Priority)
──────────────────────────────────────────
D1: Grammar must be intact
D2: No ALL-CAPS emphasis except acronyms (FBI, NATO, CEO)
D3: Headlines must be ≤12 words
D4: Neutral tone throughout

═══════════════════════════════════════════════════════════════════════════════
MANIPULATION PATTERNS TO REMOVE
═══════════════════════════════════════════════════════════════════════════════

1. CLICKBAIT
   - "You won't believe...", "What happened next...", "shocking", "mind-blowing"
   - "Must see", "must read", "can't miss", "don't miss"
   - "Secret", "hidden", "exposed", "revealed"
   - ALL CAPS for emphasis, excessive punctuation (!!, ?!)

2. URGENCY INFLATION
   - "BREAKING" (when not actually breaking), "JUST IN", "DEVELOPING"
   - "Alert", "emergency", "crisis", "chaos" (when exaggerated)
   - False time pressure

3. EMOTIONAL TRIGGERS
   - Conflict theater: "slams", "destroys", "eviscerates", "blasts", "rips", "torches"
   - Fear amplifiers: "terrifying", "alarming", "chilling", "horrifying"
   - Outrage bait: "shocking", "disgusting", "unbelievable", "insane"
   - Empathy exploitation: "heartbreaking", "devastating"

4. AGENDA SIGNALING
   - "Finally", "Long overdue", loaded adjectives without evidence
   - Scare quotes around legitimate terms
   - "Radical", "extremist", "dangerous" without factual basis
   - "The truth about...", "What they don't want you to know"

5. RHETORICAL MANIPULATION
   - Leading questions ("Is this the end of...?")
   - False equivalence
   - "Some say", "critics say", "experts warn" (without attribution)
   - Weasel words that imply consensus without evidence

6. SELLING LANGUAGE
   - "Must-read", "Essential", "Exclusive", "Insider"
   - Superlatives without evidence ("biggest", "worst", "most important")
   - "Viral", "trending", "everyone is talking about"

═══════════════════════════════════════════════════════════════════════════════
CONTENT OUTPUT SPECIFICATIONS
═══════════════════════════════════════════════════════════════════════════════

FEED TITLE (feed_title)
- Purpose: Fast scanning in feed (must fit 2 lines at all text sizes)
- Length: 50-60 characters, MAXIMUM 65 characters (hard cap)
- Content: Factual, neutral, descriptive
- Avoid: Emotional language, urgency, clickbait, questions, teasers

FEED SUMMARY (feed_summary)
- Purpose: Lightweight context (fits ~3 lines)
- Length: 90-105 characters, soft max 115 characters
- 2 complete sentences with substance

DETAIL TITLE (detail_title)
- Purpose: Precise headline on article page
- May be longer and more precise than feed_title
- Neutral, complete, factual
- Not auto-derived from feed_title

DETAIL BRIEF (detail_brief)
- Purpose: The core NTRL reading experience
- Length: 3-5 short paragraphs maximum
- Format: NO section headers, bullets, dividers, or calls to action
- Tone: Must read as a complete, calm explanation
- Structure (implicit, not labeled): grounding → context → state of knowledge → uncertainty
- Quotes: Only when wording itself is news; must be short, embedded, attributed, non-emotional

DETAIL FULL (detail_full)
- Purpose: Original article with manipulation removed
- Preserve: Full content, structure, quotes, factual detail
- Remove: Manipulative language, urgency inflation, editorial framing, publisher cruft

═══════════════════════════════════════════════════════════════════════════════
PRESERVE EXACTLY
═══════════════════════════════════════════════════════════════════════════════
- All facts, names, dates, numbers, places, statistics
- Direct quotes with attribution
- Real tension, conflict, and uncertainty (these are news, not manipulation)
- Original structure where possible
- Epistemic markers (alleged, suspected, confirmed, reportedly)

═══════════════════════════════════════════════════════════════════════════════
DO NOT
═══════════════════════════════════════════════════════════════════════════════
- Soften real conflict into blandness
- Add context or explanation not in the original
- Editorialize about significance
- Turn news into opinion
- Infer motives or intent
- Downshift factual severity (don't change "killed" to "shot" if death occurred)

═══════════════════════════════════════════════════════════════════════════════
FINAL PRINCIPLE
═══════════════════════════════════════════════════════════════════════════════
If an output feels calmer but is less true, it fails.
If it feels true but pushes the reader, it fails.
"""

DEFAULT_SYSTEM_PROMPT = """You are a neutral language filter for NTRL.

NTRL is not a publisher, explainer, or editor. It is a filter.
Your role is to REMOVE manipulative language while preserving the original facts,
tension, conflict, and uncertainty exactly as they exist in the source.

Neutrality is discipline, not balance.
Clarity is achieved through removal, not replacement.

REMOVE THESE MANIPULATIVE PATTERNS:

1. CLICKBAIT: "You won't believe...", "What happened next...", ALL CAPS for emphasis, excessive punctuation (!!, ?!)

2. URGENCY INFLATION: "BREAKING" (when not breaking), "JUST IN", "DEVELOPING", false time pressure

3. EMOTIONAL TRIGGERS:
   - Conflict theater: "slams", "destroys", "eviscerates", "blasts", "rips", "torches"
   - Fear amplifiers: "terrifying", "alarming", "chilling"
   - Outrage bait: "shocking", "disgusting", "unbelievable", "insane"

4. AGENDA SIGNALING: "Finally", "Long overdue", loaded adjectives like "controversial" or "embattled" without evidence, scare quotes

5. RHETORICAL MANIPULATION: Leading questions ("Is this the end of...?"), false equivalence

6. SELLING: "Must-read", "Essential", superlatives without evidence

PRESERVE EXACTLY:
- All facts, names, dates, numbers, places
- Direct quotes with attribution
- Real tension, conflict, and uncertainty (these are news, not manipulation)
- The original structure where possible

DO NOT:
- Soften real conflict into blandness
- Add context or explanation not in the original
- Editorialize about significance
- Turn news into summaries"""

DEFAULT_REPAIR_SYSTEM_PROMPT = """You are the NTRL Neutralization Repair Agent.

Goal: Produce a corrected NTRL-neutral JSON output for a story that failed safeguards.
You are a FILTER, not a publisher: remove manipulative language while preserving all facts,
uncertainty, and conflict exactly as stated in the source.

DO NOT:
- Add new facts, context, or interpretation
- Infer motives or implications
- Generalize away key factual specifics
- Soften factual conflict if it is factual

HARD RULES:
1) No rhetorical or leading questions in neutral_headline or neutral_summary (no "?").
2) Core fact integrity: if death is central in the input (killed/dead/death/fatal/shooting death),
   the neutral output must state death plainly (e.g., "killed" or "died"), not merely "shot."
3) Agenda signaling removal: remove evaluative framing like "promotes global order," "bold move," etc.
4) Thin content / newsletter shells: if the input is a newsletter/promo wrapper or lacks enough concrete
   detail to summarize without guessing, return has_manipulative_content: false with unchanged content.

CONSISTENCY CONTRACT (MANDATORY):
- If has_manipulative_content = true:
  • removed_phrases must contain at least 1 item, AND
  • neutral_headline OR neutral_summary must differ from the original.
- If no changes are needed, set has_manipulative_content = false."""

DEFAULT_USER_PROMPT_TEMPLATE = """Filter this news content. Remove manipulative language, preserve everything else.

ORIGINAL TITLE: {title}

ORIGINAL DESCRIPTION: {description}

ORIGINAL BODY: {body}

Respond with JSON:
{{
  "neutral_headline": "The title with manipulative words removed. Keep structure, remove hype.",
  "neutral_summary": "The description with manipulative language removed. Do not summarize - filter.",
  "what_happened": "One sentence: the core fact.",
  "why_it_matters": null,
  "what_is_known": null,
  "what_is_uncertain": null,
  "has_manipulative_content": true or false,
  "removed_phrases": ["list", "of", "phrases", "you", "removed"]
}}

IMPORTANT:
- Filter, don't rewrite. The output should be recognizable as the original minus manipulation.
- If "Senator SLAMS critics" becomes "Senator criticizes critics", you've rewritten.
- It should become "Senator [spoke against] critics" or similar minimal change.
- If content is already neutral, return it unchanged with has_manipulative_content: false.
- NO QUESTION MARKS in neutral_headline or neutral_summary. Convert rhetorical questions to statements.
- If death/killing is central to the story, state it plainly. Do not downshift "killed" to "shot"."""


# -----------------------------------------------------------------------------
# Detail Full Filter Prompt (Call 1: Filter & Track)
# -----------------------------------------------------------------------------

DEFAULT_FILTER_DETAIL_FULL_PROMPT = """Filter the following article to produce a neutralized version.

═══════════════════════════════════════════════════════════════════════════════
YOUR TASK
═══════════════════════════════════════════════════════════════════════════════

You are an aggressive FILTER. Your job is to:
1. AGGRESSIVELY REMOVE all manipulative language (see detailed lists below)
2. PRESERVE facts, quotes, structure, and real conflict
3. TRACK every change you make with transparency spans

This is a neutralization filter, not a light editing pass. If in doubt, REMOVE IT.

═══════════════════════════════════════════════════════════════════════════════
WORDS/PHRASES THAT MUST BE REMOVED (delete entirely or replace)
═══════════════════════════════════════════════════════════════════════════════

URGENCY WORDS (remove entirely, no replacement needed):
- "BREAKING", "BREAKING NEWS", "JUST IN", "DEVELOPING", "LIVE", "UPDATE", "UPDATES"
- "HAPPENING NOW", "ALERT", "URGENT", "EMERGENCY" (unless factual emergency)
- "shocking", "stunning", "dramatic", "explosive"
- Entire phrases like "In a shocking turn of events", "In a stunning announcement"

EMOTIONAL AMPLIFICATION (remove entirely):
- "heartbreaking", "heart-wrenching", "devastating", "catastrophic"
- "terrifying", "horrifying", "alarming", "chilling", "dire"
- "utter devastation", "complete chaos", "total disaster"
- "breathless", "breathtaking", "mind-blowing", "jaw-dropping"
- "outrage", "fury", "livid", "enraged" (unless direct quote)
- "insane", "crazy", "unbelievable", "incredible"
- "game-changer", "revolutionary", "unprecedented" (unless truly unprecedented)

CONFLICT THEATER (replace with neutral verbs):
- "slams" → "criticizes" or "responds to"
- "blasts" → "criticizes"
- "destroys" → "disputes" or "challenges"
- "eviscerates" → "criticizes"
- "rips" → "criticizes"
- "torches" → "criticizes"

CLICKBAIT PHRASES (remove entirely):
- "You won't believe"
- "What happened next"
- "This is huge"
- "Must see", "Must read", "Essential"
- "Here's why"
- "Everything you need to know"
- "Stay tuned"
- "One thing is certain"
- "will never be the same"

AGENDA SIGNALING (remove unless in attributed quote):
- "radical", "radical left", "radical right"
- "dangerous", "extremist" (unless factual designation)
- "disastrous", "failed policies"
- "threatens the fabric of"
- "invasion" (unless military context)

SELLING LANGUAGE (remove entirely):
- "exclusive", "insider", "secret", "revealed", "exposed"
- "viral", "trending", "everyone is talking"
- "undisputed leader", "once again proven"
- "leaves competitors in the dust"

ALL CAPS (convert to lowercase, except acronyms like NATO, FBI, CEO):
- "BREAKING NEWS" → just remove entirely
- "NEWS" → "news" or remove if part of urgency phrase
- Random ALL CAPS words for emphasis → lowercase

═══════════════════════════════════════════════════════════════════════════════
PRESERVE EXACTLY
═══════════════════════════════════════════════════════════════════════════════

- Original paragraph structure and flow
- All direct quotes with their attribution (even if quote contains emotional language)
- All facts, names, dates, numbers, places, statistics
- Real tension, conflict, and uncertainty (these are news, not manipulation)
- Epistemic markers (alleged, suspected, confirmed, reportedly, expected to)
- Causal relationships as stated (don't infer motives)
- Emergency/crisis terminology when it's factual (actual declared emergency)

═══════════════════════════════════════════════════════════════════════════════
DO NOT
═══════════════════════════════════════════════════════════════════════════════

- Add new facts, context, or explanation
- Remove facts even if uncomfortable
- Downshift factual severity ("killed" → "shot" is wrong if death occurred)
- Infer motives or intent beyond what's stated
- Change quoted material (preserve exactly as written, even if manipulative)
- Remove attributed emotional language inside quotes (that's the speaker's words)

═══════════════════════════════════════════════════════════════════════════════
ORIGINAL ARTICLE
═══════════════════════════════════════════════════════════════════════════════

{body}

═══════════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════════════════

Respond with JSON containing:
1. "filtered_article": The complete filtered article text
2. "spans": Array of transparency spans tracking each change

{{
  "filtered_article": "The full article with manipulative language removed...",
  "spans": [
    {{
      "field": "body",
      "start_char": 0,
      "end_char": 8,
      "original_text": "BREAKING",
      "action": "removed",
      "reason": "urgency_inflation"
    }},
    {{
      "field": "body",
      "start_char": 150,
      "end_char": 155,
      "original_text": "slams",
      "action": "replaced",
      "reason": "emotional_trigger",
      "replacement_text": "criticizes"
    }}
  ]
}}

SPAN FIELD DEFINITIONS:
- field: Always "body" for detail_full filtering
- start_char: Character position where original text started (0-indexed)
- end_char: Character position where original text ended
- original_text: The exact text that was changed/removed
- action: One of "removed", "replaced", "softened"
- reason: One of "clickbait", "urgency_inflation", "emotional_trigger", "selling", "agenda_signaling", "rhetorical_framing", "publisher_cruft"
- replacement_text: (Optional) The text that replaced the original, if action is "replaced"

If no changes are needed, return the original article unchanged with an empty spans array."""


# -----------------------------------------------------------------------------
# Detail Brief Synthesis Prompt (Call 2: Synthesize)
# -----------------------------------------------------------------------------

DEFAULT_SYNTHESIS_DETAIL_BRIEF_PROMPT = """Synthesize the following article into a neutral brief.

═══════════════════════════════════════════════════════════════════════════════
PRIME DIRECTIVE
═══════════════════════════════════════════════════════════════════════════════

You are a FILTER, not a writer. Your job is to CONDENSE the original article
into a shorter form while ONLY using information that appears in the source.

Do NOT add:
- Background context
- Historical information
- Industry trends
- Implications or consequences
- Your own analysis or interpretation
- ANYTHING not explicitly stated in the original

═══════════════════════════════════════════════════════════════════════════════
YOUR TASK
═══════════════════════════════════════════════════════════════════════════════

Create a detail_brief: a calm, complete explanation of the story in 3-5 short paragraphs.

This is the CORE NTRL reading experience. The brief must:
1. Inform without pushing
2. Present facts without editorializing
3. Acknowledge uncertainty only where the SOURCE acknowledges it
4. Be SHORTER than the original (condense, don't expand)

═══════════════════════════════════════════════════════════════════════════════
CRITICAL: MEANING PRESERVATION
═══════════════════════════════════════════════════════════════════════════════

You MUST preserve these elements EXACTLY as they appear in the original:

1. SCOPE MARKERS - These quantifiers define factual scope (REQUIRED):
   - "all", "every", "entire", "multiple"
   - If the original says "all retailers" → you MUST write "all retailers"
   - If the original says "Entire villages" → you MUST write "Entire villages" (NOT "villages")
   - If the original says "all 50 Democrats" → you MUST write "all 50 Democrats"
   - If the original says "multiple sources" → you MUST write "multiple sources"
   - NEVER drop, omit, or change these scope words - they are factual precision
   - Scan the original for these words and ensure they appear in your output
   - VERIFY: If "entire" appears in source, "entire" MUST appear in your output

2. CERTAINTY MARKERS - These define epistemic certainty:
   - "expected to", "set to", "plans to", "scheduled to", "poised to"
   - If the original says "expected to be a major issue" → write "expected to be"
   - NEVER substitute: "expected to" ≠ "anticipated to" ≠ "likely to"
   - Use the EXACT phrasing from the source

3. FACTUAL DETAILS - Names, numbers, dates, statistics, places
   - Copy these EXACTLY from the original
   - Do NOT round, estimate, or paraphrase numbers

═══════════════════════════════════════════════════════════════════════════════
CRITICAL: NO NEW FACTS
═══════════════════════════════════════════════════════════════════════════════

ONLY include information that appears in the original article.

FORBIDDEN:
- Adding background context not in the original (no drought, no challenges, no trends)
- Explaining why something matters (unless the original does)
- Describing trends or patterns not mentioned
- Adding interpretive phrases like "amid growing concerns" unless quoted
- Inferring implications or consequences not stated
- Speculating about uncertainties not mentioned in the original
- Adding information about "long-term effects" or "implementation" not in source

CRITICAL: If the original article is SHORT, your brief must also be SHORT.
- A 3-paragraph original → 2-3 paragraph brief (NOT 4 paragraphs)
- Do NOT pad with general knowledge, assumed context, or speculation
- If there's nothing to say about "uncertainty", don't add an uncertainty paragraph
- The brief should be SMALLER than the original, not larger

EXPLICIT PROHIBITIONS - The following are NEVER acceptable in your narrative:
- "ongoing efforts" - unless quoted from source
- "sustainability" / "conservation" / "management" context - unless in original
- "remain to be seen" / "remains to be seen" - do not use this phrase
- "may occur" / "could occur" / "are expected to occur" - unless source uses these exact words
- "challenges" / "concerns" / "issues" as added framing - unless quoted or stated in source
- Adding ANY context about trends, background, history, or implications not explicitly in source

═══════════════════════════════════════════════════════════════════════════════
FORMAT REQUIREMENTS
═══════════════════════════════════════════════════════════════════════════════

LENGTH: 3-5 short paragraphs maximum
- Each paragraph should be 2-4 sentences
- Prefer shorter paragraphs over longer ones
- Total word count typically 150-300 words (shorter for short articles)

FORMAT: Plain prose only
- NO section headers (no "What happened:", "Context:", etc.)
- NO bullet points or numbered lists
- NO dividers or horizontal rules
- NO calls to action ("Read more", "Stay tuned")
- NO meta-commentary ("This article discusses...")

═══════════════════════════════════════════════════════════════════════════════
IMPLICIT STRUCTURE (Do NOT label these sections)
═══════════════════════════════════════════════════════════════════════════════

Your brief should flow naturally through these stages WITHOUT labeling them:

1. GROUNDING (Paragraph 1)
   - What happened? Who is involved? Where and when?
   - Lead with the core fact
   - Establish the basic situation clearly

2. CONTEXT (Paragraph 2, only if context is in the original)
   - Background or preceding events mentioned in the article
   - Do NOT add context that isn't in the original

3. STATE OF KNOWLEDGE (Paragraph 3-4)
   - What is confirmed vs. claimed vs. uncertain?
   - Include key statements from officials or involved parties
   - Present different perspectives neutrally if they exist

4. UNCERTAINTY (Final paragraph, if mentioned in original)
   - What remains unknown? (only if stated in original)
   - What happens next (if mentioned)?

═══════════════════════════════════════════════════════════════════════════════
QUOTE RULES
═══════════════════════════════════════════════════════════════════════════════

Direct quotes are allowed ONLY when the wording itself is newsworthy.

When using quotes:
- Keep them SHORT (1 sentence or less, ideally a phrase)
- EMBED them in prose (don't lead with the quote)
- IMMEDIATELY attribute them (who said it)
- AVOID emotional or inflammatory quotes unless the emotion IS the news
- NEVER use quotes just to add color or drama

GOOD: The president called the legislation "dead on arrival" in Congress.
BAD: "This is absolutely devastating for families," said the advocate.

═══════════════════════════════════════════════════════════════════════════════
BANNED LANGUAGE
═══════════════════════════════════════════════════════════════════════════════

Remove these from YOUR narrative (they may appear in quotes):

URGENCY: breaking, developing, just in, emerging, escalating
EMOTIONAL: shocking, devastating, terrifying, unprecedented, historic,
           dramatic, catastrophic, dire, significant (as amplifier)
JUDGMENT: dangerous, reckless, extreme, radical (unless quoted)
VAGUE AMPLIFIERS: significantly, substantially, major (unless quoted)

Use factual language instead:
- "significantly impacted" → state the specific impact
- "unprecedented" → describe what actually happened
- "catastrophic" → use the factual severity from the source

═══════════════════════════════════════════════════════════════════════════════
PRESERVE EXACTLY (Scan original and verify these appear in your output)
═══════════════════════════════════════════════════════════════════════════════

MUST PRESERVE VERBATIM:
- All facts, names, dates, numbers, places, statistics from the original
- SCOPE MARKERS: "all", "every", "entire", "multiple" - if in original, MUST be in output
- CERTAINTY MARKERS: "expected to", "set to", "plans to", "scheduled to", "poised to"
- Epistemic markers: alleged, suspected, confirmed, reportedly
- Attribution: who said it, who claims it
- Real tension and conflict (these are news, not manipulation)

VERIFICATION: Before outputting, scan for these scope words in your brief:
- Does the original have "all"? → Your brief MUST have "all"
- Does the original have "entire"? → Your brief MUST have "entire"
- Does the original have "every"? → Your brief MUST have "every"
- Does the original have "expected to"? → Your brief MUST have "expected to"

═══════════════════════════════════════════════════════════════════════════════
DO NOT
═══════════════════════════════════════════════════════════════════════════════

- Add facts, context, or background not in the original article
- Editorialize about significance or importance
- Downshift factual severity (don't soften "killed" to "harmed")
- Infer motives or intent beyond what's stated
- Use rhetorical questions
- Substitute certainty markers (expected ≠ anticipated ≠ likely)
- Drop scope markers (all, every, entire, multiple)

═══════════════════════════════════════════════════════════════════════════════
ORIGINAL ARTICLE
═══════════════════════════════════════════════════════════════════════════════

{body}

═══════════════════════════════════════════════════════════════════════════════
OUTPUT
═══════════════════════════════════════════════════════════════════════════════

Return ONLY the brief as plain text. No JSON. No markup. No labels.
Just 3-5 paragraphs of neutral prose."""


# -----------------------------------------------------------------------------
# Feed Outputs Compression Prompt (Call 3: Compress)
# -----------------------------------------------------------------------------

DEFAULT_COMPRESSION_FEED_OUTPUTS_PROMPT = """Generate compressed feed outputs from the following article.

═══════════════════════════════════════════════════════════════════════════════
PRIME DIRECTIVE
═══════════════════════════════════════════════════════════════════════════════

You are a COMPRESSION FILTER. You COMPRESS and FILTER - you do NOT add, editorialize, or interpret.
If a marker appears in the source (expected to, plans to, all, entire), it MUST appear in your output.

═══════════════════════════════════════════════════════════════════════════════
YOUR TASK
═══════════════════════════════════════════════════════════════════════════════

Produce three distinct outputs:
1. feed_title: Short headline (55-70 characters, MAXIMUM 75)
2. feed_summary: 2-3 sentences continuing from title (140-160 characters, soft max 175)
3. detail_title: Precise headline (≤12 words MAXIMUM)

These are NOT variations of the same text. Each serves a different cognitive purpose.
The feed_title and feed_summary will display INLINE (summary continues on same line as title ends).

═══════════════════════════════════════════════════════════════════════════════
OUTPUT 1: feed_title (STRICT 75 CHARACTER LIMIT)
═══════════════════════════════════════════════════════════════════════════════

Purpose: Fast scanning and orientation in the feed.

STRICT CONSTRAINTS - TITLE MUST NEVER BE TRUNCATED:
- MAXIMUM 75 characters (count EVERY character including spaces)
- Target 55-70 characters (leave buffer room)
- COUNT YOUR CHARACTERS BEFORE OUTPUTTING

CONTENT RULES:
- Factual, neutral, descriptive
- Lead with the core fact or subject
- Use present tense for ongoing events, past for completed
- PRESERVE epistemic markers: "expected to", "plans to", "set to" → must appear in title if in source
- NO emotional language, urgency, clickbait, questions, or teasers
- NO colons introducing clauses (e.g., "Breaking: X happens")
- NO ALL-CAPS except acronyms (NATO, FBI, CEO)

GOOD: "Apple Expected to Announce New iPhone Feature at Spring Event" (61 chars) ✓
GOOD: "Senate Passes $1.2 Trillion Infrastructure Bill After Week of Debate" (68 chars) ✓
GOOD: "Zelenskyy Warns of European Inaction on Ukraine Aid at Davos" (60 chars) ✓
BAD: "Apple Announces New Feature" (drops "expected to" - VIOLATION)
BAD: "The United States Senate Passes Major Infrastructure Bill with Bipartisan Support After Lengthy Debate" (102 chars - TOO LONG)

═══════════════════════════════════════════════════════════════════════════════
OUTPUT 2: feed_summary (TARGET 160 CHARACTERS)
═══════════════════════════════════════════════════════════════════════════════

Purpose: Provide context and details that CONTINUE from the feed_title. Displays inline after title.

CONSTRAINTS:
- Target 140-160 characters (count EVERY character including spaces and periods)
- Maximum 175 characters (soft limit - some overflow acceptable)
- 2-3 complete sentences with meaningful content
- NO ellipses (...) ever

CRITICAL: NON-REDUNDANCY RULE
- feed_summary MUST NOT repeat the subject or core fact from feed_title
- feed_summary CONTINUES from where the title leaves off
- Think: title = "who/what happened", summary = "context / details / so what"
- If title names a person, summary should NOT start with that person's name
- If title states the main event, summary should NOT restate that event

CONTENT RULES:
- 2-3 sentences providing context, details, and substance
- Include specific details: names, numbers, dates, outcomes, locations
- Factual, neutral tone

GOOD EXAMPLES (title + summary that DON'T repeat):
Title: "Senate Passes $1.2 Trillion Infrastructure Bill After Week of Debate"
Summary: "The vote was 65-35 with bipartisan support. Funds will go to roads, bridges, and broadband expansion over five years." (117 chars) ✓

Title: "Zelenskyy Warns of European Inaction on Ukraine Aid at Davos"
Summary: "Speaking at the World Economic Forum, he criticized delays in military assistance. U.S. leadership changes have added urgency to the appeals." (142 chars) ✓

Title: "Jessie Buckley Supports Paul Mescal After Oscar Snub"
Summary: "'Hamnet' received eight nominations including Best Picture. The film has earned $45 million worldwide since its December release." (128 chars) ✓

Title: "2026 Oscar Nominations Announced Thursday Morning"
Summary: "Brady Corbet's 'The Brutalist' leads with ten nominations. The ceremony is scheduled for March 2nd at the Dolby Theatre." (121 chars) ✓

BAD EXAMPLES (redundant - repeats title):
Title: "Jessie Buckley Supports Paul Mescal" → Summary: "Jessie Buckley reacted to Paul Mescal's snub..." (REPEATS NAME AND EVENT)
Title: "Oscar Nominations Announced" → Summary: "The Oscar nominations were announced Thursday..." (REPEATS EVENT)
Title: "Zelenskyy Warns Leaders" → Summary: "Zelenskyy warned European leaders about..." (REPEATS SUBJECT AND VERB)

═══════════════════════════════════════════════════════════════════════════════
OUTPUT 3: detail_title (≤12 words MAXIMUM)
═══════════════════════════════════════════════════════════════════════════════

Purpose: Precise headline on the article page.

HARD CONSTRAINTS:
- ≤12 words MAXIMUM (NEVER exceed - will be rejected if over)
- COUNT YOUR WORDS BEFORE OUTPUTTING

CONTENT RULES:
- More specific than feed_title (include names, numbers, locations)
- Neutral, complete, factual
- PRESERVE epistemic markers: "expected to", "plans to" → must appear if in source
- PRESERVE scope markers: "all", "entire", "every" → must appear if factually in source
- NO urgency framing, sensational language, or emotional amplifiers
- NO questions or teasers
- NO ALL-CAPS except acronyms

GOOD: "Senate Passes $1.2 Trillion Infrastructure Bill" (7 words)
GOOD: "Apple Expected to Announce AI Feature for iPhone 17" (9 words)
BAD: "U.S. Senate Approves $1.2 Trillion Infrastructure Bill with Bipartisan Support in Historic Vote" (14 words - TOO LONG)

═══════════════════════════════════════════════════════════════════════════════
CRITICAL: MARKER PRESERVATION
═══════════════════════════════════════════════════════════════════════════════

If ANY of these markers appear in the original article, they MUST appear in your outputs:
- EPISTEMIC: "expected to", "plans to", "set to", "reportedly", "allegedly"
- SCOPE: "all", "every", "entire", "multiple"

VERIFICATION STEP: Before outputting, check if source contains these markers.
If source says "expected to", your output MUST say "expected to".
If source says "all", your output MUST say "all".

═══════════════════════════════════════════════════════════════════════════════
BANNED LANGUAGE (applies to all three outputs)
═══════════════════════════════════════════════════════════════════════════════

URGENCY: breaking, developing, just in, emerging, escalating, update, alert
EMOTIONAL: shocking, stunning, devastating, terrifying, unprecedented, historic,
           dramatic, catastrophic, dire, heartbreaking, explosive, massive
CONFLICT THEATER: slams, blasts, destroys, eviscerates, rips, torches
CLICKBAIT: you won't believe, here's why, everything you need to know
SELLING: exclusive, insider, secret, revealed, exposed, viral, trending
JUDGMENT: dangerous, reckless, extreme, radical (unless in attributed quote)
AMPLIFIERS: game-changer, revolutionary, once-in-a-lifetime, monumental

═══════════════════════════════════════════════════════════════════════════════
ORIGINAL ARTICLE
═══════════════════════════════════════════════════════════════════════════════

{body}

═══════════════════════════════════════════════════════════════════════════════
REFERENCE: DETAIL BRIEF (for context, already generated)
═══════════════════════════════════════════════════════════════════════════════

{detail_brief}

═══════════════════════════════════════════════════════════════════════════════
OUTPUT 4: section (REQUIRED)
═══════════════════════════════════════════════════════════════════════════════

Purpose: Categorize this article into one of 5 fixed news sections.

SECTIONS (choose exactly one based on PRIMARY TOPIC):

- "world"      : International/foreign affairs, non-US countries, UN, NATO, EU,
                 foreign governments, international conflicts, global events
                 NOT: US foreign policy (that's "us")

- "us"         : US federal government, Congress, White House, Supreme Court,
                 US elections, federal agencies (FBI, CIA, Pentagon),
                 US foreign policy, national legislation
                 NOT: State/local government (that's "local")

- "local"      : City/municipal government, state-level politics,
                 regional infrastructure, community events, school boards,
                 local courts, zoning, transit
                 NOT: Federal government (that's "us")

- "business"   : Stock markets, corporate earnings, mergers, acquisitions,
                 economic indicators (GDP, inflation), Federal Reserve policy,
                 banking, finance, cryptocurrency
                 INCLUDES: Tech company business performance (earnings, revenue)
                 NOT: Tech products/features (that's "technology")

- "technology" : Tech products, features, platforms, AI/ML, software, hardware,
                 cybersecurity, data privacy, social media platforms,
                 tech industry trends
                 NOT: Tech company earnings (that's "business")

DECISION TREE:
1. Is it about a tech product/feature/platform/AI? → "technology"
2. Is it about business performance, markets, economy? → "business"
3. Is it about US federal government/politics? → "us"
4. Is it about state/municipal government? → "local"
5. Is it about international/foreign affairs? → "world"
6. Still unsure? → "world" (safest default)

EXAMPLES:
- "Apple announces new iPhone feature" → "technology"
- "Apple reports Q4 earnings" → "business"
- "Apple faces EU antitrust probe" → "world"
- "Senate passes infrastructure bill" → "us"
- "City council approves transit plan" → "local"
- "Fed raises interest rates" → "business"
- "Zelenskyy addresses World Economic Forum" → "world"
- "OpenAI releases new AI model" → "technology"

═══════════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════════════════

Respond with JSON containing exactly these four fields:

{{
  "feed_title": "55-70 chars, max 75, NEVER truncated",
  "feed_summary": "140-160 chars, soft max 175, 2-3 sentences, MUST NOT repeat title",
  "detail_title": "≤12 words, more specific than feed_title",
  "section": "world|us|local|business|technology"
}}

BEFORE OUTPUTTING - VERIFY (CRITICAL):
1. feed_title: COUNT EVERY CHARACTER NOW - must be ≤75 (target 55-70)
2. feed_summary: COUNT EVERY CHARACTER NOW - must be ≤175 (target 140-160)
3. feed_summary: Does it repeat the title's subject or event? If yes, REWRITE to continue from title instead
4. detail_title word count: ≤12 words? (count now)
5. Epistemic markers preserved? (check source for "expected to", "plans to")
6. section: Is it one of exactly: world, us, local, business, technology?

If feed_title is over 75 characters, REWRITE IT SHORTER before outputting.
If feed_summary is over 175 characters, REWRITE IT SHORTER before outputting.
If feed_summary repeats the title, REWRITE to add new information instead."""


# -----------------------------------------------------------------------------
# Prompt loading from DB - DB is source of truth for model selection
# -----------------------------------------------------------------------------

_prompt_cache: Dict[str, str] = {}
_prompt_cache_time: Optional[datetime] = None
_active_model_cache: Optional[str] = None
PROMPT_CACHE_TTL_SECONDS = 60  # Refresh from DB every 60 seconds


class NeutralizerConfigError(Exception):
    """Raised when neutralizer is misconfigured (no prompts, no API key, etc.)."""
    pass


def get_active_model() -> str:
    """
    Get the active model from the database.

    The active model is determined by the active system_prompt row.
    Raises NeutralizerConfigError if no active system_prompt found.
    """
    global _active_model_cache, _prompt_cache_time

    # Check if cache is stale
    now = datetime.utcnow()
    if _prompt_cache_time is None or (now - _prompt_cache_time).total_seconds() > PROMPT_CACHE_TTL_SECONDS:
        _active_model_cache = None
        _prompt_cache_time = now

    if _active_model_cache is not None:
        return _active_model_cache

    try:
        from app.database import SessionLocal
        from app import models

        db = SessionLocal()
        try:
            # Find the active system_prompt - its model field determines which model to use
            prompt = db.query(models.Prompt).filter(
                models.Prompt.name == "system_prompt",
                models.Prompt.is_active == True
            ).first()

            if not prompt:
                raise NeutralizerConfigError(
                    "No active system_prompt found in database. "
                    "Please create a prompt via PUT /v1/prompts/system_prompt"
                )

            if not prompt.model:
                raise NeutralizerConfigError(
                    "Active system_prompt has no model specified. "
                    "Please update the prompt with a valid model."
                )

            _active_model_cache = prompt.model
            return prompt.model
        finally:
            db.close()
    except NeutralizerConfigError:
        raise
    except Exception as e:
        raise NeutralizerConfigError(f"Failed to load active model from database: {e}")


def get_prompt(name: str, default: str) -> str:
    """
    Get a prompt from the database for the active model.

    Raises NeutralizerConfigError if no active prompt found.
    Caches prompts for PROMPT_CACHE_TTL_SECONDS to avoid DB hits on every call.
    """
    global _prompt_cache, _prompt_cache_time

    # Get the active model (this also refreshes cache if stale)
    model = get_active_model()

    # Cache key includes model
    cache_key = f"{name}:{model}"

    # Return from cache if available
    if cache_key in _prompt_cache:
        return _prompt_cache[cache_key]

    # Load from DB
    try:
        from app.database import SessionLocal
        from app import models

        db = SessionLocal()
        try:
            prompt = db.query(models.Prompt).filter(
                models.Prompt.name == name,
                models.Prompt.model == model,
                models.Prompt.is_active == True
            ).first()

            if prompt:
                _prompt_cache[cache_key] = prompt.content
                return prompt.content
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Failed to load prompt '{name}' for model '{model}' from DB: {e}")

    # Use default if prompt not found (e.g., user_prompt_template might not be customized)
    _prompt_cache[cache_key] = default
    return default


def clear_prompt_cache() -> None:
    """Clear the prompt cache (called when prompts are updated via API)."""
    global _prompt_cache, _prompt_cache_time, _active_model_cache
    _prompt_cache = {}
    _prompt_cache_time = None
    _active_model_cache = None


def get_system_prompt() -> str:
    """Get the system prompt for neutralization."""
    return get_prompt("system_prompt", DEFAULT_SYSTEM_PROMPT)


def get_article_system_prompt() -> str:
    """
    Get the article system prompt containing all canon rules.

    This is the shared DNA for all 3 generation calls (Filter, Synthesize, Compress).
    Contains: A1-D4 canon rules, manipulation patterns, content spec constraints.

    Retrievable via get_prompt('article_system_prompt').
    """
    return get_prompt("article_system_prompt", DEFAULT_ARTICLE_SYSTEM_PROMPT)


def get_repair_system_prompt() -> str:
    """Get the repair system prompt."""
    return get_prompt("repair_system_prompt", DEFAULT_REPAIR_SYSTEM_PROMPT)


def get_user_prompt_template() -> str:
    """Get the user prompt template."""
    return get_prompt("user_prompt_template", DEFAULT_USER_PROMPT_TEMPLATE)


def get_filter_detail_full_prompt() -> str:
    """
    Get the user prompt template for detail_full generation (Call 1: Filter & Track).

    This prompt instructs the LLM to:
    - Preserve structure, quotes, factual detail
    - Remove manipulation, urgency, editorial framing
    - Output JSON with filtered_article and transparency spans

    Spans include: field, start_char, end_char, original_text, action, reason
    """
    return get_prompt("filter_detail_full_prompt", DEFAULT_FILTER_DETAIL_FULL_PROMPT)


def build_filter_detail_full_prompt(body: str) -> str:
    """
    Build the user prompt for detail_full filtering.

    Args:
        body: The original article body text to filter

    Returns:
        Formatted prompt with article body inserted
    """
    template = get_filter_detail_full_prompt()
    return template.format(body=body or "")


def get_synthesis_detail_brief_prompt() -> str:
    """
    Get the user prompt template for detail_brief generation (Call 2: Synthesize).

    This prompt instructs the LLM to:
    - Generate 3-5 paragraphs of neutral prose
    - Follow implicit structure: grounding → context → knowledge → uncertainty
    - Use quotes only when wording is newsworthy (short, attributed, non-emotional)
    - Output plain text (not JSON)
    """
    return get_prompt("synthesis_detail_brief_prompt", DEFAULT_SYNTHESIS_DETAIL_BRIEF_PROMPT)


def build_synthesis_detail_brief_prompt(body: str) -> str:
    """
    Build the user prompt for detail_brief synthesis.

    Args:
        body: The original article body text to synthesize

    Returns:
        Formatted prompt with article body inserted
    """
    template = get_synthesis_detail_brief_prompt()
    return template.format(body=body or "")


def get_compression_feed_outputs_prompt() -> str:
    """
    Get the user prompt template for feed outputs generation (Call 3: Compress).

    This prompt instructs the LLM to generate:
    - feed_title: 50-60 chars, max 65 chars (must fit 2 lines)
    - feed_summary: 90-105 chars, soft max 115 (fits ~3 lines)
    - detail_title: Longer, precise, neutral headline

    Output is JSON with all 3 fields.
    """
    return get_prompt("compression_feed_outputs_prompt", DEFAULT_COMPRESSION_FEED_OUTPUTS_PROMPT)


def build_compression_feed_outputs_prompt(body: str, detail_brief: str) -> str:
    """
    Build the user prompt for feed outputs compression.

    Args:
        body: The original article body text
        detail_brief: The already-generated detail brief (for context)

    Returns:
        Formatted prompt with article body and detail_brief inserted
    """
    template = get_compression_feed_outputs_prompt()
    return template.format(body=body or "", detail_brief=detail_brief or "")


def build_user_prompt(title: str, description: Optional[str], body: Optional[str]) -> str:
    """Build the user prompt for neutralization using template from DB."""
    template = get_user_prompt_template()
    return template.format(
        title=title,
        description=description or 'N/A',
        body=(body or '')[:3000]
    )


def build_repair_prompt(
    title: str,
    description: Optional[str],
    body: Optional[str],
    repair_instructions: str,
) -> str:
    """Build the repair prompt for failed neutralization attempts."""
    return f"""REPAIR REQUIRED. Previous output failed audit with issues:
{repair_instructions}

Fix these issues in your response.

ORIGINAL TITLE: {title}

ORIGINAL DESCRIPTION: {description or 'N/A'}

ORIGINAL BODY: {(body or '')[:3000]}

Respond with JSON:
{{
  "neutral_headline": "The title with manipulative words removed. NO QUESTIONS.",
  "neutral_summary": "The description filtered. NO QUESTIONS.",
  "what_happened": "One sentence: the core fact.",
  "why_it_matters": null,
  "what_is_known": null,
  "what_is_uncertain": null,
  "has_manipulative_content": true or false,
  "removed_phrases": ["list", "of", "exact", "phrases", "removed"]
}}"""


def parse_llm_response(
    data: dict,
    title: str,
    description: Optional[str],
) -> NeutralizationResult:
    """Parse LLM JSON response into NeutralizationResult."""
    removed_phrases = data.get("removed_phrases", [])
    has_manipulative = data.get("has_manipulative_content", len(removed_phrases) > 0)

    # Map old field names to new ones for backwards compatibility
    feed_title = data.get("feed_title") or data.get("neutral_headline", title)
    feed_summary = data.get("feed_summary") or data.get("neutral_summary", description or title)

    return NeutralizationResult(
        feed_title=feed_title,
        feed_summary=feed_summary,
        detail_title=data.get("detail_title"),
        detail_brief=data.get("detail_brief"),
        detail_full=data.get("detail_full"),
        has_manipulative_content=has_manipulative,
        spans=[],  # Simplified: no granular spans for v1
        removed_phrases=removed_phrases,  # Store for audit consistency check
    )


def _parse_span_action(action: str) -> SpanAction:
    """Parse action string to SpanAction enum."""
    action_lower = action.lower()
    if action_lower == "removed":
        return SpanAction.REMOVED
    elif action_lower == "replaced":
        return SpanAction.REPLACED
    elif action_lower == "softened":
        return SpanAction.SOFTENED
    else:
        return SpanAction.SOFTENED  # Default


def _parse_span_reason(reason: str) -> SpanReason:
    """Parse reason string to SpanReason enum."""
    reason_lower = reason.lower()
    mapping = {
        "clickbait": SpanReason.CLICKBAIT,
        "urgency_inflation": SpanReason.URGENCY_INFLATION,
        "emotional_trigger": SpanReason.EMOTIONAL_TRIGGER,
        "selling": SpanReason.SELLING,
        "agenda_signaling": SpanReason.AGENDA_SIGNALING,
        "rhetorical_framing": SpanReason.RHETORICAL_FRAMING,
        "publisher_cruft": SpanReason.SELLING,  # Map to closest enum
    }
    return mapping.get(reason_lower, SpanReason.RHETORICAL_FRAMING)


def _correct_span_positions(spans: List[TransparencySpan], original_body: str) -> List[TransparencySpan]:
    """
    Correct span positions by searching for original_text in the body.

    LLMs are notoriously bad at computing exact character positions.
    This function finds the actual positions by searching for the original_text.
    """
    if not original_body:
        return spans

    corrected = []
    used_positions = set()  # Track used positions to avoid duplicates

    for span in spans:
        original_text = span.original_text
        if not original_text:
            continue

        # Search for the original_text in the body
        # Start searching from a position near where the LLM said it was
        search_start = max(0, span.start_char - 200)

        # Try exact match first
        pos = original_body.find(original_text, search_start)

        # If not found near expected position, search from beginning
        if pos == -1:
            pos = original_body.find(original_text)

        # If still not found, try case-insensitive search
        if pos == -1:
            lower_body = original_body.lower()
            lower_text = original_text.lower()
            pos = lower_body.find(lower_text, search_start)
            if pos == -1:
                pos = lower_body.find(lower_text)

        if pos != -1 and pos not in used_positions:
            # Found the text - update positions
            corrected.append(TransparencySpan(
                field=span.field,
                start_char=pos,
                end_char=pos + len(original_text),
                original_text=original_text,
                action=span.action,
                reason=span.reason,
                replacement_text=span.replacement_text,
            ))
            used_positions.add(pos)
        else:
            # Could not find text - log and skip
            logger.warning(f"Could not find span text in body: '{original_text[:50]}...'")

    # Sort by position
    corrected.sort(key=lambda s: s.start_char)
    return corrected


def _extract_spans_from_diff(
    original: str,
    filtered: str,
    field: str = "body"
) -> List[TransparencySpan]:
    """
    Compare original and filtered text to find changes the LLM made
    but didn't report in spans array.

    Uses difflib to find actual differences between the original and filtered text.
    This catches changes that the LLM made but forgot to report.

    Args:
        original: Original article body
        filtered: Filtered article body from LLM
        field: Field name for the spans (default "body")

    Returns:
        List of TransparencySpan objects representing detected changes
    """
    import difflib

    if not original or not filtered:
        return []

    spans = []
    matcher = difflib.SequenceMatcher(None, original, filtered, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'replace':
            # Text was changed - this is the most common manipulation fix
            original_text = original[i1:i2]
            replacement_text = filtered[j1:j2]

            # Only track if it's a meaningful change (not just whitespace)
            if original_text.strip() and replacement_text.strip():
                spans.append(TransparencySpan(
                    field=field,
                    start_char=i1,
                    end_char=i2,
                    original_text=original_text,
                    action=SpanAction.REPLACED,
                    reason=SpanReason.EMOTIONAL_MANIPULATION,  # Default, could be refined
                    replacement_text=replacement_text,
                ))
        elif tag == 'delete':
            # Text was removed entirely
            original_text = original[i1:i2]

            # Only track if it's meaningful content
            if original_text.strip():
                spans.append(TransparencySpan(
                    field=field,
                    start_char=i1,
                    end_char=i2,
                    original_text=original_text,
                    action=SpanAction.REMOVED,
                    reason=SpanReason.URGENCY_INFLATION,  # Default for removals
                    replacement_text=None,
                ))

    return spans


def _merge_spans(
    llm_spans: List[TransparencySpan],
    diff_spans: List[TransparencySpan]
) -> List[TransparencySpan]:
    """
    Merge LLM-reported spans with diff-detected spans.

    LLM spans have better reason/action metadata, so prefer them when
    there's overlap. Diff spans catch changes the LLM forgot to report.

    Args:
        llm_spans: Spans reported by the LLM (may have better reasons)
        diff_spans: Spans detected from text diff (guaranteed accurate positions)

    Returns:
        Merged list of spans, deduplicated and sorted by position
    """
    if not diff_spans:
        return llm_spans
    if not llm_spans:
        return diff_spans

    # Index LLM spans by their character ranges for quick lookup
    llm_ranges = {}
    for span in llm_spans:
        llm_ranges[(span.start_char, span.end_char)] = span

    merged = list(llm_spans)  # Start with all LLM spans
    used_positions = {(s.start_char, s.end_char) for s in llm_spans}

    # Add diff spans that don't overlap with LLM spans
    for diff_span in diff_spans:
        key = (diff_span.start_char, diff_span.end_char)
        if key not in used_positions:
            # Check for partial overlap
            overlaps = False
            for llm_start, llm_end in used_positions:
                # Check if ranges overlap
                if not (diff_span.end_char <= llm_start or diff_span.start_char >= llm_end):
                    overlaps = True
                    break

            if not overlaps:
                merged.append(diff_span)
                used_positions.add(key)

    # Sort by position
    merged.sort(key=lambda s: s.start_char)
    return merged


def _validate_neutralization(original: str, filtered: str) -> bool:
    """
    Verify that filtered text is actually different from original.
    If they're too similar (>98%), neutralization likely failed silently.

    Args:
        original: Original article body
        filtered: Filtered article body

    Returns:
        True if neutralization appears to have worked, False if it looks unchanged
    """
    import difflib

    if not original or not filtered:
        return True  # Edge case - can't validate empty content

    # Quick length check first
    if original == filtered:
        logger.warning("Neutralization validation FAILED: filtered == original (exact match)")
        return False

    # Use SequenceMatcher for similarity ratio
    ratio = difflib.SequenceMatcher(None, original, filtered, autojunk=False).ratio()

    if ratio > 0.98:
        logger.warning(f"Neutralization validation WARNING: ratio={ratio:.3f} - text nearly unchanged")
        return False

    if ratio > 0.95:
        logger.info(f"Neutralization ratio {ratio:.3f} - minimal changes detected")

    return True


def _convert_v2_detection_to_transparency_span(detection) -> TransparencySpan:
    """
    Convert a V2 DetectionInstance to a V1 TransparencySpan.

    This enables using the more reliable V2 ntrl-scan detection
    for transparency spans in the V1 pipeline.

    Args:
        detection: DetectionInstance from ntrl-scan

    Returns:
        TransparencySpan for V1 transparency display
    """
    from app.services.ntrl_scan.types import SpanAction as V2SpanAction

    # Map V2 SpanAction to V1 SpanAction
    action_mapping = {
        V2SpanAction.REMOVE: SpanAction.REMOVED,
        V2SpanAction.REPLACE: SpanAction.REPLACED,
        V2SpanAction.REWRITE: SpanAction.SOFTENED,
        V2SpanAction.ANNOTATE: SpanAction.SOFTENED,
        V2SpanAction.PRESERVE: SpanAction.SOFTENED,
    }

    # Map V2 type categories to V1 SpanReason based on taxonomy
    # Categories: A=Attention, B=Emotional, C=Cognitive, D=Linguistic, E=Structural, F=Incentive
    def map_type_to_reason(type_id: str) -> SpanReason:
        if not type_id:
            return SpanReason.RHETORICAL_FRAMING
        category = type_id.split('.')[0] if '.' in type_id else type_id[0]
        category_mapping = {
            'A': SpanReason.URGENCY_INFLATION,  # Attention/clickbait
            'B': SpanReason.EMOTIONAL_MANIPULATION,  # Emotional
            'C': SpanReason.RHETORICAL_FRAMING,  # Cognitive
            'D': SpanReason.RHETORICAL_FRAMING,  # Linguistic
            'E': SpanReason.RHETORICAL_FRAMING,  # Structural
            'F': SpanReason.AGENDA_SIGNALING,  # Incentive/meta
        }
        return category_mapping.get(category.upper(), SpanReason.RHETORICAL_FRAMING)

    action = action_mapping.get(detection.recommended_action, SpanAction.SOFTENED)
    reason = map_type_to_reason(detection.type_id_primary)

    return TransparencySpan(
        field="body",
        start_char=detection.span_start,
        end_char=detection.span_end,
        original_text=detection.text,
        action=action,
        reason=reason,
        replacement_text=None,  # V2 doesn't provide replacement text
    )


async def _enhance_spans_with_v2_scan_async(
    original_body: str,
    llm_spans: List[TransparencySpan]
) -> List[TransparencySpan]:
    """
    Async implementation of V2 ntrl-scan span enhancement.

    V2 ntrl-scan uses regex patterns and spaCy NLP for precise detection
    that doesn't rely on LLM self-reporting (which is unreliable).

    Args:
        original_body: The original article body (before neutralization)
        llm_spans: Spans reported by the LLM

    Returns:
        Merged spans combining LLM and V2 detection
    """
    from app.services.ntrl_scan.scanner import NTRLScanner, ScannerConfig
    from app.services.ntrl_scan.types import ArticleSegment

    if not original_body:
        return llm_spans

    try:
        # Use fast mode (no semantic detector) to avoid adding latency
        config = ScannerConfig(
            enable_lexical=True,
            enable_structural=True,
            enable_semantic=False,  # Skip semantic to keep it fast
        )
        scanner = NTRLScanner(config)
        scan_result = await scanner.scan(original_body, ArticleSegment.BODY)

        if not scan_result.spans:
            return llm_spans

        # Convert V2 detections to V1 spans
        v2_spans = [
            _convert_v2_detection_to_transparency_span(detection)
            for detection in scan_result.spans
        ]

        # Log enhancement
        if v2_spans and not llm_spans:
            logger.info(
                f"V2 ntrl-scan detected {len(v2_spans)} spans, LLM reported 0 - using V2 spans"
            )
        elif v2_spans and len(v2_spans) > len(llm_spans):
            logger.info(
                f"V2 ntrl-scan detected {len(v2_spans)} spans, LLM reported {len(llm_spans)} - merging"
            )

        # Merge LLM and V2 spans (V2 has accurate positions, LLM may have better reasons)
        return _merge_spans(llm_spans, v2_spans)

    except Exception as e:
        logger.warning(f"V2 ntrl-scan enhancement failed: {e} - using LLM spans only")
        return llm_spans


def _enhance_spans_with_v2_scan(
    original_body: str,
    llm_spans: List[TransparencySpan]
) -> List[TransparencySpan]:
    """
    Enhance LLM-reported spans with V2 ntrl-scan detection.

    Synchronous wrapper around the async implementation. Properly handles
    cases where an event loop is already running (e.g., in FastAPI context).

    Args:
        original_body: The original article body (before neutralization)
        llm_spans: Spans reported by the LLM

    Returns:
        Merged spans combining LLM and V2 detection
    """
    import asyncio

    try:
        # Try to get current event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an async context (e.g., FastAPI) - create a new loop in thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    _enhance_spans_with_v2_scan_async(original_body, llm_spans)
                )
                return future.result(timeout=10)
        else:
            # No running loop - use asyncio.run
            return asyncio.run(_enhance_spans_with_v2_scan_async(original_body, llm_spans))
    except RuntimeError:
        # No event loop exists - create one
        return asyncio.run(_enhance_spans_with_v2_scan_async(original_body, llm_spans))
    except Exception as e:
        logger.warning(f"V2 ntrl-scan sync wrapper failed: {e} - using LLM spans only")
        return llm_spans


class NeutralizationResponseError(Exception):
    """Raised when LLM response is missing required fields."""
    pass


def parse_detail_full_response(data: dict, original_body: str) -> DetailFullResult:
    """
    Parse LLM JSON response for detail_full filtering into DetailFullResult.

    CRITICAL: This function NO LONGER silently falls back to original_body.
    If the LLM response is missing 'filtered_article', it raises an exception
    so the caller can retry or handle the error appropriately.

    Args:
        data: Parsed JSON dict from LLM with filtered_article and spans
        original_body: Original body text (used for span detection, NOT fallback)

    Returns:
        DetailFullResult with filtered article and transparency spans

    Raises:
        NeutralizationResponseError: If LLM response is missing 'filtered_article'
    """
    # CRITICAL FIX: Do NOT silently fall back to original_body
    # This was the root cause of full view showing non-neutralized content
    filtered_article = data.get("filtered_article")

    if filtered_article is None:
        logger.error(
            "LLM response missing 'filtered_article' key - this is a critical error. "
            f"Available keys: {list(data.keys())}"
        )
        raise NeutralizationResponseError(
            "LLM response missing 'filtered_article' - cannot silently return original"
        )

    # Parse LLM-reported spans
    spans_data = data.get("spans", [])
    llm_spans = []
    for span_data in spans_data:
        try:
            span = TransparencySpan(
                field=span_data.get("field", "body"),
                start_char=span_data.get("start_char", 0),
                end_char=span_data.get("end_char", 0),
                original_text=span_data.get("original_text", ""),
                action=_parse_span_action(span_data.get("action", "softened")),
                reason=_parse_span_reason(span_data.get("reason", "rhetorical_framing")),
                replacement_text=span_data.get("replacement_text"),
            )
            llm_spans.append(span)
        except Exception as e:
            logger.warning(f"Failed to parse span: {e}")
            continue

    # Correct LLM span positions by searching for actual text in body
    corrected_llm_spans = _correct_span_positions(llm_spans, original_body)

    # CRITICAL FIX: Extract spans from actual diff to catch changes LLM didn't report
    # LLMs frequently return empty spans arrays even when they made changes
    diff_spans = _extract_spans_from_diff(original_body, filtered_article)

    if diff_spans and not corrected_llm_spans:
        logger.info(
            f"LLM reported 0 spans but diff detected {len(diff_spans)} changes - "
            "using diff-extracted spans"
        )
    elif diff_spans and len(diff_spans) > len(corrected_llm_spans):
        logger.info(
            f"LLM reported {len(corrected_llm_spans)} spans, "
            f"diff detected {len(diff_spans)} - merging"
        )

    # Merge LLM spans with diff-detected spans (catches what LLM missed)
    merged_spans = _merge_spans(corrected_llm_spans, diff_spans)

    # Validate that neutralization actually happened
    if not _validate_neutralization(original_body, filtered_article):
        # CRITICAL FIX: If LLM returned text unchanged, raise error to trigger retry
        # This catches cases where LLM returns original text as 'filtered_article'
        # The retry may use different sampling or eventually fall back to mock provider
        raise NeutralizationResponseError(
            "Neutralization validation failed - filtered text nearly identical to original. "
            "LLM did not properly neutralize the content."
        )

    return DetailFullResult(
        detail_full=filtered_article,
        spans=merged_spans,
    )


# -----------------------------------------------------------------------------
# OpenAI provider
# -----------------------------------------------------------------------------

class OpenAINeutralizerProvider(NeutralizerProvider):
    """OpenAI-based neutralizer (GPT-4o-mini, GPT-4o, etc.)."""

    def __init__(self, model: str = "gpt-4o-mini"):
        self._model = model
        self._api_key = os.getenv("OPENAI_API_KEY")

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    def neutralize(
        self,
        title: str,
        description: Optional[str],
        body: Optional[str],
        repair_instructions: Optional[str] = None,
    ) -> NeutralizationResult:
        """Neutralize using OpenAI API."""
        if not self._api_key:
            logger.warning("No OPENAI_API_KEY set, falling back to mock provider")
            return MockNeutralizerProvider().neutralize(title, description, body, repair_instructions)

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self._api_key)

            if repair_instructions:
                system_prompt = get_repair_system_prompt()
                user_prompt = build_repair_prompt(title, description, body, repair_instructions)
            else:
                system_prompt = get_system_prompt()
                user_prompt = build_user_prompt(title, description, body)

            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            import json
            data = json.loads(response.choices[0].message.content)
            return parse_llm_response(data, title, description)

        except Exception as e:
            logger.error(f"OpenAI neutralization failed: {e}")
            return MockNeutralizerProvider().neutralize(title, description, body)

    def _neutralize_detail_full(self, body: str, retry_count: int = 0) -> DetailFullResult:
        """
        Filter an article body using OpenAI (Call 1: Filter & Track).

        Uses shared article_system_prompt + filter_detail_full_prompt.
        Includes retry logic for transient failures and response parsing errors.
        """
        MAX_RETRIES = 2

        if not body:
            return DetailFullResult(detail_full="", spans=[])

        if not self._api_key:
            logger.warning("No OPENAI_API_KEY set, falling back to mock provider")
            return MockNeutralizerProvider()._neutralize_detail_full(body)

        try:
            import json
            from openai import OpenAI
            client = OpenAI(api_key=self._api_key)

            system_prompt = get_article_system_prompt()
            user_prompt = build_filter_detail_full_prompt(body)

            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            data = json.loads(response.choices[0].message.content)
            return parse_detail_full_response(data, body)

        except NeutralizationResponseError as e:
            # LLM response missing required fields - retry with explicit instructions
            if retry_count < MAX_RETRIES:
                logger.warning(
                    f"OpenAI response missing 'filtered_article' (attempt {retry_count + 1}/{MAX_RETRIES + 1}), retrying..."
                )
                return self._neutralize_detail_full(body, retry_count + 1)
            else:
                logger.error(
                    f"OpenAI detail_full failed after {MAX_RETRIES + 1} attempts: {e}. "
                    "Falling back to mock provider."
                )
                return MockNeutralizerProvider()._neutralize_detail_full(body)

        except json.JSONDecodeError as e:
            # JSON parsing failed - retry
            if retry_count < MAX_RETRIES:
                logger.warning(
                    f"OpenAI returned invalid JSON (attempt {retry_count + 1}/{MAX_RETRIES + 1}), retrying..."
                )
                return self._neutralize_detail_full(body, retry_count + 1)
            else:
                logger.error(f"OpenAI JSON parse failed after {MAX_RETRIES + 1} attempts: {e}")
                return MockNeutralizerProvider()._neutralize_detail_full(body)

        except Exception as e:
            # API error, timeout, rate limit - retry once
            if retry_count < MAX_RETRIES:
                logger.warning(
                    f"OpenAI API error (attempt {retry_count + 1}/{MAX_RETRIES + 1}): {e}, retrying..."
                )
                import time
                time.sleep(1)  # Brief backoff before retry
                return self._neutralize_detail_full(body, retry_count + 1)
            else:
                logger.error(
                    f"OpenAI detail_full neutralization failed after {MAX_RETRIES + 1} attempts: {e}"
                )
                return MockNeutralizerProvider()._neutralize_detail_full(body)

    def _neutralize_detail_brief(self, body: str) -> str:
        """
        Synthesize an article body into a brief using OpenAI (Call 2: Synthesize).

        Uses shared article_system_prompt + synthesis_detail_brief_prompt.
        Returns plain text (3-5 paragraphs, no headers or bullets).
        """
        if not body:
            return ""

        if not self._api_key:
            logger.warning("No OPENAI_API_KEY set, falling back to mock provider")
            return MockNeutralizerProvider()._neutralize_detail_brief(body)

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self._api_key)

            system_prompt = get_article_system_prompt()
            user_prompt = build_synthesis_detail_brief_prompt(body)

            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                # Note: No JSON response format - we want plain text
            )

            # Return plain text response
            return response.choices[0].message.content.strip()

        except Exception as e:
            logger.error(f"OpenAI detail_brief synthesis failed: {e}")
            return MockNeutralizerProvider()._neutralize_detail_brief(body)

    def _neutralize_feed_outputs(self, body: str, detail_brief: str) -> dict:
        """
        Generate compressed feed outputs using OpenAI (Call 3: Compress).

        Uses shared article_system_prompt + compression_feed_outputs_prompt.
        Returns dict with feed_title, feed_summary, detail_title.
        """
        if not body and not detail_brief:
            return {
                "feed_title": "",
                "feed_summary": "",
                "detail_title": "",
                "section": "world",
            }

        if not self._api_key:
            logger.warning("No OPENAI_API_KEY set, falling back to mock provider")
            return MockNeutralizerProvider()._neutralize_feed_outputs(body, detail_brief)

        try:
            import json
            from openai import OpenAI
            client = OpenAI(api_key=self._api_key)

            system_prompt = get_article_system_prompt()
            user_prompt = build_compression_feed_outputs_prompt(body, detail_brief)

            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            data = json.loads(response.choices[0].message.content)
            return {
                "feed_title": data.get("feed_title", ""),
                "feed_summary": data.get("feed_summary", ""),
                "detail_title": data.get("detail_title", ""),
                "section": data.get("section", "world"),
            }

        except Exception as e:
            logger.error(f"OpenAI feed outputs compression failed: {e}")
            return MockNeutralizerProvider()._neutralize_feed_outputs(body, detail_brief)


# -----------------------------------------------------------------------------
# Gemini provider
# -----------------------------------------------------------------------------

class GeminiNeutralizerProvider(NeutralizerProvider):
    """Google Gemini-based neutralizer (Gemini 1.5 Flash, Gemini 2.0 Flash, etc.)."""

    # Available Gemini models
    MODELS = {
        "gemini-1.5-flash": "gemini-1.5-flash",
        "gemini-1.5-flash-latest": "gemini-1.5-flash-latest",
        "gemini-1.5-pro": "gemini-1.5-pro",
        "gemini-2.0-flash": "gemini-2.0-flash-exp",
        "gemini-2.0-flash-exp": "gemini-2.0-flash-exp",
    }

    def __init__(self, model: str = "gemini-1.5-flash"):
        self._model = self.MODELS.get(model, model)
        self._api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    def neutralize(
        self,
        title: str,
        description: Optional[str],
        body: Optional[str],
        repair_instructions: Optional[str] = None,
    ) -> NeutralizationResult:
        """Neutralize using Google Gemini API."""
        if not self._api_key:
            logger.warning("No GOOGLE_API_KEY or GEMINI_API_KEY set, falling back to mock provider")
            return MockNeutralizerProvider().neutralize(title, description, body, repair_instructions)

        try:
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)

            # Use proper system instruction (not concatenated prompt)
            if repair_instructions:
                system_prompt = get_repair_system_prompt()
                user_prompt = build_repair_prompt(title, description, body, repair_instructions)
            else:
                system_prompt = get_system_prompt()
                user_prompt = build_user_prompt(title, description, body)

            model = genai.GenerativeModel(
                self._model,
                system_instruction=system_prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.3,
                ),
            )

            response = model.generate_content(user_prompt)

            import json
            data = json.loads(response.text)
            return parse_llm_response(data, title, description)

        except Exception as e:
            logger.error(f"Gemini neutralization failed: {e}")
            return MockNeutralizerProvider().neutralize(title, description, body)

    def _neutralize_detail_full(self, body: str, retry_count: int = 0) -> DetailFullResult:
        """
        Filter an article body using Gemini (Call 1: Filter & Track).

        Uses shared article_system_prompt + filter_detail_full_prompt.
        Includes retry logic for transient failures and response parsing errors.
        """
        MAX_RETRIES = 2

        if not body:
            return DetailFullResult(detail_full="", spans=[])

        if not self._api_key:
            logger.warning("No GOOGLE_API_KEY or GEMINI_API_KEY set, falling back to mock provider")
            return MockNeutralizerProvider()._neutralize_detail_full(body)

        try:
            import json
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)

            system_prompt = get_article_system_prompt()
            user_prompt = build_filter_detail_full_prompt(body)

            model = genai.GenerativeModel(
                self._model,
                system_instruction=system_prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.3,
                ),
            )

            response = model.generate_content(user_prompt)
            data = json.loads(response.text)
            return parse_detail_full_response(data, body)

        except NeutralizationResponseError as e:
            # LLM response missing required fields - retry
            if retry_count < MAX_RETRIES:
                logger.warning(
                    f"Gemini response missing 'filtered_article' (attempt {retry_count + 1}/{MAX_RETRIES + 1}), retrying..."
                )
                return self._neutralize_detail_full(body, retry_count + 1)
            else:
                logger.error(
                    f"Gemini detail_full failed after {MAX_RETRIES + 1} attempts: {e}. "
                    "Falling back to mock provider."
                )
                return MockNeutralizerProvider()._neutralize_detail_full(body)

        except json.JSONDecodeError as e:
            # JSON parsing failed - retry
            if retry_count < MAX_RETRIES:
                logger.warning(
                    f"Gemini returned invalid JSON (attempt {retry_count + 1}/{MAX_RETRIES + 1}), retrying..."
                )
                return self._neutralize_detail_full(body, retry_count + 1)
            else:
                logger.error(f"Gemini JSON parse failed after {MAX_RETRIES + 1} attempts: {e}")
                return MockNeutralizerProvider()._neutralize_detail_full(body)

        except Exception as e:
            # API error, timeout, rate limit - retry once
            if retry_count < MAX_RETRIES:
                logger.warning(
                    f"Gemini API error (attempt {retry_count + 1}/{MAX_RETRIES + 1}): {e}, retrying..."
                )
                import time
                time.sleep(1)  # Brief backoff before retry
                return self._neutralize_detail_full(body, retry_count + 1)
            else:
                logger.error(
                    f"Gemini detail_full neutralization failed after {MAX_RETRIES + 1} attempts: {e}"
                )
                return MockNeutralizerProvider()._neutralize_detail_full(body)

    def _neutralize_detail_brief(self, body: str) -> str:
        """
        Synthesize an article body into a brief using Gemini (Call 2: Synthesize).

        Uses shared article_system_prompt + synthesis_detail_brief_prompt.
        Returns plain text (3-5 paragraphs, no headers or bullets).
        """
        if not body:
            return ""

        if not self._api_key:
            logger.warning("No GOOGLE_API_KEY or GEMINI_API_KEY set, falling back to mock provider")
            return MockNeutralizerProvider()._neutralize_detail_brief(body)

        try:
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)

            system_prompt = get_article_system_prompt()
            user_prompt = build_synthesis_detail_brief_prompt(body)

            model = genai.GenerativeModel(
                self._model,
                system_instruction=system_prompt,
                generation_config=genai.GenerationConfig(
                    # Note: No JSON mime type - we want plain text
                    temperature=0.3,
                ),
            )

            response = model.generate_content(user_prompt)
            return response.text.strip()

        except Exception as e:
            logger.error(f"Gemini detail_brief synthesis failed: {e}")
            return MockNeutralizerProvider()._neutralize_detail_brief(body)

    def _neutralize_feed_outputs(self, body: str, detail_brief: str) -> dict:
        """
        Generate compressed feed outputs using Gemini (Call 3: Compress).

        Uses shared article_system_prompt + compression_feed_outputs_prompt.
        Returns dict with feed_title, feed_summary, detail_title, section.
        """
        if not body and not detail_brief:
            return {
                "feed_title": "",
                "feed_summary": "",
                "detail_title": "",
                "section": "world",
            }

        if not self._api_key:
            logger.warning("No GOOGLE_API_KEY or GEMINI_API_KEY set, falling back to mock provider")
            return MockNeutralizerProvider()._neutralize_feed_outputs(body, detail_brief)

        try:
            import json
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)

            system_prompt = get_article_system_prompt()
            user_prompt = build_compression_feed_outputs_prompt(body, detail_brief)

            model = genai.GenerativeModel(
                self._model,
                system_instruction=system_prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.3,
                ),
            )

            response = model.generate_content(user_prompt)
            data = json.loads(response.text)
            return {
                "feed_title": data.get("feed_title", ""),
                "feed_summary": data.get("feed_summary", ""),
                "detail_title": data.get("detail_title", ""),
                "section": data.get("section", "world"),
            }

        except Exception as e:
            logger.error(f"Gemini feed outputs compression failed: {e}")
            return MockNeutralizerProvider()._neutralize_feed_outputs(body, detail_brief)


# -----------------------------------------------------------------------------
# Anthropic provider
# -----------------------------------------------------------------------------

class AnthropicNeutralizerProvider(NeutralizerProvider):
    """Anthropic Claude-based neutralizer (Claude 3.5 Haiku, Sonnet, etc.)."""

    MODELS = {
        "claude-3-5-haiku": "claude-3-5-haiku-latest",
        "claude-3-5-sonnet": "claude-3-5-sonnet-latest",
        "claude-3-haiku": "claude-3-haiku-20240307",
    }

    def __init__(self, model: str = "claude-3-5-haiku"):
        self._model = self.MODELS.get(model, model)
        self._api_key = os.getenv("ANTHROPIC_API_KEY")

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model

    def neutralize(
        self,
        title: str,
        description: Optional[str],
        body: Optional[str],
        repair_instructions: Optional[str] = None,
    ) -> NeutralizationResult:
        """Neutralize using Anthropic Claude API."""
        if not self._api_key:
            logger.warning("No ANTHROPIC_API_KEY set, falling back to mock provider")
            return MockNeutralizerProvider().neutralize(title, description, body, repair_instructions)

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self._api_key)

            if repair_instructions:
                system_prompt = get_repair_system_prompt()
                user_prompt = build_repair_prompt(title, description, body, repair_instructions)
            else:
                system_prompt = get_system_prompt()
                user_prompt = build_user_prompt(title, description, body)

            response = client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt},
                ],
            )

            import json
            # Claude returns text, need to extract JSON
            text = response.content[0].text
            # Handle potential markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            data = json.loads(text.strip())
            return parse_llm_response(data, title, description)

        except Exception as e:
            logger.error(f"Anthropic neutralization failed: {e}")
            return MockNeutralizerProvider().neutralize(title, description, body)

    def _neutralize_detail_full(self, body: str, retry_count: int = 0) -> DetailFullResult:
        """
        Filter an article body using Anthropic Claude (Call 1: Filter & Track).

        Uses shared article_system_prompt + filter_detail_full_prompt.
        Includes retry logic for transient failures and response parsing errors.
        """
        MAX_RETRIES = 2

        if not body:
            return DetailFullResult(detail_full="", spans=[])

        if not self._api_key:
            logger.warning("No ANTHROPIC_API_KEY set, falling back to mock provider")
            return MockNeutralizerProvider()._neutralize_detail_full(body)

        try:
            import json
            import anthropic
            client = anthropic.Anthropic(api_key=self._api_key)

            system_prompt = get_article_system_prompt()
            user_prompt = build_filter_detail_full_prompt(body)

            response = client.messages.create(
                model=self._model,
                max_tokens=4096,  # Larger max for full article filtering
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt},
                ],
            )

            # Claude returns text, need to extract JSON
            text = response.content[0].text
            # Handle potential markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            data = json.loads(text.strip())
            return parse_detail_full_response(data, body)

        except NeutralizationResponseError as e:
            # LLM response missing required fields - retry
            if retry_count < MAX_RETRIES:
                logger.warning(
                    f"Anthropic response missing 'filtered_article' (attempt {retry_count + 1}/{MAX_RETRIES + 1}), retrying..."
                )
                return self._neutralize_detail_full(body, retry_count + 1)
            else:
                logger.error(
                    f"Anthropic detail_full failed after {MAX_RETRIES + 1} attempts: {e}. "
                    "Falling back to mock provider."
                )
                return MockNeutralizerProvider()._neutralize_detail_full(body)

        except json.JSONDecodeError as e:
            # JSON parsing failed - retry
            if retry_count < MAX_RETRIES:
                logger.warning(
                    f"Anthropic returned invalid JSON (attempt {retry_count + 1}/{MAX_RETRIES + 1}), retrying..."
                )
                return self._neutralize_detail_full(body, retry_count + 1)
            else:
                logger.error(f"Anthropic JSON parse failed after {MAX_RETRIES + 1} attempts: {e}")
                return MockNeutralizerProvider()._neutralize_detail_full(body)

        except Exception as e:
            # API error, timeout, rate limit - retry once
            if retry_count < MAX_RETRIES:
                logger.warning(
                    f"Anthropic API error (attempt {retry_count + 1}/{MAX_RETRIES + 1}): {e}, retrying..."
                )
                import time
                time.sleep(1)  # Brief backoff before retry
                return self._neutralize_detail_full(body, retry_count + 1)
            else:
                logger.error(
                    f"Anthropic detail_full neutralization failed after {MAX_RETRIES + 1} attempts: {e}"
                )
                return MockNeutralizerProvider()._neutralize_detail_full(body)

    def _neutralize_detail_brief(self, body: str) -> str:
        """
        Synthesize an article body into a brief using Anthropic Claude (Call 2: Synthesize).

        Uses shared article_system_prompt + synthesis_detail_brief_prompt.
        Returns plain text (3-5 paragraphs, no headers or bullets).
        """
        if not body:
            return ""

        if not self._api_key:
            logger.warning("No ANTHROPIC_API_KEY set, falling back to mock provider")
            return MockNeutralizerProvider()._neutralize_detail_brief(body)

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self._api_key)

            system_prompt = get_article_system_prompt()
            user_prompt = build_synthesis_detail_brief_prompt(body)

            response = client.messages.create(
                model=self._model,
                max_tokens=2048,  # Sufficient for 3-5 paragraph brief
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt},
                ],
            )

            # Return plain text response (no JSON parsing needed)
            return response.content[0].text.strip()

        except Exception as e:
            logger.error(f"Anthropic detail_brief synthesis failed: {e}")
            return MockNeutralizerProvider()._neutralize_detail_brief(body)

    def _neutralize_feed_outputs(self, body: str, detail_brief: str) -> dict:
        """
        Generate compressed feed outputs using Anthropic Claude (Call 3: Compress).

        Uses shared article_system_prompt + compression_feed_outputs_prompt.
        Returns dict with feed_title, feed_summary, detail_title, section.
        """
        if not body and not detail_brief:
            return {
                "feed_title": "",
                "feed_summary": "",
                "detail_title": "",
                "section": "world",
            }

        if not self._api_key:
            logger.warning("No ANTHROPIC_API_KEY set, falling back to mock provider")
            return MockNeutralizerProvider()._neutralize_feed_outputs(body, detail_brief)

        try:
            import json
            import anthropic
            client = anthropic.Anthropic(api_key=self._api_key)

            system_prompt = get_article_system_prompt()
            user_prompt = build_compression_feed_outputs_prompt(body, detail_brief)

            response = client.messages.create(
                model=self._model,
                max_tokens=1024,  # Sufficient for feed outputs
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt},
                ],
            )

            # Claude returns text, need to extract JSON
            text = response.content[0].text
            # Handle potential markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            data = json.loads(text.strip())
            return {
                "feed_title": data.get("feed_title", ""),
                "feed_summary": data.get("feed_summary", ""),
                "detail_title": data.get("detail_title", ""),
                "section": data.get("section", "world"),
            }

        except Exception as e:
            logger.error(f"Anthropic feed outputs compression failed: {e}")
            return MockNeutralizerProvider()._neutralize_feed_outputs(body, detail_brief)


# -----------------------------------------------------------------------------
# Provider factory - model determined by active system_prompt in DB
# -----------------------------------------------------------------------------

def _infer_provider_from_model(model: str) -> str:
    """Infer provider name from model string."""
    model_lower = model.lower()

    if model_lower == "mock":
        return "mock"
    elif model_lower.startswith("gpt-") or model_lower.startswith("o1") or model_lower.startswith("o3"):
        return "openai"
    elif model_lower.startswith("gemini"):
        return "gemini"
    elif model_lower.startswith("claude"):
        return "anthropic"
    else:
        raise NeutralizerConfigError(
            f"Unknown model '{model}'. Model must start with 'gpt-', 'gemini', 'claude', or be 'mock'."
        )


# Provider registry - maps provider names to classes
PROVIDERS = {
    "mock": MockNeutralizerProvider,
    "openai": OpenAINeutralizerProvider,
    "gemini": GeminiNeutralizerProvider,
    "anthropic": AnthropicNeutralizerProvider,
}

# API key env var names for each provider
PROVIDER_API_KEYS = {
    "openai": "OPENAI_API_KEY",
    "gemini": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    "anthropic": "ANTHROPIC_API_KEY",
}


def _check_api_key(provider_name: str) -> None:
    """Check that the required API key is set for the provider."""
    if provider_name == "mock":
        return

    key_names = PROVIDER_API_KEYS.get(provider_name)
    if not key_names:
        return

    if isinstance(key_names, str):
        key_names = [key_names]

    for key_name in key_names:
        if os.getenv(key_name):
            return

    raise NeutralizerConfigError(
        f"No API key found for {provider_name}. "
        f"Please set one of: {', '.join(key_names)}"
    )


def get_neutralizer_provider() -> NeutralizerProvider:
    """
    Get the neutralizer provider based on the active system_prompt in the database.

    The model is determined by the 'model' field of the active system_prompt row.
    Provider is inferred from model name (gpt-* -> openai, gemini-* -> gemini, etc.)

    Raises NeutralizerConfigError if:
        - No active system_prompt in database
        - Unknown model name
        - Required API key not set

    Examples:
        system_prompt.model = "gpt-4o-mini"    -> OpenAI GPT-4o-mini
        system_prompt.model = "gemini-2.0-flash" -> Gemini 2.0 Flash
        system_prompt.model = "claude-3-5-haiku" -> Anthropic Claude 3.5 Haiku
        system_prompt.model = "mock"           -> Mock (pattern-based, for testing)
    """
    # Get the active model from DB
    model = get_active_model()

    # Infer provider from model name
    provider_name = _infer_provider_from_model(model)

    # Check API key is configured
    _check_api_key(provider_name)

    if provider_name == "mock":
        return MockNeutralizerProvider()

    provider_class = PROVIDERS.get(provider_name)
    if not provider_class:
        raise NeutralizerConfigError(f"Unknown provider '{provider_name}'")

    return provider_class(model=model)


class NeutralizerService:
    """Service for neutralizing stories."""

    def __init__(self, provider: Optional[NeutralizerProvider] = None):
        self.provider = provider or get_neutralizer_provider()

    def _log_pipeline(
        self,
        db: Session,
        stage: PipelineStage,
        status: PipelineStatus,
        story_raw_id: Optional[uuid.UUID] = None,
        started_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> models.PipelineLog:
        """Create a pipeline log entry."""
        now = datetime.utcnow()
        duration_ms = None
        if started_at:
            duration_ms = int((now - started_at).total_seconds() * 1000)

        log = models.PipelineLog(
            id=uuid.uuid4(),
            stage=stage.value,
            status=status.value,
            story_raw_id=story_raw_id,
            started_at=started_at or now,
            finished_at=now,
            duration_ms=duration_ms,
            error_message=error_message,
            metadata=metadata,
        )
        db.add(log)
        return log

    def neutralize_story(
        self,
        db: Session,
        story: models.StoryRaw,
        force: bool = False,
    ) -> Optional[models.StoryNeutralized]:
        """
        Neutralize a single story using the 3-call pipeline with audit validation.

        Pipeline:
        1. Call 1: Filter & Track - produces detail_full and transparency spans
        2. Call 2: Synthesize - produces detail_brief (3-5 paragraphs)
        3. Call 3: Compress - produces feed_title, feed_summary, detail_title
        4. Audit output against NTRL rules
        5. Retry if audit fails (up to MAX_RETRY_ATTEMPTS)

        Args:
            story: The raw story to neutralize
            force: Re-neutralize even if already done

        Returns:
            The neutralized story record, or None if skipped/failed
        """
        started_at = datetime.utcnow()

        # Check if already neutralized
        existing = (
            db.query(models.StoryNeutralized)
            .filter(
                models.StoryNeutralized.story_raw_id == story.id,
                models.StoryNeutralized.is_current == True,
            )
            .first()
        )

        if existing and not force:
            self._log_pipeline(
                db,
                stage=PipelineStage.NEUTRALIZE,
                status=PipelineStatus.SKIPPED,
                story_raw_id=story.id,
                started_at=started_at,
                metadata={'reason': 'already_neutralized'},
            )
            return None

        try:
            # Fetch body from storage
            body = _get_body_from_storage(story)

            # Initialize auditor
            auditor = Auditor()
            audit_result = None
            detail_full_result = None
            detail_brief = None
            feed_outputs = None
            transparency_spans: List[TransparencySpan] = []

            # Run the 3-call pipeline with retry loop for audit
            for attempt in range(MAX_RETRY_ATTEMPTS + 1):
                # Call 1: Filter & Track - produces detail_full and spans
                if body:
                    detail_full_result = self.provider._neutralize_detail_full(body)
                    transparency_spans = detail_full_result.spans

                    # CRITICAL FIX: Enhance LLM spans with V2 ntrl-scan detection
                    # LLMs are unreliable at tracking spans - they often return empty arrays
                    # V2 ntrl-scan uses regex + spaCy for precise detection
                    try:
                        enhanced_spans = _enhance_spans_with_v2_scan(body, transparency_spans)
                        if len(enhanced_spans) != len(transparency_spans):
                            logger.info(
                                f"Story {story.id}: V2 scan enhanced spans "
                                f"({len(transparency_spans)} LLM → {len(enhanced_spans)} total)"
                            )
                        transparency_spans = enhanced_spans
                    except Exception as e:
                        logger.warning(f"V2 scan enhancement failed for story {story.id}: {e}")
                        # Continue with LLM spans only
                else:
                    detail_full_result = DetailFullResult(detail_full="", spans=[])
                    transparency_spans = []

                # Call 2: Synthesize - produces detail_brief
                if body:
                    detail_brief = self.provider._neutralize_detail_brief(body)
                else:
                    detail_brief = ""

                # Call 3: Compress - produces feed_title, feed_summary, detail_title, section
                feed_outputs = self.provider._neutralize_feed_outputs(
                    body or "",
                    detail_brief
                )

                # Apply LLM section classification if valid and different from keyword classifier
                llm_section = feed_outputs.get("section", "").lower()
                valid_sections = {s.value for s in models.Section}
                if llm_section in valid_sections and llm_section != story.section:
                    logger.info(
                        f"Story {story.id}: section updated from '{story.section}' to '{llm_section}' (LLM classification)"
                    )
                    story.section = llm_section

                # Determine if content was manipulative (has transparency spans)
                has_manipulative_content = len(transparency_spans) > 0

                # Build model output for audit (use feed_title/feed_summary for current auditor)
                model_output = {
                    "neutral_headline": feed_outputs.get("feed_title", ""),
                    "neutral_summary": feed_outputs.get("feed_summary", ""),
                    "has_manipulative_content": has_manipulative_content,
                    "removed_phrases": [s.original_text for s in transparency_spans],
                }

                # Run audit
                audit_result = auditor.audit(
                    original_title=story.original_title,
                    original_description=story.original_description,
                    original_body=body,
                    model_output=model_output,
                )

                logger.info(f"Story {story.id} audit attempt {attempt + 1}: {audit_result.verdict.value}")

                if audit_result.verdict == AuditVerdict.PASS:
                    break
                elif audit_result.verdict == AuditVerdict.SKIP:
                    # Content should be skipped (thin, promotional, etc.)
                    self._log_pipeline(
                        db,
                        stage=PipelineStage.NEUTRALIZE,
                        status=PipelineStatus.SKIPPED,
                        story_raw_id=story.id,
                        started_at=started_at,
                        metadata={
                            'reason': 'audit_skip',
                            'audit_reasons': [r.code for r in audit_result.reasons],
                        },
                    )
                    return None
                elif audit_result.verdict == AuditVerdict.FAIL:
                    # Permanent failure
                    self._log_pipeline(
                        db,
                        stage=PipelineStage.NEUTRALIZE,
                        status=PipelineStatus.FAILED,
                        story_raw_id=story.id,
                        started_at=started_at,
                        error_message="Audit failed permanently",
                        metadata={
                            'audit_reasons': [r.code for r in audit_result.reasons],
                        },
                    )
                    return None
                elif audit_result.verdict == AuditVerdict.RETRY:
                    if attempt < MAX_RETRY_ATTEMPTS:
                        # For retry, we log and try again (prompts are deterministic, so this is mainly for transient issues)
                        logger.info(f"Retrying neutralization for story {story.id}")
                    else:
                        # Max retries exceeded
                        logger.warning(f"Story {story.id} failed audit after {MAX_RETRY_ATTEMPTS} retries")

            # Determine version
            version = 1
            if existing:
                existing.is_current = False
                version = existing.version + 1

            # Determine if content was manipulative
            has_manipulative_content = len(transparency_spans) > 0

            # Create neutralized record with all 6 outputs
            neutralized = models.StoryNeutralized(
                id=uuid.uuid4(),
                story_raw_id=story.id,
                version=version,
                is_current=True,
                feed_title=feed_outputs.get("feed_title", ""),
                feed_summary=feed_outputs.get("feed_summary", ""),
                detail_title=feed_outputs.get("detail_title"),
                detail_brief=detail_brief,
                detail_full=detail_full_result.detail_full if detail_full_result else None,
                disclosure="Manipulative language removed." if has_manipulative_content else "",
                has_manipulative_content=has_manipulative_content,
                model_name=self.provider.model_name,
                prompt_version="v3",  # Updated for 3-call pipeline
                created_at=datetime.utcnow(),
            )
            db.add(neutralized)
            db.flush()

            # Save transparency spans for detail_full
            for span in transparency_spans:
                span_record = models.TransparencySpan(
                    id=uuid.uuid4(),
                    story_neutralized_id=neutralized.id,
                    field=span.field,
                    start_char=span.start_char,
                    end_char=span.end_char,
                    original_text=span.original_text,
                    action=span.action.value if isinstance(span.action, SpanAction) else span.action,
                    reason=span.reason.value if isinstance(span.reason, SpanReason) else span.reason,
                    replacement_text=span.replacement_text,
                )
                db.add(span_record)

            # Log success
            self._log_pipeline(
                db,
                stage=PipelineStage.NEUTRALIZE,
                status=PipelineStatus.COMPLETED,
                story_raw_id=story.id,
                started_at=started_at,
                metadata={
                    'provider': self.provider.name,
                    'model': self.provider.model_name,
                    'has_manipulative': has_manipulative_content,
                    'audit_verdict': audit_result.verdict.value if audit_result else 'none',
                    'retry_count': attempt if 'attempt' in dir() else 0,
                    'span_count': len(transparency_spans),
                },
            )

            return neutralized

        except Exception as e:
            logger.error(f"Neutralization failed for story {story.id}: {e}")
            self._log_pipeline(
                db,
                stage=PipelineStage.NEUTRALIZE,
                status=PipelineStatus.FAILED,
                story_raw_id=story.id,
                started_at=started_at,
                error_message=str(e),
            )
            raise

    def _neutralize_content(
        self,
        story_id: uuid.UUID,
        title: str,
        description: Optional[str],
        body: Optional[str],
    ) -> Dict[str, Any]:
        """
        Neutralize content using 3-call LLM pipeline (thread-safe, no db operations).

        This method can be called in parallel from multiple threads.
        Uses the 3-call pipeline:
        1. Filter & Track - produces detail_full and transparency spans
        2. Synthesize - produces detail_brief
        3. Compress - produces feed_title, feed_summary, detail_title

        Returns:
            Dict with neutralization result, transparency spans, or error
        """
        from app.services.auditor import Auditor, AuditVerdict

        try:
            auditor = Auditor()
            audit_result = None
            transparency_spans: List[TransparencySpan] = []

            # Run the 3-call pipeline with retry loop for audit
            for attempt in range(MAX_RETRY_ATTEMPTS + 1):
                # Call 1: Filter & Track - produces detail_full and spans
                if body:
                    detail_full_result = self.provider._neutralize_detail_full(body)
                    transparency_spans = detail_full_result.spans

                    # CRITICAL FIX: Enhance LLM spans with V2 ntrl-scan detection
                    # LLMs are unreliable at tracking spans - they often return empty arrays
                    # V2 ntrl-scan uses regex + spaCy for precise detection
                    try:
                        enhanced_spans = _enhance_spans_with_v2_scan(body, transparency_spans)
                        if len(enhanced_spans) != len(transparency_spans):
                            logger.info(
                                f"Story {story_id}: V2 scan enhanced spans "
                                f"({len(transparency_spans)} LLM → {len(enhanced_spans)} total)"
                            )
                        transparency_spans = enhanced_spans
                    except Exception as e:
                        logger.warning(f"V2 scan enhancement failed for story {story_id}: {e}")
                        # Continue with LLM spans only
                else:
                    detail_full_result = DetailFullResult(detail_full="", spans=[])
                    transparency_spans = []

                # Call 2: Synthesize - produces detail_brief
                if body:
                    detail_brief = self.provider._neutralize_detail_brief(body)
                else:
                    detail_brief = ""

                # Call 3: Compress - produces feed_title, feed_summary, detail_title
                feed_outputs = self.provider._neutralize_feed_outputs(
                    body or "",
                    detail_brief
                )

                # Determine if content was manipulative (has transparency spans)
                has_manipulative_content = len(transparency_spans) > 0

                # Build model output for audit
                model_output = {
                    "neutral_headline": feed_outputs.get("feed_title", ""),
                    "neutral_summary": feed_outputs.get("feed_summary", ""),
                    "has_manipulative_content": has_manipulative_content,
                    "removed_phrases": [s.original_text for s in transparency_spans],
                }

                # Run audit
                audit_result = auditor.audit(
                    original_title=title,
                    original_description=description,
                    original_body=body,
                    model_output=model_output,
                )

                logger.info(f"Story {story_id} audit attempt {attempt + 1}: {audit_result.verdict.value}")

                if audit_result.verdict == AuditVerdict.PASS:
                    break
                elif audit_result.verdict == AuditVerdict.SKIP:
                    return {
                        'story_id': story_id,
                        'status': 'skipped',
                        'reason': 'audit_skip',
                        'audit_reasons': [r.code for r in audit_result.reasons],
                    }
                elif audit_result.verdict == AuditVerdict.FAIL:
                    return {
                        'story_id': story_id,
                        'status': 'failed',
                        'error': 'Audit failed permanently',
                        'audit_reasons': [r.code for r in audit_result.reasons],
                    }
                elif audit_result.verdict == AuditVerdict.RETRY:
                    if attempt < MAX_RETRY_ATTEMPTS:
                        logger.info(f"Retrying neutralization for story {story_id}")
                    else:
                        logger.warning(f"Story {story_id} failed audit after {MAX_RETRY_ATTEMPTS} retries")

            # Build NeutralizationResult with all 6 outputs
            result = NeutralizationResult(
                feed_title=feed_outputs.get("feed_title", ""),
                feed_summary=feed_outputs.get("feed_summary", ""),
                detail_title=feed_outputs.get("detail_title"),
                detail_brief=detail_brief,
                detail_full=detail_full_result.detail_full if detail_full_result else None,
                has_manipulative_content=has_manipulative_content,
                spans=transparency_spans,
                removed_phrases=[s.original_text for s in transparency_spans],
            )

            return {
                'story_id': story_id,
                'status': 'completed',
                'result': result,
                'transparency_spans': transparency_spans,  # Include spans for storage
                'audit_verdict': audit_result.verdict.value if audit_result else 'none',
                'retry_count': attempt,
            }

        except Exception as e:
            logger.error(f"Neutralization failed for story {story_id}: {e}")
            return {
                'story_id': story_id,
                'status': 'failed',
                'error': str(e),
            }

    def neutralize_pending(
        self,
        db: Session,
        story_ids: Optional[List[str]] = None,
        force: bool = False,
        limit: int = 50,
        max_workers: int = 5,
    ) -> Dict[str, Any]:
        """
        Neutralize pending stories with parallel processing.

        Args:
            db: Database session
            story_ids: Specific story IDs to process (optional)
            force: Re-neutralize even if already done
            limit: Max stories to process
            max_workers: Number of parallel workers (default: 5)

        Returns:
            Dict with processing results
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        started_at = datetime.utcnow()

        # Get stories to process
        if story_ids:
            # When specific IDs are requested, skip is_duplicate filter
            # (user explicitly wants these stories re-neutralized)
            # Still require body content to be available
            query = db.query(models.StoryRaw).filter(
                models.StoryRaw.raw_content_available == True,
                models.StoryRaw.raw_content_uri.isnot(None),
            )

            # Convert string IDs to UUIDs
            requested_uuids = [uuid.UUID(sid) for sid in story_ids]

            # Check which IDs are StoryRaw IDs
            existing_raw_ids = set(
                row[0] for row in db.query(models.StoryRaw.id)
                .filter(models.StoryRaw.id.in_(requested_uuids))
                .all()
            )

            # For IDs not found in StoryRaw, check if they're StoryNeutralized IDs
            # and get the corresponding story_raw_id
            missing_ids = [uid for uid in requested_uuids if uid not in existing_raw_ids]
            if missing_ids:
                # These might be StoryNeutralized IDs - get the corresponding story_raw_ids
                neutralized_mappings = (
                    db.query(models.StoryNeutralized.story_raw_id)
                    .filter(models.StoryNeutralized.id.in_(missing_ids))
                    .all()
                )
                for mapping in neutralized_mappings:
                    if mapping[0]:  # story_raw_id is not None
                        existing_raw_ids.add(mapping[0])

            query = query.filter(models.StoryRaw.id.in_(existing_raw_ids))
        else:
            # Default query: exclude duplicates, require body content
            query = db.query(models.StoryRaw).filter(
                models.StoryRaw.is_duplicate == False,
                models.StoryRaw.raw_content_available == True,
                models.StoryRaw.raw_content_uri.isnot(None),
            )
            if not force:
                # Only get stories without current neutralization
                subq = (
                    db.query(models.StoryNeutralized.story_raw_id)
                    .filter(models.StoryNeutralized.is_current == True)
                )
                query = query.filter(~models.StoryRaw.id.in_(subq))

        # Prioritize fresh articles - most recent first
        stories = query.order_by(models.StoryRaw.published_at.desc()).limit(limit).all()

        result = {
            'status': 'completed',
            'started_at': started_at,
            'finished_at': None,
            'duration_ms': 0,
            'total_processed': 0,
            'total_skipped': 0,
            'total_failed': 0,
            'skipped_no_body': 0,  # Stories skipped due to missing body content
            'story_results': [],
            'max_workers': max_workers,
        }

        if not stories:
            result['finished_at'] = datetime.utcnow()
            result['duration_ms'] = int((result['finished_at'] - started_at).total_seconds() * 1000)
            return result

        # Prepare data for parallel processing (extract from ORM objects)
        # Skip stories where body is empty/unavailable even after storage check
        story_data = []
        skipped_no_body = 0
        for story in stories:
            body = _get_body_from_storage(story)
            if not body or len(body.strip()) < 100:
                # Skip stories without usable body content
                logger.warning(f"Skipping story {story.id} - no body content available")
                skipped_no_body += 1
                continue
            story_data.append({
                'story_id': story.id,
                'title': story.original_title,
                'description': story.original_description,
                'body': body,
                'story_obj': story,  # Keep reference for db operations
            })

        result['skipped_no_body'] = skipped_no_body

        # Check for existing neutralizations
        existing_map = {}
        if force:
            existing_neutralized = (
                db.query(models.StoryNeutralized)
                .filter(
                    models.StoryNeutralized.story_raw_id.in_([s['story_id'] for s in story_data]),
                    models.StoryNeutralized.is_current == True,
                )
                .all()
            )
            existing_map = {n.story_raw_id: n for n in existing_neutralized}

        # Run LLM calls in parallel
        llm_results = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._neutralize_content,
                    sd['story_id'],
                    sd['title'],
                    sd['description'],
                    sd['body'],
                ): sd['story_id']
                for sd in story_data
            }

            for future in as_completed(futures):
                story_id = futures[future]
                try:
                    llm_result = future.result()
                    llm_results[story_id] = llm_result
                except Exception as e:
                    logger.error(f"Future failed for story {story_id}: {e}")
                    llm_results[story_id] = {
                        'story_id': story_id,
                        'status': 'failed',
                        'error': str(e),
                    }

        # Save results to database (sequential)
        for sd in story_data:
            story_id = sd['story_id']
            story = sd['story_obj']
            llm_result = llm_results.get(story_id, {'status': 'failed', 'error': 'No result'})

            story_result = {
                'story_id': str(story_id),
                'status': llm_result['status'],
                'feed_title': None,
                'has_manipulative_content': False,
                'span_count': 0,
                'error': llm_result.get('error'),
            }

            if llm_result['status'] == 'completed':
                neutralization = llm_result['result']

                # Determine version
                version = 1
                existing = existing_map.get(story_id)
                if existing:
                    existing.is_current = False
                    version = existing.version + 1

                # Create neutralized record
                neutralized = models.StoryNeutralized(
                    id=uuid.uuid4(),
                    story_raw_id=story_id,
                    version=version,
                    is_current=True,
                    feed_title=neutralization.feed_title,
                    feed_summary=neutralization.feed_summary,
                    detail_title=neutralization.detail_title,
                    detail_brief=neutralization.detail_brief,
                    detail_full=neutralization.detail_full,
                    disclosure="Manipulative language removed." if neutralization.has_manipulative_content else "",
                    has_manipulative_content=neutralization.has_manipulative_content,
                    model_name=self.provider.model_name,
                    prompt_version="v3",  # Updated for 3-call pipeline
                    created_at=datetime.utcnow(),
                )
                db.add(neutralized)
                db.flush()  # Flush to get neutralized.id for span FK

                # Save transparency spans
                transparency_spans = llm_result.get('transparency_spans', [])
                for span in transparency_spans:
                    span_record = models.TransparencySpan(
                        id=uuid.uuid4(),
                        story_neutralized_id=neutralized.id,
                        field=span.field,
                        start_char=span.start_char,
                        end_char=span.end_char,
                        original_text=span.original_text,
                        action=span.action.value if isinstance(span.action, SpanAction) else span.action,
                        reason=span.reason.value if isinstance(span.reason, SpanReason) else span.reason,
                        replacement_text=span.replacement_text,
                    )
                    db.add(span_record)

                # Log success
                self._log_pipeline(
                    db,
                    stage=PipelineStage.NEUTRALIZE,
                    status=PipelineStatus.COMPLETED,
                    story_raw_id=story_id,
                    started_at=started_at,
                    metadata={
                        'provider': self.provider.name,
                        'model': self.provider.model_name,
                        'has_manipulative': neutralization.has_manipulative_content,
                        'span_count': len(transparency_spans),
                        'audit_verdict': llm_result.get('audit_verdict', 'none'),
                        'retry_count': llm_result.get('retry_count', 0),
                    },
                )

                story_result['feed_title'] = neutralization.feed_title
                story_result['has_manipulative_content'] = neutralization.has_manipulative_content
                story_result['span_count'] = len(transparency_spans)
                result['total_processed'] += 1

            elif llm_result['status'] == 'skipped':
                self._log_pipeline(
                    db,
                    stage=PipelineStage.NEUTRALIZE,
                    status=PipelineStatus.SKIPPED,
                    story_raw_id=story_id,
                    started_at=started_at,
                    metadata={
                        'reason': llm_result.get('reason', 'unknown'),
                        'audit_reasons': llm_result.get('audit_reasons', []),
                    },
                )
                result['total_skipped'] += 1

            else:  # failed
                self._log_pipeline(
                    db,
                    stage=PipelineStage.NEUTRALIZE,
                    status=PipelineStatus.FAILED,
                    story_raw_id=story_id,
                    started_at=started_at,
                    error_message=llm_result.get('error', 'Unknown error'),
                )
                result['total_failed'] += 1

            result['story_results'].append(story_result)

        db.commit()

        finished_at = datetime.utcnow()
        result['finished_at'] = finished_at
        result['duration_ms'] = int((finished_at - started_at).total_seconds() * 1000)

        if result['total_failed'] > 0 and result['total_processed'] == 0:
            result['status'] = 'failed'
        elif result['total_failed'] > 0:
            result['status'] = 'partial'

        return result
