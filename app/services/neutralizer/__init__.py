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
from app.config import get_settings
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
    status: str = "success"  # success, failed_llm, failed_garbled, failed_audit
    failure_reason: Optional[str] = None


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

# -----------------------------------------------------------------------------
# Headline System Prompt (for feed outputs - lighter than article system prompt)
# -----------------------------------------------------------------------------

DEFAULT_HEADLINE_SYSTEM_PROMPT = """You are a neutral news headline writer.

Your job is to SYNTHESIZE article content into clear, factual headlines.
NOT to filter or remove words - the article body has already been neutralized.

═══════════════════════════════════════════════════════════════════════════════
CORE PRINCIPLES (Priority Order)
═══════════════════════════════════════════════════════════════════════════════

1. GRAMMATICAL INTEGRITY (Highest Priority)
   - Every output MUST be a complete, readable phrase
   - NEVER leave incomplete sentences or awkward gaps
   - NEVER output: "Senator Tax Bill" (missing verb)
   - ALWAYS output: "Senator Proposes Tax Bill" (complete thought)

2. FACTUAL ACCURACY
   - Preserve who, what, where, when exactly as stated
   - Keep names, numbers, dates, locations intact
   - Preserve epistemic markers: "expected to", "plans to", "reportedly"

3. NEUTRAL TONE
   - Use straightforward language
   - Avoid sensationalism

═══════════════════════════════════════════════════════════════════════════════
TONE GUIDANCE (Prefer, Don't Enforce Strictly)
═══════════════════════════════════════════════════════════════════════════════

When possible, use neutral alternatives:
- "criticizes" over "slams"
- "disputes" over "destroys"
- "addresses" over "blasts"
- "responds to" over "fires back"

CRITICAL: If you cannot find a neutral synonym that fits the character limit,
USE THE ORIGINAL WORD. An awkward word is better than a broken sentence.

═══════════════════════════════════════════════════════════════════════════════
SELF-CHECK BEFORE OUTPUTTING
═══════════════════════════════════════════════════════════════════════════════

Read each output aloud. If it sounds incomplete or awkward, REWRITE IT.

BAD (incomplete): "and Timothée enjoyed a to Cabo" - missing subject and noun
GOOD (complete): "Kylie Jenner and Timothée Chalamet Vacation in Cabo"

BAD (incomplete): "The has initiated an 's platform" - missing proper nouns
GOOD (complete): "European Commission Investigates Elon Musk's Platform"

BAD (incomplete): "the seizure of a of a" - garbled, repeated words
GOOD (complete): "Authorities Seize Narco Sub Carrying Cocaine"

If your output has:
- Missing subjects or verbs
- Dangling prepositions (ending in "to", "of", "a", "the")
- Repeated words ("of a of a")
- Fewer than 3 words in a title

Then REWRITE before outputting."""

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

You are a NEUTRALIZATION FILTER. Your job is to:
1. REMOVE or REPLACE manipulative language (see detailed lists below)
2. PRESERVE facts, quotes, structure, and real conflict
3. TRACK every change you make with transparency spans
4. ENSURE the output remains grammatically correct and readable

═══════════════════════════════════════════════════════════════════════════════
CRITICAL: GRAMMAR PRESERVATION (HIGHEST PRIORITY)
═══════════════════════════════════════════════════════════════════════════════

Your output MUST be grammatically correct, readable prose. Follow these rules:

1. NEVER leave broken sentences - if removing a word breaks grammar, either:
   - Rephrase the sentence to be grammatically complete, OR
   - Keep the word if no clean removal is possible

2. NEVER remove words that leave gaps like:
   - "He attended the at the center" (missing noun)
   - "She was to the event" (missing verb)
   - "The announced that" (missing subject/object)

3. When removing adjectives/adverbs, ensure the sentence still flows:
   - WRONG: "The event was a" → broken
   - RIGHT: "The event was a success" → keep "success"

4. Publisher boilerplate (sign-up prompts, navigation text) should be removed
   as complete blocks, not word-by-word.

5. After EVERY removal, mentally read the sentence - if it sounds broken, fix it.

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

- BREAK GRAMMAR - this is the #1 rule. Never leave incomplete sentences.
- Remove words that leave syntactic gaps (missing subjects, verbs, objects)
- Add new facts, context, or explanation
- Remove facts even if uncomfortable
- Downshift factual severity ("killed" → "shot" is wrong if death occurred)
- Infer motives or intent beyond what's stated
- Change quoted material (preserve exactly as written, even if manipulative)
- Remove attributed emotional language inside quotes (that's the speaker's words)
- Remove individual words from the middle of sentences without rephrasing

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

BEFORE RETURNING, VALIDATE:
1. Read through filtered_article - every sentence must be grammatically complete
2. No sentence should have missing words that make it unreadable
3. The text should flow naturally as if written by a journalist
4. If you find broken sentences, FIX THEM before returning

If no changes are needed, return the original article unchanged with an empty spans array."""


# -----------------------------------------------------------------------------
# Detail Full Synthesis Prompt (NEW: Synthesis approach instead of in-place filtering)
# -----------------------------------------------------------------------------

DEFAULT_SYNTHESIS_DETAIL_FULL_PROMPT = """Rewrite the following article in a neutral tone, preserving full length.

═══════════════════════════════════════════════════════════════════════════════
YOUR TASK
═══════════════════════════════════════════════════════════════════════════════

You are a NEUTRAL REWRITER. Your job is to produce a full-length neutralized
version of the article that:
1. REMOVES manipulative language (urgency, emotional triggers, clickbait)
2. PRESERVES all facts, quotes, structure, and paragraph flow
3. MAINTAINS similar length to the original (NOT shorter)
4. ENSURES perfect grammar and readability

This is NOT summarization - produce a full-length neutral version.

═══════════════════════════════════════════════════════════════════════════════
LANGUAGE TO NEUTRALIZE
═══════════════════════════════════════════════════════════════════════════════

REMOVE OR REPLACE these patterns:

URGENCY (remove entirely, repair surrounding grammar):
- "BREAKING", "BREAKING NEWS", "JUST IN", "DEVELOPING", "LIVE"
- "shocking", "stunning", "dramatic", "explosive"
- Start sentences cleanly without these words

EMOTIONAL AMPLIFICATION (remove and repair):
- "heartbreaking", "devastating", "horrifying", "alarming"
- "breathtaking", "mind-blowing", "jaw-dropping"
- "outrage", "fury", "livid" (unless direct quote)

CONFLICT THEATER (replace with neutral verbs):
- "slams" → "criticizes" or "responds to"
- "blasts" → "criticizes"
- "destroys" → "disputes"
- "eviscerates" → "criticizes"

CLICKBAIT (remove entirely):
- "You won't believe"
- "What happened next"
- "This is huge"
- "Here's why"
- "Everything you need to know"

ALL CAPS (convert to regular case):
- Except acronyms like NATO, FBI, CEO

═══════════════════════════════════════════════════════════════════════════════
PRESERVE EXACTLY
═══════════════════════════════════════════════════════════════════════════════

- Original paragraph structure (same number of paragraphs)
- All direct quotes with their attribution
- All facts, names, dates, numbers, places, statistics
- Real tension and conflict (news, not manipulation)
- Epistemic markers (alleged, suspected, reportedly)

═══════════════════════════════════════════════════════════════════════════════
GRAMMAR RULES (CRITICAL)
═══════════════════════════════════════════════════════════════════════════════

When removing words, ensure sentences remain grammatically complete:

WRONG: "In a development, the president announced..."
RIGHT: "The president announced..." (clean start)

WRONG: "She was to the event..." (missing verb)
RIGHT: "She was invited to the event..." (complete)

After EVERY change, read the sentence - it must sound natural.

═══════════════════════════════════════════════════════════════════════════════
ORIGINAL ARTICLE
═══════════════════════════════════════════════════════════════════════════════

{body}

═══════════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════════════════

Return ONLY the neutralized article text as plain text. No JSON. No metadata.
Just the complete, grammatically correct, neutral article.

The output should be similar in length to the input (full-length, not summarized).
"""


# -----------------------------------------------------------------------------
# Span Detection Prompt (NEW: LLM-based context-aware detection)
# -----------------------------------------------------------------------------

# Minimal system prompt for span detection - defers to detailed user prompt
# This replaces get_article_system_prompt() to avoid conflicting aggressive rules
SPAN_DETECTION_SYSTEM_PROMPT = """You are an expert analyzer identifying manipulative language in news articles.

CRITICAL: Follow the detailed instructions in the user message EXACTLY.
The user message contains all rules, examples, and calibration guidance.
Balance PRECISION with RECALL - flag manipulative language while avoiding false positives."""

# High-recall system prompt for first pass (Claude Haiku)
HIGH_RECALL_SYSTEM_PROMPT = """You are detecting ALL manipulative language in news articles.

CRITICAL: When in doubt, FLAG IT. It's better to flag something borderline than to miss genuine manipulation.
Follow the detailed instructions in the user message for categories and examples.
Prioritize RECALL over PRECISION - catch everything, filtering happens later."""

# Adversarial system prompt for second pass (finds what was missed)
ADVERSARIAL_SYSTEM_PROMPT = """You are a second-pass reviewer finding manipulative phrases that were MISSED by the first analysis.

Your job is to identify manipulation that slipped through the initial detection.
Look for subtle patterns, context-dependent manipulation, and phrases that seem neutral but carry bias.
Be thorough - your role is to catch what others missed."""

DEFAULT_SPAN_DETECTION_PROMPT = """You are a precision-focused media analyst. Your job is to identify manipulative language in news articles while balancing precision with recall.

═══════════════════════════════════════════════════════════════════════════════
WHAT TO FLAG - PRIMARY DETECTION CATEGORIES
═══════════════════════════════════════════════════════════════════════════════

1. URGENCY INFLATION - Creates false sense of immediacy
   FLAG: BREAKING, JUST IN, developing, scrambling, racing, urgent, crisis

2. EMOTIONAL TRIGGERS - Manipulates feelings instead of informing
   FLAG: shocking, devastating, heartbreaking, stunning, dramatic, dire, tragic
   FLAG: slams, blasts, rips, destroys, crushes (when meaning "criticizes")
   FLAG: mind-blowing, incredible, unbelievable, jaw-dropping
   FLAG: ecstatic, elated, overjoyed (exaggerated positive emotions)
   FLAG: outraged, furious, infuriated, livid, seething (exaggerated anger)
   FLAG: devastated, gutted, heartbroken (dramatic emotional states)
   FLAG: stunned, flabbergasted, gobsmacked (surprise amplification)
   FLAG: scathed, unscathed (when editorializing, not literal injury)

3. CLICKBAIT - Teases to get clicks
   FLAG: You won't believe, Here's what happened, The truth about
   FLAG: Stay tuned, What you need to know, This changes everything

4. SELLING/HYPE - Promotes rather than reports
   FLAG: revolutionary, game-changer, groundbreaking, unprecedented
   FLAG: undisputed leader, viral, exclusive, must-see
   FLAG: celeb, celebs (casual celebrity references)
   FLAG: A-list, B-list, D-list (celebrity tier language)
   FLAG: haunts, hotspots (celebrity location slang)
   FLAG: mogul, tycoon, kingpin (hyperbolic titles)
   FLAG: sound the alarm, raise the alarm (manufactured urgency)
   FLAG: whopping, staggering, eye-watering (amplifying numbers)
   FLAG: massive, enormous (when used for emotional effect, not literal size)

5. AGENDA SIGNALING - Politically loaded framing
   FLAG: radical left, radical right, extremist, dangerous (as political label)
   FLAG: invasion (for immigration), crisis (when editorializing)

═══════════════════════════════════════════════════════════════════════════════
SUBTLE MANIPULATION TO CATCH (when used by journalist, not in quotes)
═══════════════════════════════════════════════════════════════════════════════

These are more nuanced patterns. Flag ONLY when used by the journalist (not in quotes):

6. LOADED VERBS (instead of neutral attribution)
   FLAG: "slammed", "blasted", "ripped" (instead of "criticized")
   FLAG: "admits" (implies guilt vs neutral "said")
   FLAG: "claims" (implies doubt vs neutral "states" or "says")
   FLAG: "conceded", "confessed" (implies wrongdoing)

7. URGENCY INFLATION (artificial time pressure)
   FLAG: "BREAKING", "JUST IN", "DEVELOPING" when story is hours old
   FLAG: "You need to see this now", "Before it's too late"
   FLAG: "Act now", "Don't miss out"

8. AGENDA FRAMING (assuming conclusions)
   FLAG: "the crisis at the border" (assuming crisis, not reporting one)
   FLAG: "threatens our way of life" (fear without specifics)
   FLAG: "controversial decision" (when labeling, not reporting controversy)
   NOTE: "some say", "critics argue" are OK if followed by specific attribution

9. SPORTS/EVENT HYPE - Inflated descriptors in sports/entertainment coverage
   FLAG: brilliant, stunning, magnificent, phenomenal, sensational
   FLAG: massive, blockbuster, mega, epic, colossal
   FLAG: beautiful, gorgeous (describing events/matches, not people in quotes)
   NOTE: OK when quoting someone; flag when journalist writes it editorially
   REPLACE: "brilliant form" → "form", "blockbuster year" → "year"
   REPLACE: "beautiful unification clash" → "unification fight"

10. LOADED PERSONAL DESCRIPTORS - Editorial judgments about people's appearance
    FLAG: handsome, beautiful, attractive, gorgeous (describing news subjects)
    FLAG: unfriendly, hostile, menacing, intimidating (describing appearance)
    FLAG: dangerous (as character judgment, not actual physical danger)
    NOTE: These inject opinion into news coverage
    ACTION: remove entirely, or replace with factual descriptor

11. HYPERBOLIC ADJECTIVES - Generic intensifiers that inflate importance
    FLAG: punishing, brutal, devastating, crushing (when not describing literal events)
    FLAG: incredible, unbelievable, extraordinary, remarkable
    FLAG: soaked in blood, drenched in (sensational imagery)
    FLAG: "of the year", "of a generation", "of the century" (superlative inflation)
    REPLACE: "punishing defeat" → "defeat", "incredible performance" → "performance"

12. LOADED IDIOMS - Sensational/violent metaphors for ordinary events
    FLAG: "came under fire" (should be "faced criticism")
    FLAG: "in the crosshairs" (should be "under investigation" or "being scrutinized")
    FLAG: "in hot water" (should be "facing scrutiny")
    FLAG: "took aim at" (should be "criticized")
    FLAG: "on the warpath" (should be "strongly opposing")
    NOTE: These military/violent idioms sensationalize ordinary disagreements

13. ENTERTAINMENT/CELEBRITY HYPE - Romance/lifestyle manipulation in celebrity coverage
    FLAG: "romantic escape", "romantic getaway", "sun-drenched romantic escape"
    FLAG: "looked more in love than ever", "cozied up", "tender moment"
    FLAG: "intimate conversation", "intimate moment", "intimate getaway"
    FLAG: "showed off her toned figure", "showed off his toned physique", "flaunted"
    FLAG: "celebrity hotspot", "beloved Cabo restaurant", "beloved restaurant"
    FLAG: "totally into each other", "visibly smitten", "obsessed with"
    FLAG: "luxurious boat", "luxury yacht", "exclusive resort"
    FLAG: "exclusively revealed", "exclusively reported"
    FLAG: "A-list pair", "A-list couple", "power couple"
    FLAG: "secluded waterfront property", "secluded getaway"
    FLAG: "appeared relaxed and affectionate", "relaxed and affectionate"
    REPLACE: "romantic getaway" → "trip" or "vacation"
    REPLACE: "sun-drenched romantic escape" → "vacation"
    REPLACE: "luxury yacht" → "boat"
    REPLACE: "celebrity hotspot" → "restaurant"
    REPLACE: "showed off her toned figure" → "wore a bikini"
    REPLACE: "appeared relaxed and affectionate" → "spent time together"
    DO NOT FLAG: Direct quotes with attribution
    DO NOT FLAG: "romantic comedy" as genre name (legitimate use)
    DO NOT FLAG: Factual statements like "they are a couple" or "they are dating"

14. EDITORIAL VOICE - First-person opinion markers in news
    FLAG: "we're glad", "we believe", "as it should", "as they should"
    FLAG: "we hope", "we expect", "we think", "we feel"
    FLAG: "naturally", "of course", "obviously" (when editorializing)
    FLAG: "Border Czar" (unofficial, loaded title - use "immigration enforcement lead")
    FLAG: "lunatic", "absurd", "ridiculous" (pejorative descriptors in news)
    FLAG: "faceoff", "faceoffs" (sensationalized conflict language)
    FLAG: "shockwaves", "sent shockwaves" (emotional impact language)
    FLAG: "whirlwind romance", "whirlwind" (romanticized drama)
    FLAG: "completely horrified", "utterly horrified" (amplified emotional states)
    NOTE: These indicate editorial content masquerading as news
    ACTION: Flag with reason "editorial_voice"

═══════════════════════════════════════════════════════════════════════════════
EXCLUSIONS - DO NOT FLAG THESE
═══════════════════════════════════════════════════════════════════════════════

Before flagging any phrase, check if it falls into these categories:

NEVER FLAG - Medical/Scientific Terms:
  "cancer", "bowel cancer", "tumor", "disease", "diagnosis", "mortality"

NEVER FLAG - Neutral News Verbs:
  "tests will", "announced", "reported", "according to", "showed"

NEVER FLAG - Factual Descriptors:
  "spot more", "highest", "lowest", "most", "increasing", "rising"
  "getting worse", "every year", "daily", "this week"

NEVER FLAG - Data/Statistics Language:
  "highest cost", "most affected", "largest increase", "record-breaking"

NEVER FLAG - Quoted Text:
  Anything inside quotation marks (" ")

NEVER FLAG - Literal Meanings:
  "car slams into wall", "bomb blast", "radical surgery"

NEVER FLAG - Professional Terms:
  "crisis management", "reputation management", "crisis manager"
  "public relations", "media relations", "investor relations"
  "communications director", "crisis communications"

If a phrase matches ANY exclusion above, DO NOT include it in your output.

BUT STILL NEVER FLAG (even if matching detection categories):
- Factual statistics even if alarming ("500 dead", "record high")
- Quoted speech (even if manipulative - that's the source, not the journalist)
- Medical/scientific terminology
- Proper nouns and place names
- Direct factual reporting of events

═══════════════════════════════════════════════════════════════════════════════
CRITICAL: NEVER FLAG QUOTED TEXT
═══════════════════════════════════════════════════════════════════════════════

Text inside quotation marks (" ") must NEVER be flagged.
Quotes preserve attribution - readers can judge the speaker's words themselves.

If a phrase appears inside quotes, DO NOT include it in your output.
This applies to ALL quoted speech, regardless of how manipulative the language seems.

The journalist is not endorsing the language - they are reporting what someone said.

═══════════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT - JSON OBJECT WITH PHRASES ARRAY
═══════════════════════════════════════════════════════════════════════════════

Return a JSON object with a "phrases" key containing an array. Include ALL manipulative phrases found in the article, not just the first one.

Format:
{{"phrases": [
  {{"phrase": "EXACT text", "reason": "category", "action": "remove|replace|softened", "replacement": "text or null"}}
]}}

For each phrase:
- phrase: EXACT text from article (case-sensitive, must match exactly)
- reason: clickbait | urgency_inflation | emotional_trigger | selling | agenda_signaling | rhetorical_framing | editorial_voice
- action: remove | replace | softened
- replacement: neutral text if action is "replace", else null

IMPORTANT: Find ALL manipulative phrases in the article, not just one.

═══════════════════════════════════════════════════════════════════════════════
EXAMPLES
═══════════════════════════════════════════════════════════════════════════════

Example 1 - Heavy manipulation:
Input: "BREAKING NEWS - In a shocking turn of events, world leaders are scrambling as the dramatic announcement could have devastating consequences."

Output: {{"phrases": [
  {{"phrase": "BREAKING NEWS", "reason": "urgency_inflation", "action": "remove", "replacement": null}},
  {{"phrase": "shocking", "reason": "emotional_trigger", "action": "remove", "replacement": null}},
  {{"phrase": "scrambling", "reason": "emotional_trigger", "action": "replace", "replacement": "responding"}},
  {{"phrase": "dramatic", "reason": "emotional_trigger", "action": "remove", "replacement": null}},
  {{"phrase": "devastating", "reason": "emotional_trigger", "action": "remove", "replacement": null}}
]}}

Example 2 - Tech hype article:
Input: "Apple's mind-blowing new feature is a game-changer that will revolutionize the industry."

Output: {{"phrases": [
  {{"phrase": "mind-blowing", "reason": "emotional_trigger", "action": "remove", "replacement": null}},
  {{"phrase": "game-changer", "reason": "selling", "action": "remove", "replacement": null}},
  {{"phrase": "revolutionize", "reason": "selling", "action": "replace", "replacement": "change"}}
]}}

Example 3 - Clean article (no manipulation):
Input: "The Federal Reserve announced it would hold interest rates steady at 5.25%, citing stable inflation data."

Output: {{"phrases": []}}

Example 4 - Disaster coverage with emotional framing:
Input: "In scenes of utter devastation that will break your heart, families desperately flee as catastrophic floods ravage the region."

Output: {{"phrases": [
  {{"phrase": "utter devastation", "reason": "emotional_trigger", "action": "remove", "replacement": null}},
  {{"phrase": "will break your heart", "reason": "emotional_trigger", "action": "remove", "replacement": null}},
  {{"phrase": "desperately", "reason": "emotional_trigger", "action": "remove", "replacement": null}},
  {{"phrase": "catastrophic", "reason": "emotional_trigger", "action": "remove", "replacement": null}},
  {{"phrase": "ravage", "reason": "emotional_trigger", "action": "replace", "replacement": "affect"}}
]}}

Example 5 - Quoted speech (DO NOT FLAG):
Input: "Governor Abbott said 'this is an invasion caused by the radical left.'"

Output: {{"phrases": []}}

(Empty array - even though "invasion" and "radical left" are manipulative terms, they appear inside quotes. The journalist is reporting what the Governor said, not endorsing it. Readers can judge the speaker's words themselves.)

Example 6 - Tabloid celebrity article (FLAG these):
Input: "Katie Price's shock fourth marriage sent shockwaves through the showbiz world. Her family were completely horrified when they learned about the whirlwind romance with her new partner."

Output: {{"phrases": [
  {{"phrase": "shock fourth marriage", "reason": "emotional_trigger", "action": "replace", "replacement": "fourth marriage"}},
  {{"phrase": "sent shockwaves", "reason": "emotional_trigger", "action": "remove", "replacement": null}},
  {{"phrase": "showbiz world", "reason": "selling", "action": "replace", "replacement": "entertainment industry"}},
  {{"phrase": "completely horrified", "reason": "emotional_trigger", "action": "replace", "replacement": "surprised"}},
  {{"phrase": "whirlwind romance", "reason": "rhetorical_framing", "action": "replace", "replacement": "relationship"}}
]}}

Why: Tabloid content uses emotional amplification ("shock", "shockwaves", "horrified") and romanticized drama ("whirlwind romance") to manipulate reader emotions. These must be flagged even in celebrity coverage.

Example 7 - Editorial voice in news (FLAG these):
Input: "We're glad to see the Border Czar finally taking action, as it should be. These lunatic faceoffs at the border have gone on too long."

Output: {{"phrases": [
  {{"phrase": "We're glad to see", "reason": "editorial_voice", "action": "remove", "replacement": null}},
  {{"phrase": "Border Czar", "reason": "editorial_voice", "action": "replace", "replacement": "immigration enforcement lead"}},
  {{"phrase": "as it should be", "reason": "editorial_voice", "action": "remove", "replacement": null}},
  {{"phrase": "lunatic faceoffs", "reason": "editorial_voice", "action": "replace", "replacement": "confrontations"}}
]}}

Why: This is opinion/editorial content masquerading as news. "We're glad" and "as it should be" are first-person editorial opinions. "Border Czar" is an unofficial loaded title. "Lunatic" is a pejorative judgment.

Example 9a - Sports/editorial hype (FLAG these):
Input: "Josh Kelly's brilliant form and handsome face will make for a beautiful unification clash in what promises to be a blockbuster year."

Output: {{"phrases": [
  {{"phrase": "brilliant form", "reason": "rhetorical_framing", "action": "replace", "replacement": "form"}},
  {{"phrase": "handsome", "reason": "rhetorical_framing", "action": "remove", "replacement": null}},
  {{"phrase": "beautiful unification clash", "reason": "selling", "action": "replace", "replacement": "unification fight"}},
  {{"phrase": "blockbuster year", "reason": "selling", "action": "replace", "replacement": "year"}}
]}}

Why: These are editorial opinions from the journalist, not facts. "Brilliant" and "handsome" are subjective judgments. "Beautiful clash" and "blockbuster year" are promotional hype.

Example 9b - Boxing article with loaded descriptors:
Input: "The unfriendly-faced boxer delivered a punishing defeat, leaving his opponent soaked in blood after a massive night of boxing."

Output: {{"phrases": [
  {{"phrase": "unfriendly-faced", "reason": "rhetorical_framing", "action": "remove", "replacement": null}},
  {{"phrase": "punishing defeat", "reason": "rhetorical_framing", "action": "replace", "replacement": "defeat"}},
  {{"phrase": "soaked in blood", "reason": "emotional_trigger", "action": "replace", "replacement": "bloodied"}},
  {{"phrase": "massive night", "reason": "selling", "action": "replace", "replacement": "night"}}
]}}

Example 9c - Loaded idioms (FLAG these):
Input: "The senator came under fire and found himself in the crosshairs of critics who took aim at his policy."

Output: {{"phrases": [
  {{"phrase": "came under fire", "reason": "rhetorical_framing", "action": "replace", "replacement": "faced criticism"}},
  {{"phrase": "in the crosshairs", "reason": "rhetorical_framing", "action": "replace", "replacement": "scrutinized by"}},
  {{"phrase": "took aim at", "reason": "rhetorical_framing", "action": "replace", "replacement": "criticized"}}
]}}

Why: These military metaphors sensationalize ordinary political disagreement.

Example 9d - Entertainment/celebrity hype (FLAG these):
Input: "Kylie Jenner and Timothée Chalamet enjoyed a sun-drenched romantic escape in Cabo, where they cozied up at a beloved waterfront restaurant. The couple looked more in love than ever during their intimate getaway."

Output: {{"phrases": [
  {{"phrase": "sun-drenched romantic escape", "reason": "rhetorical_framing", "action": "replace", "replacement": "vacation"}},
  {{"phrase": "cozied up", "reason": "rhetorical_framing", "action": "replace", "replacement": "dined"}},
  {{"phrase": "beloved waterfront restaurant", "reason": "rhetorical_framing", "action": "replace", "replacement": "waterfront restaurant"}},
  {{"phrase": "looked more in love than ever", "reason": "rhetorical_framing", "action": "remove", "replacement": null}},
  {{"phrase": "intimate getaway", "reason": "rhetorical_framing", "action": "replace", "replacement": "trip"}}
]}}

Why: These phrases inject romantic/emotional framing that isn't factual reporting. "Sun-drenched romantic escape" editorializes a vacation. "Looked more in love than ever" is subjective speculation. "Beloved" and "intimate" are emotional descriptors that manipulate reader perception.

═══════════════════════════════════════════════════════════════════════════════
FALSE POSITIVE EXAMPLES - WHAT NOT TO FLAG
═══════════════════════════════════════════════════════════════════════════════

Study these examples carefully. They show common MISTAKES to avoid.

Example 6 - Medical news (DO NOT OVER-FLAG):
Input: "NHS bowel cancer tests will be fine-tuned to spot more tumours early as part of a faster diagnosis drive."

WRONG output: {{"phrases": [
  {{"phrase": "bowel cancer", "reason": "urgency_inflation"}},
  {{"phrase": "tests will", "reason": "urgency_inflation"}},
  {{"phrase": "spot more", "reason": "urgency_inflation"}}
]}}

CORRECT output: {{"phrases": []}}

Why: This is factual health news. "Bowel cancer" is medical terminology, not emotional language. "Tests will" and "spot more" are neutral verbs describing a program. Nothing here manipulates the reader's emotions.

Example 7 - Statistical reporting (DO NOT OVER-FLAG):
Input: "The region with the highest cost of living saw prices increase every year, getting worse since 2020."

WRONG output: {{"phrases": [
  {{"phrase": "highest cost", "reason": "urgency_inflation"}},
  {{"phrase": "every year", "reason": "urgency_inflation"}},
  {{"phrase": "getting worse", "reason": "emotional_trigger"}}
]}}

CORRECT output: {{"phrases": []}}

Why: These are factual descriptors of data. "Highest" is a superlative describing statistics. "Every year" is a temporal phrase. "Getting worse" describes a trend. None of these are manipulative.

Example 8 - Clean science news:
Input: "Researchers announced that the new treatment showed a 40% improvement in patient outcomes according to the published study."

CORRECT output: {{"phrases": []}}

Why: Standard news verbs ("announced", "showed", "according to") are neutral attribution language, not manipulation.

═══════════════════════════════════════════════════════════════════════════════
CALIBRATION - BALANCE PRECISION WITH RECALL
═══════════════════════════════════════════════════════════════════════════════

Not every article contains manipulation. Many news articles are straightforward reporting.

ASK YOURSELF before flagging each phrase:
- Is this trying to manipulate the reader's emotions or perception?
- Would a neutral rewrite change the emotional impact?
- Is this editorial opinion disguised as news?

IMPORTANT: Tabloid and celebrity news sources often use MORE manipulation (emotional amplification, dramatic language, romantic framing). When analyzing content from sources like Daily Mail, The Sun, NY Post, etc., expect and flag these patterns.

Aim for balanced detection - flag genuine manipulation while avoiding false positives on neutral language.

═══════════════════════════════════════════════════════════════════════════════
ARTICLE TO ANALYZE
═══════════════════════════════════════════════════════════════════════════════

{body}

═══════════════════════════════════════════════════════════════════════════════
RESPONSE
═══════════════════════════════════════════════════════════════════════════════

Return ONLY a JSON array (or empty array [] if no manipulation found):"""


def get_span_detection_prompt() -> str:
    """
    Get the prompt for LLM-based span detection.

    This prompt asks the LLM to identify manipulative phrases WITH context awareness:
    - Understands literal vs figurative usage
    - Distinguishes author language from quotes
    - Applies judgment about justified vs inflated urgency
    """
    return get_prompt("span_detection_prompt", DEFAULT_SPAN_DETECTION_PROMPT)


def get_model_agnostic_prompt(name: str, default: str) -> str:
    """
    Get a model-agnostic prompt from the database (model=NULL).

    Used for prompts that work across all models (e.g., multi-pass detection prompts).
    """
    global _prompt_cache

    cache_key = f"{name}:agnostic"

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
                models.Prompt.model.is_(None),  # model=NULL (agnostic)
                models.Prompt.is_active == True
            ).first()

            if prompt:
                _prompt_cache[cache_key] = prompt.content
                return prompt.content
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Failed to load model-agnostic prompt '{name}' from DB: {e}")

    # Use default if prompt not found
    _prompt_cache[cache_key] = default
    return default


def get_high_recall_prompt() -> str:
    """Get the high-recall prompt for Pass 1 (Claude Haiku)."""
    return get_model_agnostic_prompt("high_recall_prompt", HIGH_RECALL_USER_PROMPT)


def get_adversarial_prompt() -> str:
    """Get the adversarial prompt for Pass 2 (GPT-4o-mini)."""
    return get_model_agnostic_prompt("adversarial_prompt", ADVERSARIAL_USER_PROMPT)


def build_span_detection_prompt(body: str) -> str:
    """Build the prompt for LLM-based span detection."""
    template = get_span_detection_prompt()
    return template.format(body=body or "")


def find_phrase_positions(body: str, llm_phrases: list) -> List[TransparencySpan]:
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
    if not body or not llm_phrases:
        return []

    spans = []
    body_lower = body.lower()

    for phrase_data in llm_phrases:
        # Handle case where phrase_data is a string instead of a dict
        if isinstance(phrase_data, str):
            phrase = phrase_data
            reason_str = "emotional_trigger"
            action_str = "softened"
            replacement = None
        elif isinstance(phrase_data, dict):
            phrase = phrase_data.get("phrase", "")
            if not phrase:
                continue
            reason_str = phrase_data.get("reason", "emotional_trigger")
            action_str = phrase_data.get("action", "softened")
            replacement = phrase_data.get("replacement")
        else:
            # Skip invalid entries
            continue

        if not phrase:
            continue

        # Parse reason to enum
        reason = _parse_span_reason(reason_str)

        # Parse action to enum
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
                    # Use the actual text at this position
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


# Quote character pairs for matching (opening -> closing)
# Using Unicode escapes to ensure curly quotes are correctly defined
QUOTE_PAIRS = {
    '"': '"',           # Straight double quote (U+0022)
    '\u201c': '\u201d', # Curly double quotes: " -> " (U+201C -> U+201D)
    "'": "'",           # Straight single quote (U+0027)
    '\u2018': '\u2019', # Curly single quotes: ' -> ' (U+2018 -> U+2019)
}

# All characters that can open a quote
QUOTE_CHARS_OPEN = set(QUOTE_PAIRS.keys())

# All characters that can close a quote
QUOTE_CHARS_CLOSE = set(QUOTE_PAIRS.values())


def is_contraction_apostrophe(body: str, pos: int) -> bool:
    """
    Check if apostrophe at position is part of a contraction, not a quote boundary.

    Contractions have letters on both sides of the apostrophe, like:
    - won't, can't, don't (n't pattern)
    - it's, he's, she's ('s pattern)
    - they're, we're, you're ('re pattern)
    - I've, you've, we've ('ve pattern)
    - I'll, you'll, we'll ('ll pattern)
    - I'd, you'd, we'd ('d pattern)

    Quote boundaries typically have space or punctuation on at least one side.

    Note: This function intentionally does NOT detect possessives like "James' dog"
    because they are ambiguous with closing quotes like 'shocking'. Single quotes
    at word boundaries should be treated as potential quote marks for proper pairing.
    """
    if pos <= 0 or pos >= len(body) - 1:
        return False

    char_before = body[pos - 1]
    char_after = body[pos + 1]

    # Core rule: letters on both sides = contraction
    # Example: "won't" -> 'n' + "'" + 't'
    if char_before.isalpha() and char_after.isalpha():
        return True

    return False


def filter_spans_in_quotes(body: str, spans: List[TransparencySpan]) -> List[TransparencySpan]:
    """
    Remove spans that fall inside quotation marks.

    This is a post-filter to catch any manipulative language that the LLM
    flagged inside quoted speech. Quotes preserve attribution - readers
    can judge the speaker's words themselves.

    Handles multiple quote types:
    - Straight double quotes: "..."
    - Curly double quotes: "..."
    - Straight single quotes: '...'
    - Curly single quotes: '...'

    Distinguishes between apostrophes used as quote marks vs contractions:
    - Contractions: won't, it's, they're (letters on both sides)
    - Quotes: 'totally shocking' (space before opening, space after closing)
    """
    if not body or not spans:
        return spans

    # Find all quote boundaries using a stack for nested quotes
    quote_ranges = []
    stack = []  # Track (open_char, start_position)

    for i, char in enumerate(body):
        # Skip apostrophes that are part of contractions (not quote boundaries)
        if char in ("'", "'") and is_contraction_apostrophe(body, i):
            continue

        if char in QUOTE_CHARS_OPEN:
            # Check if this is an opening quote (not a closing one for the same type)
            # Handle ambiguous chars like " and ' that serve as both open and close
            if char in ('"', "'"):
                # Ambiguous quote - toggle behavior
                if stack and stack[-1][0] == char:
                    # Same quote type on stack, treat as closing
                    open_char, start = stack.pop()
                    quote_ranges.append((start, i + 1))
                else:
                    # New quote opening
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
FALSE_POSITIVE_PATTERNS = [
    # Don't use broad patterns like "cancer" - too aggressive
    # Only add very specific false positives here
]


def filter_false_positives(spans: List[TransparencySpan]) -> List[TransparencySpan]:
    """
    Remove known false positive spans that LLMs commonly flag incorrectly.

    This is a safety net for when the LLM doesn't follow the prompt instructions
    to avoid flagging neutral language like medical terms and factual descriptors.
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


# -----------------------------------------------------------------------------
# Brief Neutralization Validation
# -----------------------------------------------------------------------------

# Phrases that should be neutralized in detail_brief (entertainment/hype focus)
BRIEF_BANNED_PHRASES = {
    # Romance/celebrity hype (phrases)
    "romantic escape", "romantic getaway", "sun-drenched",
    "tender moment", "intimate conversation", "intimate getaway",
    "cozied up", "looked more in love", "visibly smitten",
    "totally into each other", "obsessed with",
    # Romance/celebrity hype (standalone words)
    "romantic", "intimate", "tender", "beloved", "smitten",
    "luxurious", "secluded", "affectionate",
    # Personal descriptors
    "showed off", "toned figure", "toned physique", "flaunted",
    "relaxed and affectionate", "appeared relaxed",
    # Loaded modifiers
    "celebrity hotspot", "beloved restaurant", "beloved cabo",
    "a-list", "power couple", "luxury yacht", "luxurious boat",
    "exclusive resort", "secluded getaway", "secluded waterfront",
    "exclusively revealed", "exclusively reported",
}


def validate_brief_neutralization(brief: str) -> List[str]:
    """
    Check if brief contains phrases that should have been neutralized.

    This is a post-generation validation step to catch entertainment/hype
    language that slipped through the LLM neutralization.

    Args:
        brief: The generated detail_brief text

    Returns:
        List of violations found (for logging/debugging). Empty list if clean.
    """
    if not brief:
        return []

    violations = []
    brief_lower = brief.lower()

    for phrase in BRIEF_BANNED_PHRASES:
        if phrase.lower() in brief_lower:
            violations.append(phrase)

    if violations:
        logger.warning(f"Brief contains un-neutralized phrases: {violations}")

    return violations


# Prompt for repairing briefs that failed validation
BRIEF_REPAIR_PROMPT = """The following brief contains banned language that must be removed.

VIOLATIONS FOUND: {violations}

Original brief:
{brief}

Rewrite this brief removing ALL the violations listed above. Replace:
- "romantic getaway" → "trip" or "vacation"
- "luxury boat" / "luxurious" → "boat" or neutral equivalent
- "relaxed and affectionate" → "spent time together"
- "romantic" / "intimate" / "tender" → remove or use neutral equivalents
- "cozied up" → "sat together" or similar
- "showed off" / "flaunted" → "wore" or "had"
- "celebrity hotspot" → "restaurant"
- "power couple" → "the couple" or just their names
- Other loaded entertainment language → neutral equivalents

Return ONLY the rewritten brief, no explanation or commentary."""


def build_brief_repair_prompt(brief: str, violations: List[str]) -> str:
    """
    Build a prompt to repair a brief that contains banned phrases.

    Args:
        brief: The original brief text with violations
        violations: List of banned phrases found in the brief

    Returns:
        A repair prompt asking the LLM to remove violations
    """
    return BRIEF_REPAIR_PROMPT.format(
        violations=", ".join(f'"{v}"' for v in violations),
        brief=brief,
    )


def validate_feed_summary(summary: str) -> List[str]:
    """
    Check if feed_summary contains phrases that should have been neutralized.

    Uses the same banned phrases list as brief validation.

    Args:
        summary: The generated feed_summary text

    Returns:
        List of violations found. Empty list if clean.
    """
    if not summary:
        return []

    violations = []
    summary_lower = summary.lower()

    for phrase in BRIEF_BANNED_PHRASES:
        if phrase.lower() in summary_lower:
            violations.append(phrase)

    if violations:
        logger.warning(f"Feed summary contains un-neutralized phrases: {violations}")

    return violations


# Prompt for repairing feed summaries that failed validation
FEED_SUMMARY_REPAIR_PROMPT = """The following feed summary contains banned language.

VIOLATIONS: {violations}
ORIGINAL: {summary}

Rewrite in 2 complete sentences, max 120 characters total. Remove all violations.
Replace "romantic getaway" with "trip", "luxury" with neutral terms, etc.
Return ONLY the rewritten summary, no explanation."""


def build_feed_summary_repair_prompt(summary: str, violations: List[str]) -> str:
    """Build a prompt to repair a feed_summary with banned phrases."""
    return FEED_SUMMARY_REPAIR_PROMPT.format(
        violations=", ".join(f'"{v}"' for v in violations),
        summary=summary,
    )


def truncate_at_sentence(text: str, max_chars: int = 130) -> str:
    """
    Truncate text at last complete sentence within limit.

    Args:
        text: The text to truncate
        max_chars: Maximum allowed characters

    Returns:
        Text truncated at sentence boundary, or word boundary if no sentence found
    """
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]

    # Find last sentence boundary
    for end_char in ['. ', '! ', '? ']:
        last_pos = truncated.rfind(end_char)
        if last_pos > 0:
            return truncated[:last_pos + 1].strip()

    # Check for sentence ending at very end (no space after)
    if truncated.endswith('.') or truncated.endswith('!') or truncated.endswith('?'):
        return truncated.strip()

    # Fallback: truncate at word boundary
    last_space = truncated.rfind(' ')
    if last_space > 0:
        return truncated[:last_space].strip()

    return truncated


def get_synthesis_detail_full_prompt() -> str:
    """
    Get the user prompt template for detail_full synthesis (NEW approach).

    This uses synthesis mode instead of in-place filtering:
    - Easier for LLMs - no position tracking
    - Better grammar preservation
    - Produces readable output
    """
    return get_prompt("synthesis_detail_full_prompt", DEFAULT_SYNTHESIS_DETAIL_FULL_PROMPT)


def build_synthesis_detail_full_prompt(body: str) -> str:
    """
    Build the user prompt for detail_full synthesis.
    """
    template = get_synthesis_detail_full_prompt()
    return template.format(body=body or "")


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
ENTERTAINMENT HYPE: romantic, intimate, tender, beloved, exclusive,
                    luxurious, luxury, secluded, sun-drenched, A-list
PERSONAL DESCRIPTORS: toned, stunning, gorgeous, handsome, smitten,
                      obsessed, affectionate, relaxed and affectionate
LOADED MODIFIERS: celebrity hotspot, power couple, looked more in love,
                  cozied up, showed off, flaunted

Use factual language instead:
- "significantly impacted" → state the specific impact
- "unprecedented" → describe what actually happened
- "catastrophic" → use the factual severity from the source

ENTERTAINMENT NEUTRALIZATION EXAMPLES:
- "romantic getaway" → "trip" or "vacation"
- "sun-drenched romantic escape" → "vacation"
- "luxury yacht" → "boat"
- "celebrity hotspot" → "restaurant"
- "showed off her toned figure" → "wore a bikini"
- "appeared relaxed and affectionate" → "spent time together"
- "looked more in love than ever" → OMIT (speculative)
- "cozied up" → "dined" or "sat together"
- "beloved restaurant" → "restaurant"

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
2. feed_summary: 2 complete sentences continuing from title (100-120 characters, hard max 130)
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
OUTPUT 2: feed_summary (TARGET 120 CHARACTERS)
═══════════════════════════════════════════════════════════════════════════════

Purpose: Provide context and details that CONTINUE from the feed_title. Displays inline after title.

CONSTRAINTS:
- Target 100-120 characters (count EVERY character including spaces and periods)
- Maximum 130 characters (HARD limit - will be truncated if exceeded)
- 2 complete sentences with meaningful content
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
GRAMMAR INTEGRITY CHECK (CRITICAL - READ BEFORE OUTPUTTING)
═══════════════════════════════════════════════════════════════════════════════

Read each output aloud BEFORE submitting. If it sounds incomplete or awkward, REWRITE IT.

NEVER OUTPUT INCOMPLETE PHRASES:
- "and Timothée enjoyed a to Cabo" ← BROKEN (missing subject + noun)
- "The has initiated an 's platform" ← BROKEN (missing proper nouns)
- "the seizure of a of a" ← BROKEN (garbled, repeated words)
- "Senator Tax Bill" ← BROKEN (missing verb)

ALWAYS OUTPUT COMPLETE PHRASES:
- "Kylie Jenner and Timothée Chalamet Vacation in Cabo" ← COMPLETE
- "European Commission Investigates Elon Musk's Platform" ← COMPLETE
- "Authorities Seize Narco Sub Carrying Cocaine" ← COMPLETE
- "Senator Proposes Tax Bill" ← COMPLETE

WARNING SIGNS OF GARBLED OUTPUT:
- Fewer than 3 words in a title
- Ends with "a", "the", "to", "of", "and"
- Missing subject (who) or verb (what happened)
- Repeated word pairs ("of a of a")

If ANY warning sign appears, STOP and REWRITE before outputting.

TONE GUIDANCE (prefer neutral alternatives):
- "criticizes" over "slams"
- "disputes" over "destroys"
- "addresses" over "blasts"
But if no neutral word fits, USE THE ORIGINAL - never break grammar for neutrality.

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
  "feed_summary": "100-120 chars, hard max 130, 2 sentences, MUST NOT repeat title",
  "detail_title": "≤12 words, more specific than feed_title",
  "section": "world|us|local|business|technology"
}}

BEFORE OUTPUTTING - VERIFY (CRITICAL):
1. feed_title: COUNT EVERY CHARACTER NOW - must be ≤75 (target 55-70)
2. feed_summary: COUNT EVERY CHARACTER NOW - must be ≤130 (target 100-120)
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


def get_headline_system_prompt() -> str:
    """
    Get the headline system prompt for feed outputs (Call 3: Compress).

    This is a LIGHTER prompt than the article system prompt, optimized for
    headline synthesis. It prioritizes:
    1. Grammatical integrity - complete, readable phrases
    2. Factual accuracy - preserve who, what, where, when
    3. Neutral tone - straightforward language

    Unlike the article system prompt, this does NOT aggressively ban words,
    because the article body has already been neutralized. The goal is
    SYNTHESIS into short headlines, not word-level filtering.

    Retrievable via get_prompt('headline_system_prompt').
    """
    return get_prompt("headline_system_prompt", DEFAULT_HEADLINE_SYSTEM_PROMPT)


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


def _validate_feed_outputs(result: dict) -> None:
    """
    Validate feed outputs for garbled content and log warnings.

    This function detects common signs of LLM garbling:
    - Titles/summaries ending with dangling prepositions/articles
    - Titles with fewer than 3 words (likely incomplete)
    - Repeated word patterns ("of a of a")
    - Missing punctuation in summaries

    Logs warnings but does NOT modify the result - this is for monitoring.
    In future iterations, we may add automatic repair.

    Args:
        result: dict with feed_title, feed_summary, detail_title, section
    """
    issues = []

    feed_title = result.get("feed_title", "")
    feed_summary = result.get("feed_summary", "")
    detail_title = result.get("detail_title", "")

    # Check for dangling prepositions/articles (ends with incomplete phrase)
    dangling_endings = ["a", "an", "the", "to", "of", "in", "on", "at", "for", "with", "and", "or"]

    for field_name, text in [("feed_title", feed_title), ("feed_summary", feed_summary), ("detail_title", detail_title)]:
        if not text:
            continue

        # Strip punctuation for checking endings
        text_stripped = text.rstrip(".,!?:;")
        words = text_stripped.split()

        if words and words[-1].lower() in dangling_endings:
            issues.append(f"{field_name} ends with dangling '{words[-1]}': '{text[:50]}...'")

    # Check for minimum word count in titles (< 3 words is suspicious)
    for field_name, text in [("feed_title", feed_title), ("detail_title", detail_title)]:
        if text:
            word_count = len(text.split())
            if word_count < 3:
                issues.append(f"{field_name} has only {word_count} word(s): '{text}'")

    # Check for repeated word patterns (e.g., "of a of a")
    for field_name, text in [("feed_title", feed_title), ("feed_summary", feed_summary), ("detail_title", detail_title)]:
        if text:
            words = text.lower().split()
            for i in range(len(words) - 3):
                # Look for patterns like "X Y X Y"
                if words[i] == words[i+2] and words[i+1] == words[i+3]:
                    issues.append(f"{field_name} has repeated pattern: '{text[:50]}...'")
                    break

    # Check for incomplete sentences in summary (should have punctuation)
    if feed_summary and not feed_summary.rstrip().endswith((".", "!", "?", '"', "'")):
        issues.append(f"feed_summary lacks ending punctuation: '{feed_summary[-30:]}...'")

    # Log warnings for any issues found
    if issues:
        logger.warning(f"Garbled feed output detected: {'; '.join(issues)}")


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
    if action_lower in ("removed", "remove"):
        return SpanAction.REMOVED
    elif action_lower in ("replaced", "replace"):
        return SpanAction.REPLACED
    elif action_lower in ("softened", "soften"):
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
        "editorial_voice": SpanReason.EDITORIAL_VOICE,
        "publisher_cruft": SpanReason.SELLING,  # Map to closest enum
    }
    return mapping.get(reason_lower, SpanReason.RHETORICAL_FRAMING)


def detect_spans_via_llm_openai(body: str, api_key: str, model: str) -> List[TransparencySpan]:
    """
    Detect manipulative spans using OpenAI LLM with context awareness.

    This is the hybrid approach:
    1. LLM identifies phrases with semantic understanding (no position tracking)
    2. find_phrase_positions() locates exact character positions

    Benefits over pattern-only approach:
    - Understands "slams" as criticism vs "car slams into wall"
    - Distinguishes author language from quoted speech
    - Applies judgment about justified vs inflated urgency

    Args:
        body: Original article body text
        api_key: OpenAI API key
        model: Model name (e.g., "gpt-4o-mini")

    Returns:
        List of TransparencySpan with accurate positions
    """
    if not body or not api_key:
        return []

    try:
        import json
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        # Use minimal system prompt to let the detailed user prompt control detection
        user_prompt = build_span_detection_prompt(body)
        logger.info(f"[SPAN_DETECTION] Starting LLM call, model={model}, body_length={len(body)}")

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SPAN_DETECTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,  # Balanced temp for variety while maintaining consistency
            response_format={"type": "json_object"},
        )

        # Parse LLM response
        content = response.choices[0].message.content.strip()
        logger.info(f"[SPAN_DETECTION] LLM responded, response_length={len(content)}")

        # Handle JSON response (might be {"phrases": [...]} or just [...])
        try:
            data = json.loads(content)
            if isinstance(data, list):
                llm_phrases = data
            elif isinstance(data, dict):
                # Try common keys that LLMs use to wrap the array
                llm_phrases = (
                    data.get("phrases")
                    or data.get("spans")
                    or data.get("manipulative_phrases")
                    or data.get("response")
                    or data.get("output")
                    or data.get("results")
                    or data.get("items")
                    or data.get("data")
                    or []
                )
                # If LLM returned a single object with "phrase" key (not wrapped in array)
                # treat it as a single-element array
                if not llm_phrases and "phrase" in data:
                    llm_phrases = [data]
            else:
                llm_phrases = []
            logger.info(f"[SPAN_DETECTION] LLM returned {len(llm_phrases)} phrases")
        except json.JSONDecodeError:
            logger.warning(f"LLM span detection returned invalid JSON: {content[:200]}")
            return []

        # Convert to TransparencySpans with position matching
        spans = find_phrase_positions(body, llm_phrases)
        after_position = len(spans)
        spans = filter_spans_in_quotes(body, spans)
        after_quotes = len(spans)
        spans = filter_false_positives(spans)
        after_fp = len(spans)
        logger.info(f"[SPAN_DETECTION] Pipeline: position_match={after_position} → quote_filter={after_quotes} → fp_filter={after_fp}")
        return spans

    except Exception as e:
        logger.error(f"[SPAN_DETECTION] LLM call failed: {type(e).__name__}: {e}")
        return None  # Return None on failure (not []) so caller knows to use fallback


@dataclass
class SpanDetectionDebugResult:
    """Debug result from span detection showing intermediate pipeline stages."""
    llm_raw_response: Optional[str]
    llm_phrases: List[Dict[str, Any]]
    spans_after_position: List[TransparencySpan]
    spans_after_quotes: List[TransparencySpan]
    spans_final: List[TransparencySpan]
    filtered_by_quotes: List[str]
    filtered_as_false_positives: List[str]
    not_found_in_text: List[str]
    error: Optional[str] = None


def detect_spans_debug_openai(body: str, api_key: str, model: str) -> SpanDetectionDebugResult:
    """
    Debug version of detect_spans_via_llm_openai that returns intermediate results.

    Returns full trace of what the LLM returned and what happened at each filtering stage.
    """
    if not body or not api_key:
        return SpanDetectionDebugResult(
            llm_raw_response=None,
            llm_phrases=[],
            spans_after_position=[],
            spans_after_quotes=[],
            spans_final=[],
            filtered_by_quotes=[],
            filtered_as_false_positives=[],
            not_found_in_text=[],
            error="Missing body or API key"
        )

    try:
        import json
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        user_prompt = build_span_detection_prompt(body)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SPAN_DETECTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,  # Balanced temp for variety while maintaining consistency
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content.strip()
        llm_raw_response = content

        # Parse LLM response
        try:
            data = json.loads(content)
            if isinstance(data, list):
                llm_phrases = data
            elif isinstance(data, dict):
                llm_phrases = (
                    data.get("phrases")
                    or data.get("spans")
                    or data.get("manipulative_phrases")
                    or data.get("response")
                    or data.get("output")
                    or data.get("results")
                    or data.get("items")
                    or data.get("data")
                    or []
                )
                if not llm_phrases and "phrase" in data:
                    llm_phrases = [data]
            else:
                llm_phrases = []
        except json.JSONDecodeError as e:
            return SpanDetectionDebugResult(
                llm_raw_response=llm_raw_response,
                llm_phrases=[],
                spans_after_position=[],
                spans_after_quotes=[],
                spans_final=[],
                filtered_by_quotes=[],
                filtered_as_false_positives=[],
                not_found_in_text=[],
                error=f"JSON parse error: {e}"
            )

        # Track phrases not found in text
        not_found_in_text = []
        body_lower = body.lower()
        for phrase_data in llm_phrases:
            phrase = phrase_data.get("phrase", "")
            if phrase and phrase.lower() not in body_lower and phrase not in body:
                not_found_in_text.append(phrase)

        # Position matching
        spans_after_position = find_phrase_positions(body, llm_phrases)

        # Quote filtering - track what's filtered
        spans_after_quotes = filter_spans_in_quotes(body, spans_after_position)
        filtered_by_quotes = [
            s.original_text for s in spans_after_position
            if s not in spans_after_quotes
        ]

        # False positive filtering - track what's filtered
        spans_final = filter_false_positives(spans_after_quotes)
        filtered_as_false_positives = [
            s.original_text for s in spans_after_quotes
            if s not in spans_final
        ]

        return SpanDetectionDebugResult(
            llm_raw_response=llm_raw_response,
            llm_phrases=llm_phrases,
            spans_after_position=spans_after_position,
            spans_after_quotes=spans_after_quotes,
            spans_final=spans_final,
            filtered_by_quotes=filtered_by_quotes,
            filtered_as_false_positives=filtered_as_false_positives,
            not_found_in_text=not_found_in_text,
        )

    except Exception as e:
        return SpanDetectionDebugResult(
            llm_raw_response=None,
            llm_phrases=[],
            spans_after_position=[],
            spans_after_quotes=[],
            spans_final=[],
            filtered_by_quotes=[],
            filtered_as_false_positives=[],
            not_found_in_text=[],
            error=f"{type(e).__name__}: {e}"
        )


def detect_spans_via_llm_gemini(body: str, api_key: str, model: str) -> List[TransparencySpan]:
    """
    Detect manipulative spans using Gemini LLM with context awareness.

    See detect_spans_via_llm_openai for details on the hybrid approach.
    """
    if not body or not api_key:
        return []

    try:
        import json
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        # Use minimal system prompt to let the detailed user prompt control detection
        user_prompt = build_span_detection_prompt(body)

        gemini_model = genai.GenerativeModel(
            model_name=model,
            system_instruction=SPAN_DETECTION_SYSTEM_PROMPT,
            generation_config={
                "temperature": 0.3,  # Balanced temp for variety while maintaining consistency
                "response_mime_type": "application/json",
            },
        )

        response = gemini_model.generate_content(user_prompt)
        content = response.text.strip()

        # Parse response
        try:
            data = json.loads(content)
            if isinstance(data, list):
                llm_phrases = data
            elif isinstance(data, dict):
                # Try common keys that LLMs use to wrap the array
                llm_phrases = (
                    data.get("phrases")
                    or data.get("spans")
                    or data.get("manipulative_phrases")
                    or data.get("response")
                    or data.get("output")
                    or data.get("results")
                    or data.get("items")
                    or data.get("data")
                    or []
                )
                # If LLM returned a single object with "phrase" key (not wrapped in array)
                if not llm_phrases and "phrase" in data:
                    llm_phrases = [data]
            else:
                llm_phrases = []
        except json.JSONDecodeError:
            logger.warning(f"Gemini span detection returned invalid JSON: {content[:200]}")
            return []

        spans = find_phrase_positions(body, llm_phrases)
        spans = filter_spans_in_quotes(body, spans)
        spans = filter_false_positives(spans)
        logger.info(f"Gemini span detection found {len(spans)} manipulative phrases")
        return spans

    except Exception as e:
        logger.warning(f"Gemini span detection failed: {e}")
        return None  # Return None on failure so caller knows to use fallback


def detect_spans_via_llm_anthropic(body: str, api_key: str, model: str) -> List[TransparencySpan]:
    """
    Detect manipulative spans using Anthropic Claude with context awareness.

    See detect_spans_via_llm_openai for details on the hybrid approach.
    """
    if not body or not api_key:
        return []

    try:
        import json
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        # Use minimal system prompt to let the detailed user prompt control detection
        user_prompt = build_span_detection_prompt(body)

        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SPAN_DETECTION_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
        )

        content = response.content[0].text.strip()

        # Claude may wrap JSON in markdown code blocks
        if content.startswith("```"):
            # Extract JSON from code block
            lines = content.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```"):
                    in_block = not in_block
                    continue
                if in_block:
                    json_lines.append(line)
            content = "\n".join(json_lines)

        # Parse response
        try:
            data = json.loads(content)
            if isinstance(data, list):
                llm_phrases = data
            elif isinstance(data, dict):
                # Try common keys that LLMs use to wrap the array
                llm_phrases = (
                    data.get("phrases")
                    or data.get("spans")
                    or data.get("manipulative_phrases")
                    or data.get("response")
                    or data.get("output")
                    or data.get("results")
                    or data.get("items")
                    or data.get("data")
                    or []
                )
                # If LLM returned a single object with "phrase" key (not wrapped in array)
                if not llm_phrases and "phrase" in data:
                    llm_phrases = [data]
            else:
                llm_phrases = []
        except json.JSONDecodeError:
            logger.warning(f"Anthropic span detection returned invalid JSON: {content[:200]}")
            return []

        spans = find_phrase_positions(body, llm_phrases)
        spans = filter_spans_in_quotes(body, spans)
        spans = filter_false_positives(spans)
        logger.info(f"Anthropic span detection found {len(spans)} manipulative phrases")
        return spans

    except Exception as e:
        logger.warning(f"Anthropic span detection failed: {e}")
        return None  # Return None on failure so caller knows to use fallback


# -----------------------------------------------------------------------------
# High-Recall Detection (Phase 2 - Claude Haiku)
# -----------------------------------------------------------------------------

# High-recall user prompt (aggressive detection)
HIGH_RECALL_USER_PROMPT = """You are detecting ALL manipulative language. When in doubt, FLAG IT.

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
{{"phrases": [{{"phrase": "EXACT text", "reason": "category", "action": "remove|replace", "replacement": "text or null"}}]}}"""


def detect_spans_high_recall_anthropic(
    body: str,
    api_key: str,
    model: str = "claude-3-5-haiku-latest"
) -> List[TransparencySpan]:
    """
    High-recall span detection using Claude Haiku with aggressive prompting.

    This is Pass 1 of multi-pass detection - optimized to catch EVERYTHING,
    even at the cost of some false positives (which get filtered later).

    Args:
        body: Original article body text
        api_key: Anthropic API key
        model: Model name (default claude-3-5-haiku-latest for speed/cost)

    Returns:
        List of TransparencySpan (may include false positives)
    """
    if not body or not api_key:
        return []

    try:
        import json
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        # Get prompt from DB (falls back to hardcoded default)
        prompt_template = get_high_recall_prompt()
        user_prompt = prompt_template.format(body=body)
        logger.info(f"[SPAN_DETECTION] High-recall pass starting, model={model}, body_length={len(body)}")

        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=HIGH_RECALL_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
        )

        content = response.content[0].text.strip()

        # Claude may wrap JSON in markdown code blocks
        if content.startswith("```"):
            lines = content.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```"):
                    in_block = not in_block
                    continue
                if in_block:
                    json_lines.append(line)
            content = "\n".join(json_lines)

        # Parse response
        try:
            data = json.loads(content)
            if isinstance(data, list):
                llm_phrases = data
            elif isinstance(data, dict):
                llm_phrases = (
                    data.get("phrases")
                    or data.get("spans")
                    or data.get("manipulative_phrases")
                    or data.get("results")
                    or []
                )
                if not llm_phrases and "phrase" in data:
                    llm_phrases = [data]
            else:
                llm_phrases = []
        except json.JSONDecodeError:
            logger.warning(f"High-recall pass returned invalid JSON: {content[:200]}")
            return []

        # Validate llm_phrases is a list of dicts (not a single dict or string)
        if not isinstance(llm_phrases, list):
            logger.warning(f"[SPAN_DETECTION] High-recall pass returned non-list phrases: {type(llm_phrases)}")
            llm_phrases = [llm_phrases] if isinstance(llm_phrases, dict) else []

        logger.info(f"[SPAN_DETECTION] High-recall pass returned {len(llm_phrases)} phrases")

        # Position matching (no filtering yet - that happens in merge step)
        spans = find_phrase_positions(body, llm_phrases)
        return spans

    except Exception as e:
        import traceback
        logger.warning(f"High-recall span detection failed: {type(e).__name__}: {e}")
        logger.debug(f"High-recall span detection traceback: {traceback.format_exc()}")
        return []


# -----------------------------------------------------------------------------
# Adversarial Second Pass Detection
# -----------------------------------------------------------------------------

# Adversarial user prompt (finds what first pass missed)
ADVERSARIAL_USER_PROMPT = """The following manipulative phrases have already been detected in this article:

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
{{"phrases": [{{"phrase": "EXACT text", "reason": "category", "action": "remove|replace", "replacement": "text or null"}}]}}

If no additional phrases found, return: {{"phrases": []}}"""


def detect_spans_adversarial_pass(
    body: str,
    detected_phrases: List[str],
    api_key: str,
    model: str = "gpt-4o-mini"
) -> List[TransparencySpan]:
    """
    Adversarial second pass that looks for phrases missed by the first pass.

    This pass sees what was already detected and specifically looks for
    manipulation that slipped through.

    Args:
        body: Original article body text
        detected_phrases: List of phrase texts already detected in first pass
        api_key: OpenAI API key
        model: Model name (default gpt-4o-mini)

    Returns:
        List of NEW TransparencySpan (only phrases not in detected_phrases)
    """
    if not body or not api_key:
        return []

    try:
        import json
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        # Format detected phrases for the prompt
        detected_list = "\n".join(f"- \"{p}\"" for p in detected_phrases) if detected_phrases else "(none detected yet)"

        # Get prompt from DB (falls back to hardcoded default)
        prompt_template = get_adversarial_prompt()
        user_prompt = prompt_template.format(
            detected_phrases=detected_list,
            body=body
        )
        logger.info(f"[SPAN_DETECTION] Adversarial pass starting, model={model}, already_detected={len(detected_phrases)}")

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": ADVERSARIAL_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content.strip()

        # Parse response
        try:
            data = json.loads(content)
            if isinstance(data, list):
                llm_phrases = data
            elif isinstance(data, dict):
                llm_phrases = (
                    data.get("phrases")
                    or data.get("spans")
                    or data.get("manipulative_phrases")
                    or data.get("results")
                    or []
                )
                if not llm_phrases and "phrase" in data:
                    llm_phrases = [data]
            else:
                llm_phrases = []
        except json.JSONDecodeError:
            logger.warning(f"Adversarial pass returned invalid JSON: {content[:200]}")
            return []

        # Validate llm_phrases is a list of dicts (not a single dict or string)
        if not isinstance(llm_phrases, list):
            logger.warning(f"[SPAN_DETECTION] Adversarial pass returned non-list phrases: {type(llm_phrases)}")
            llm_phrases = [llm_phrases] if isinstance(llm_phrases, dict) else []

        logger.info(f"[SPAN_DETECTION] Adversarial pass found {len(llm_phrases)} additional phrases")

        # Position matching
        spans = find_phrase_positions(body, llm_phrases)

        # Filter out any that overlap with already-detected phrases
        # (in case the LLM returned some duplicates)
        detected_lower = {p.lower() for p in detected_phrases}
        new_spans = [s for s in spans if s.original_text.lower() not in detected_lower]

        logger.info(f"[SPAN_DETECTION] Adversarial pass returning {len(new_spans)} new spans")
        return new_spans

    except Exception as e:
        import traceback
        logger.warning(f"Adversarial span detection failed: {type(e).__name__}: {e}")
        logger.debug(f"Adversarial span detection traceback: {traceback.format_exc()}")
        return []


# -----------------------------------------------------------------------------
# Multi-Pass Span Detection Orchestration
# -----------------------------------------------------------------------------

async def detect_spans_multi_pass_async(
    body: str,
    openai_api_key: str,
    anthropic_api_key: str,
    openai_model: str = "gpt-4o-mini",
    anthropic_model: str = "claude-3-5-haiku-latest",
    chunk_size: int = 3000,
    overlap_size: int = 500,
) -> List[TransparencySpan]:
    """
    Multi-pass span detection with chunking for high recall.

    Architecture:
    1. CHUNKING: Split long articles into overlapping chunks
    2. PASS 1 (HIGH-RECALL): Claude Haiku with aggressive prompt
    3. PASS 2 (ADVERSARIAL): GPT-4o-mini looking for what Pass 1 missed
    4. MERGE: Union all spans with deduplication

    Args:
        body: Original article body
        openai_api_key: OpenAI API key
        anthropic_api_key: Anthropic API key
        openai_model: Model for adversarial pass
        anthropic_model: Model for high-recall pass
        chunk_size: Chunk size for long articles
        overlap_size: Overlap between chunks

    Returns:
        Merged list of TransparencySpan (target: 99% recall)
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from app.services.neutralizer.chunking import ArticleChunker, ArticleChunk
    from app.services.neutralizer.spans import (
        merge_multi_pass_spans,
        adjust_chunk_positions,
        deduplicate_overlap_spans,
        filter_spans_in_quotes,
        filter_false_positives,
    )

    if not body:
        return []

    logger.info(f"[MULTI_PASS] Starting multi-pass detection, body_length={len(body)}")

    # Phase 1: Chunking
    chunker = ArticleChunker(chunk_size=chunk_size, overlap_size=overlap_size)
    chunks = chunker.chunk(body)
    logger.info(f"[MULTI_PASS] Created {len(chunks)} chunks")

    # Helper to run blocking LLM calls
    executor = ThreadPoolExecutor(max_workers=4)

    async def run_high_recall_on_chunk(chunk: ArticleChunk) -> List[TransparencySpan]:
        """Run high-recall pass on a single chunk."""
        loop = asyncio.get_event_loop()
        spans = await loop.run_in_executor(
            executor,
            lambda: detect_spans_high_recall_anthropic(
                chunk.text,
                anthropic_api_key,
                anthropic_model
            )
        )
        # Adjust positions from chunk-relative to body-relative
        return adjust_chunk_positions(spans or [], chunk.start_offset)

    async def run_adversarial_on_chunk(
        chunk: ArticleChunk,
        detected_phrases: List[str]
    ) -> List[TransparencySpan]:
        """Run adversarial pass on a single chunk."""
        loop = asyncio.get_event_loop()
        spans = await loop.run_in_executor(
            executor,
            lambda: detect_spans_adversarial_pass(
                chunk.text,
                detected_phrases,
                openai_api_key,
                openai_model
            )
        )
        # Adjust positions from chunk-relative to body-relative
        return adjust_chunk_positions(spans or [], chunk.start_offset)

    # Phase 2: Parallel high-recall detection on all chunks
    logger.info("[MULTI_PASS] Pass 1: High-recall detection (Claude Haiku)")
    high_recall_tasks = [run_high_recall_on_chunk(chunk) for chunk in chunks]
    high_recall_results = await asyncio.gather(*high_recall_tasks)

    # Flatten Pass 1 results
    pass1_spans = []
    for spans in high_recall_results:
        if spans:
            pass1_spans.extend(spans)
    logger.info(f"[MULTI_PASS] Pass 1 found {len(pass1_spans)} spans across {len(chunks)} chunks")

    # Get detected phrases for Pass 2
    detected_phrases = [s.original_text for s in pass1_spans]

    # Phase 3: Adversarial pass on all chunks
    logger.info("[MULTI_PASS] Pass 2: Adversarial detection (GPT-4o-mini)")
    adversarial_tasks = [
        run_adversarial_on_chunk(chunk, detected_phrases)
        for chunk in chunks
    ]
    adversarial_results = await asyncio.gather(*adversarial_tasks)

    # Flatten Pass 2 results
    pass2_spans = []
    for spans in adversarial_results:
        if spans:
            pass2_spans.extend(spans)
    logger.info(f"[MULTI_PASS] Pass 2 found {len(pass2_spans)} additional spans")

    # Phase 4: Merge all spans
    logger.info("[MULTI_PASS] Merging spans from all passes")
    merged_spans = merge_multi_pass_spans([pass1_spans, pass2_spans], body)

    # Deduplicate overlaps
    deduplicated = deduplicate_overlap_spans(merged_spans, overlap_size)

    # Phase 5: Apply filters
    filtered = filter_spans_in_quotes(body, deduplicated)
    final = filter_false_positives(filtered)

    logger.info(
        f"[MULTI_PASS] Final: {len(final)} spans "
        f"(pass1={len(pass1_spans)}, pass2={len(pass2_spans)}, "
        f"merged={len(merged_spans)}, filtered={len(final)})"
    )

    executor.shutdown(wait=False)
    return final


def detect_spans_multi_pass(
    body: str,
    openai_api_key: str,
    anthropic_api_key: str,
    openai_model: str = "gpt-4o-mini",
    anthropic_model: str = "claude-3-5-haiku-latest",
    chunk_size: int = 3000,
    overlap_size: int = 500,
) -> List[TransparencySpan]:
    """
    Synchronous wrapper for multi-pass span detection.

    See detect_spans_multi_pass_async for details.
    """
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already in async context - create new loop
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(
                detect_spans_multi_pass_async(
                    body, openai_api_key, anthropic_api_key,
                    openai_model, anthropic_model,
                    chunk_size, overlap_size
                )
            )
    except RuntimeError:
        pass

    # No running loop - create one
    return asyncio.run(
        detect_spans_multi_pass_async(
            body, openai_api_key, anthropic_api_key,
            openai_model, anthropic_model,
            chunk_size, overlap_size
        )
    )


def detect_spans_with_mode(
    body: str,
    mode: str,
    openai_api_key: str = None,
    anthropic_api_key: str = None,
    gemini_api_key: str = None,
    openai_model: str = "gpt-4o-mini",
    anthropic_model: str = "claude-3-5-haiku-latest",
) -> List[TransparencySpan]:
    """
    Detect spans using the specified detection mode.

    Modes:
    - "single": Original single-pass detection (current behavior)
    - "multi_pass": Multi-pass with chunking for 99% recall target

    Args:
        body: Article body text
        mode: Detection mode ("single" or "multi_pass")
        openai_api_key: OpenAI API key
        anthropic_api_key: Anthropic API key (required for multi_pass)
        gemini_api_key: Gemini API key (for single mode fallback)
        openai_model: OpenAI model name
        anthropic_model: Anthropic model name

    Returns:
        List of TransparencySpan
    """
    if mode == "multi_pass":
        if not anthropic_api_key:
            logger.warning("[SPAN_DETECTION] multi_pass mode requires ANTHROPIC_API_KEY, falling back to single")
            mode = "single"
        elif not openai_api_key:
            logger.warning("[SPAN_DETECTION] multi_pass mode requires OPENAI_API_KEY, falling back to single")
            mode = "single"

    if mode == "multi_pass":
        logger.info("[SPAN_DETECTION] Using multi_pass mode (target: 99% recall)")
        return detect_spans_multi_pass(
            body=body,
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
            openai_model=openai_model,
            anthropic_model=anthropic_model,
        )
    else:
        # Single pass mode (original behavior)
        logger.info("[SPAN_DETECTION] Using single mode")
        if openai_api_key:
            return detect_spans_via_llm_openai(body, openai_api_key, openai_model)
        elif gemini_api_key:
            return detect_spans_via_llm_gemini(body, gemini_api_key, "gemini-2.0-flash")
        elif anthropic_api_key:
            return detect_spans_via_llm_anthropic(body, anthropic_api_key, anthropic_model)
        else:
            logger.error("[SPAN_DETECTION] No API keys available")
            return []


def _detect_spans_with_config(
    body: str,
    provider_api_key: str = None,
    provider_type: str = "openai",
    provider_model: str = "gpt-4o-mini",
) -> List[TransparencySpan]:
    """
    Detect spans using the mode configured in settings.SPAN_DETECTION_MODE.

    This helper function is called by each provider's _neutralize_detail_full method.
    It checks the config and delegates to detect_spans_with_mode() or the single-pass
    function as appropriate.

    Args:
        body: Article body text
        provider_api_key: The API key for the provider calling this function
        provider_type: "openai", "gemini", or "anthropic"
        provider_model: The model name (e.g., "gpt-4o-mini")

    Returns:
        List of TransparencySpan (may be empty if article is clean, or if detection fails)
    """
    settings = get_settings()
    mode = settings.SPAN_DETECTION_MODE

    if mode == "multi_pass":
        # Multi-pass requires both OpenAI and Anthropic keys
        openai_key = settings.OPENAI_API_KEY
        anthropic_key = settings.ANTHROPIC_API_KEY

        # Fall back to single mode if keys are missing
        if not openai_key:
            logger.warning("[SPAN_DETECTION] multi_pass mode requires OPENAI_API_KEY, using single mode")
            mode = "single"
        elif not anthropic_key:
            logger.warning("[SPAN_DETECTION] multi_pass mode requires ANTHROPIC_API_KEY, using single mode")
            mode = "single"
        else:
            logger.info(f"[SPAN_DETECTION] Using multi_pass mode (config: SPAN_DETECTION_MODE={settings.SPAN_DETECTION_MODE})")
            spans = detect_spans_with_mode(
                body=body,
                mode="multi_pass",
                openai_api_key=openai_key,
                anthropic_api_key=anthropic_key,
                openai_model=settings.ADVERSARIAL_MODEL,
                anthropic_model=settings.HIGH_RECALL_MODEL,
            )
            return spans if spans is not None else []

    # Single mode - use the provider's own detection function
    logger.info(f"[SPAN_DETECTION] Using single mode with {provider_type}")
    if provider_type == "openai":
        spans = detect_spans_via_llm_openai(body, provider_api_key, provider_model)
    elif provider_type == "gemini":
        spans = detect_spans_via_llm_gemini(body, provider_api_key, provider_model)
    elif provider_type == "anthropic":
        spans = detect_spans_via_llm_anthropic(body, provider_api_key, provider_model)
    else:
        logger.error(f"[SPAN_DETECTION] Unknown provider type: {provider_type}")
        spans = None

    return spans if spans is not None else []


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


def _detect_garbled_output(original: str, filtered: str) -> bool:
    """
    Detect if the filtered output is garbled (over-filtered, broken grammar).

    Signs of garbling:
    1. Output is much shorter than input (<60% length)
    2. Many consecutive punctuation marks or articles without following words
    3. Sentences starting with lowercase after period

    Returns:
        True if output appears garbled, False if it looks OK
    """
    if not original or not filtered:
        return False

    # Check 1: Output too short (over-filtering)
    length_ratio = len(filtered) / len(original)
    if length_ratio < 0.60:
        logger.warning(
            f"Garbled output detected: length_ratio={length_ratio:.2f} "
            f"(filtered={len(filtered)}, original={len(original)})"
        )
        return True

    # Check 2: Look for broken grammar patterns
    # Pattern: ". The " followed by punctuation or article (e.g., ". The , " or ". The a ")
    broken_patterns = [
        r'\. [A-Z][a-z]* [,\.\!\?]',  # "The ," or "She ."
        r'\. [A-Z][a-z]* (a|an|the) [,\.\!\?]',  # "The a ," broken article
        r"'s [,\.\!\?]",  # "'s ," missing word after possessive
        r'\. [,\.\!\?]',  # Direct ". ," or ". ."
    ]

    import re
    broken_count = 0
    for pattern in broken_patterns:
        matches = re.findall(pattern, filtered)
        broken_count += len(matches)

    if broken_count > 5:
        logger.warning(f"Garbled output detected: {broken_count} broken grammar patterns found")
        return True

    return False


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


def _synthesize_detail_full_fallback(body: str, provider_name: str, api_key: str = None, model: str = None) -> DetailFullResult:
    """
    Fallback synthesis approach for detail_full when in-place filtering fails.

    Uses synthesis mode (plain text output) instead of JSON with position tracking.
    This produces more readable, grammatically correct output because it doesn't
    require the LLM to track exact character positions while filtering.

    Args:
        body: Original article body
        provider_name: "openai", "anthropic", or "gemini"
        api_key: API key for the provider
        model: Model name to use

    Returns:
        DetailFullResult with synthesized text (or failure indicator if synthesis fails)
    """
    if not body:
        return DetailFullResult(detail_full="", spans=[])

    # No API key = failure (don't fall back to mock)
    if not api_key:
        logger.error(f"No API key for {provider_name} - cannot synthesize detail_full")
        return DetailFullResult(
            detail_full="",
            spans=[],
            status="failed_llm",
            failure_reason=f"No API key configured for {provider_name}"
        )

    # Generate detail_full using synthesis prompt (plain text, not JSON)
    try:
        system_prompt = get_article_system_prompt()
        user_prompt = build_synthesis_detail_full_prompt(body)

        if provider_name == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=model or "gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
            detail_full = response.choices[0].message.content.strip()

        elif provider_name == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model or "claude-sonnet-4-20250514",
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            detail_full = response.content[0].text.strip()

        elif provider_name == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model_obj = genai.GenerativeModel(model or "gemini-2.0-flash")
            full_prompt = f"{system_prompt}\n\n{user_prompt}"
            response = model_obj.generate_content(full_prompt)
            detail_full = response.text.strip()

        else:
            logger.error(f"Unknown provider {provider_name} - cannot synthesize detail_full")
            return DetailFullResult(
                detail_full="",
                spans=[],
                status="failed_llm",
                failure_reason=f"Unknown provider: {provider_name}"
            )

        # Validate output isn't garbled
        if _detect_garbled_output(body, detail_full):
            logger.error(f"Synthesis fallback produced garbled output for {provider_name}")
            return DetailFullResult(
                detail_full="",
                spans=[],
                status="failed_garbled",
                failure_reason="LLM synthesis produced garbled output"
            )

        # Success - return with empty spans (spans detected separately)
        return DetailFullResult(detail_full=detail_full, spans=[])

    except Exception as e:
        logger.error(f"Synthesis fallback failed for {provider_name}: {e}")
        return DetailFullResult(
            detail_full="",
            spans=[],
            status="failed_llm",
            failure_reason=f"LLM synthesis exception: {str(e)}"
        )


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

    # Check for garbled output (over-filtered, broken grammar)
    if _detect_garbled_output(original_body, filtered_article):
        raise NeutralizationResponseError(
            "Garbled output detected - LLM over-filtered the content leaving broken grammar. "
            "Falling back to mock provider for cleaner output."
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
        """Neutralize using OpenAI API.

        Raises NeutralizationResponseError if no API key or neutralization fails.
        """
        if not self._api_key:
            logger.error("No OPENAI_API_KEY set - cannot neutralize")
            raise NeutralizationResponseError("No OPENAI_API_KEY configured")

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

        except NeutralizationResponseError:
            raise  # Re-raise our own exceptions
        except Exception as e:
            logger.error(f"OpenAI neutralization failed: {e}")
            raise NeutralizationResponseError(f"OpenAI neutralization failed: {str(e)}")

    def _neutralize_detail_full(self, body: str, retry_count: int = 0) -> DetailFullResult:
        """
        Neutralize an article body using OpenAI with SYNTHESIS approach.

        Uses synthesis mode (plain text output) as the primary approach because:
        - LLMs are better at generating fresh text than surgical editing
        - No position tracking = better grammar preservation
        - More consistent, readable output

        Spans are detected via hybrid LLM + position matching:
        1. LLM identifies manipulative phrases with context awareness
        2. Position matcher finds exact character positions in original body
        3. Returns failure status if LLM fails (no mock fallback)
        """
        MAX_RETRIES = 2

        if not body:
            return DetailFullResult(detail_full="", spans=[])

        if not self._api_key:
            logger.error("No OPENAI_API_KEY set - cannot neutralize")
            return DetailFullResult(
                detail_full="",
                spans=[],
                status="failed_llm",
                failure_reason="No OPENAI_API_KEY configured"
            )

        # Get spans via config-aware detection (respects SPAN_DETECTION_MODE)
        # Uses multi_pass for 99% recall if configured, otherwise single-pass
        spans = _detect_spans_with_config(
            body=body,
            provider_api_key=self._api_key,
            provider_type="openai",
            provider_model=self._model,
        )
        logger.info(f"Span detection completed with {len(spans)} spans")

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self._api_key)

            # Use SYNTHESIS prompt (plain text output, not JSON)
            system_prompt = get_article_system_prompt()
            user_prompt = build_synthesis_detail_full_prompt(body)

            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                # No JSON format - plain text synthesis
            )

            detail_full = response.choices[0].message.content.strip()

            # Validate output isn't garbled
            if _detect_garbled_output(body, detail_full):
                logger.error("OpenAI synthesis produced garbled output")
                return DetailFullResult(
                    detail_full="",
                    spans=spans,
                    status="failed_garbled",
                    failure_reason="OpenAI synthesis produced garbled output"
                )

            return DetailFullResult(detail_full=detail_full, spans=spans)

        except Exception as e:
            # API error - retry, then return failure status
            if retry_count < MAX_RETRIES:
                logger.warning(
                    f"OpenAI synthesis error (attempt {retry_count + 1}/{MAX_RETRIES + 1}): {e}, retrying..."
                )
                import time
                time.sleep(1)
                return self._neutralize_detail_full(body, retry_count + 1)
            else:
                logger.error(f"OpenAI synthesis failed after {MAX_RETRIES + 1} attempts: {e}")
                return DetailFullResult(
                    detail_full="",
                    spans=spans,
                    status="failed_llm",
                    failure_reason=f"OpenAI synthesis failed after {MAX_RETRIES + 1} attempts: {str(e)}"
                )

    def _neutralize_detail_brief(self, body: str) -> str:
        """
        Synthesize an article body into a brief using OpenAI (Call 2: Synthesize).

        Uses shared article_system_prompt + synthesis_detail_brief_prompt.
        Returns plain text (3-5 paragraphs, no headers or bullets).

        Includes retry logic: if the brief contains banned phrases, retry with
        a repair prompt up to MAX_BRIEF_RETRIES times.

        Raises NeutralizationResponseError if no API key or synthesis fails.
        """
        MAX_BRIEF_RETRIES = 2

        if not body:
            return ""

        if not self._api_key:
            logger.error("No OPENAI_API_KEY set - cannot synthesize brief")
            raise NeutralizationResponseError("No OPENAI_API_KEY configured")

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

            brief = response.choices[0].message.content.strip()

            # Validate and retry if violations found
            for attempt in range(MAX_BRIEF_RETRIES):
                violations = validate_brief_neutralization(brief)
                if not violations:
                    return brief

                logger.warning(
                    f"Brief validation failed (attempt {attempt + 1}/{MAX_BRIEF_RETRIES + 1}): {violations}"
                )

                # Generate repair prompt and retry
                repair_prompt = build_brief_repair_prompt(brief, violations)
                repair_response = client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": repair_prompt},
                    ],
                    temperature=0.3,
                )
                brief = repair_response.choices[0].message.content.strip()

            # Final validation after all retries
            violations = validate_brief_neutralization(brief)
            if violations:
                logger.error(
                    f"Brief validation failed after {MAX_BRIEF_RETRIES + 1} attempts: {violations}"
                )
            return brief

        except Exception as e:
            logger.error(f"OpenAI detail_brief synthesis failed: {e}")
            raise NeutralizationResponseError(f"OpenAI detail_brief synthesis failed: {str(e)}")

    def _neutralize_feed_outputs(self, body: str, detail_brief: str) -> dict:
        """
        Generate compressed feed outputs using OpenAI (Call 3: Compress).

        Uses shared article_system_prompt + compression_feed_outputs_prompt.
        Returns dict with feed_title, feed_summary, detail_title.

        Includes validation and retry for feed_summary banned phrases.
        """
        MAX_FEED_SUMMARY_RETRIES = 2

        if not body and not detail_brief:
            return {
                "feed_title": "",
                "feed_summary": "",
                "detail_title": "",
                "section": "world",
            }

        if not self._api_key:
            logger.error("No OPENAI_API_KEY set - cannot generate feed outputs")
            raise NeutralizationResponseError("No OPENAI_API_KEY configured")

        try:
            import json
            from openai import OpenAI
            client = OpenAI(api_key=self._api_key)

            # Use lighter headline prompt for feed outputs (not aggressive article prompt)
            system_prompt = get_headline_system_prompt()
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
            result = {
                "feed_title": data.get("feed_title", ""),
                "feed_summary": data.get("feed_summary", ""),
                "detail_title": data.get("detail_title", ""),
                "section": data.get("section", "world"),
            }

            # Validate and retry feed_summary if it contains banned phrases
            for attempt in range(MAX_FEED_SUMMARY_RETRIES):
                violations = validate_feed_summary(result['feed_summary'])
                if not violations:
                    break

                logger.warning(
                    f"Feed summary validation failed (attempt {attempt + 1}/{MAX_FEED_SUMMARY_RETRIES + 1}): {violations}"
                )

                # Generate repair prompt and retry
                repair_prompt = build_feed_summary_repair_prompt(result['feed_summary'], violations)
                repair_response = client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": "You are a neutral news editor. Return only the rewritten text."},
                        {"role": "user", "content": repair_prompt},
                    ],
                    temperature=0.3,
                )
                result['feed_summary'] = repair_response.choices[0].message.content.strip()

            # Final validation
            violations = validate_feed_summary(result['feed_summary'])
            if violations:
                logger.error(
                    f"Feed summary validation failed after {MAX_FEED_SUMMARY_RETRIES + 1} attempts: {violations}"
                )

            # Apply sentence-boundary truncation as safety net
            result['feed_summary'] = truncate_at_sentence(result['feed_summary'], 130)

            # Validate feed outputs for garbled content
            _validate_feed_outputs(result)
            return result

        except Exception as e:
            logger.error(f"OpenAI feed outputs compression failed: {e}")
            raise NeutralizationResponseError(f"OpenAI feed outputs compression failed: {str(e)}")


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
        """Neutralize using Google Gemini API.

        Raises NeutralizationResponseError if no API key or neutralization fails.
        """
        if not self._api_key:
            logger.error("No GOOGLE_API_KEY or GEMINI_API_KEY set - cannot neutralize")
            raise NeutralizationResponseError("No GOOGLE_API_KEY or GEMINI_API_KEY configured")

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

        except NeutralizationResponseError:
            raise  # Re-raise our own exceptions
        except Exception as e:
            logger.error(f"Gemini neutralization failed: {e}")
            raise NeutralizationResponseError(f"Gemini neutralization failed: {str(e)}")

    def _neutralize_detail_full(self, body: str, retry_count: int = 0) -> DetailFullResult:
        """
        Neutralize an article body using Gemini with SYNTHESIS approach.

        Uses synthesis mode (plain text output) as the primary approach.
        Spans are detected via hybrid LLM + position matching for context awareness.
        Returns failure status if synthesis fails (no mock fallback).
        """
        MAX_RETRIES = 2

        if not body:
            return DetailFullResult(detail_full="", spans=[])

        if not self._api_key:
            logger.error("No GOOGLE_API_KEY or GEMINI_API_KEY set - cannot neutralize")
            return DetailFullResult(
                detail_full="",
                spans=[],
                status="failed_llm",
                failure_reason="No GOOGLE_API_KEY or GEMINI_API_KEY configured"
            )

        # Get spans via config-aware detection (respects SPAN_DETECTION_MODE)
        # Uses multi_pass for 99% recall if configured, otherwise single-pass
        spans = _detect_spans_with_config(
            body=body,
            provider_api_key=self._api_key,
            provider_type="gemini",
            provider_model=self._model,
        )
        logger.info(f"Span detection completed with {len(spans)} spans")

        try:
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)

            # Use SYNTHESIS prompt (plain text output, not JSON)
            system_prompt = get_article_system_prompt()
            user_prompt = build_synthesis_detail_full_prompt(body)

            model = genai.GenerativeModel(
                self._model,
                system_instruction=system_prompt,
                generation_config=genai.GenerationConfig(
                    # No JSON mime type - plain text synthesis
                    temperature=0.3,
                ),
            )

            response = model.generate_content(user_prompt)
            detail_full = response.text.strip()

            # Validate output isn't garbled
            if _detect_garbled_output(body, detail_full):
                logger.error("Gemini synthesis produced garbled output")
                return DetailFullResult(
                    detail_full="",
                    spans=spans,
                    status="failed_garbled",
                    failure_reason="Gemini synthesis produced garbled output"
                )

            return DetailFullResult(detail_full=detail_full, spans=spans)

        except Exception as e:
            # API error - retry, then return failure status
            if retry_count < MAX_RETRIES:
                logger.warning(
                    f"Gemini synthesis error (attempt {retry_count + 1}/{MAX_RETRIES + 1}): {e}, retrying..."
                )
                import time
                time.sleep(1)
                return self._neutralize_detail_full(body, retry_count + 1)
            else:
                logger.error(f"Gemini synthesis failed after {MAX_RETRIES + 1} attempts: {e}")
                return DetailFullResult(
                    detail_full="",
                    spans=spans,
                    status="failed_llm",
                    failure_reason=f"Gemini synthesis failed after {MAX_RETRIES + 1} attempts: {str(e)}"
                )

    def _neutralize_detail_brief(self, body: str) -> str:
        """
        Synthesize an article body into a brief using Gemini (Call 2: Synthesize).

        Uses shared article_system_prompt + synthesis_detail_brief_prompt.
        Returns plain text (3-5 paragraphs, no headers or bullets).

        Includes retry logic: if the brief contains banned phrases, retry with
        a repair prompt up to MAX_BRIEF_RETRIES times.

        Raises NeutralizationResponseError if no API key or synthesis fails.
        """
        MAX_BRIEF_RETRIES = 2

        if not body:
            return ""

        if not self._api_key:
            logger.error("No GOOGLE_API_KEY or GEMINI_API_KEY set - cannot synthesize brief")
            raise NeutralizationResponseError("No GOOGLE_API_KEY or GEMINI_API_KEY configured")

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
            brief = response.text.strip()

            # Validate and retry if violations found
            for attempt in range(MAX_BRIEF_RETRIES):
                violations = validate_brief_neutralization(brief)
                if not violations:
                    return brief

                logger.warning(
                    f"Brief validation failed (attempt {attempt + 1}/{MAX_BRIEF_RETRIES + 1}): {violations}"
                )

                # Generate repair prompt and retry
                repair_prompt = build_brief_repair_prompt(brief, violations)
                repair_response = model.generate_content(repair_prompt)
                brief = repair_response.text.strip()

            # Final validation after all retries
            violations = validate_brief_neutralization(brief)
            if violations:
                logger.error(
                    f"Brief validation failed after {MAX_BRIEF_RETRIES + 1} attempts: {violations}"
                )
            return brief

        except Exception as e:
            logger.error(f"Gemini detail_brief synthesis failed: {e}")
            raise NeutralizationResponseError(f"Gemini detail_brief synthesis failed: {str(e)}")

    def _neutralize_feed_outputs(self, body: str, detail_brief: str) -> dict:
        """
        Generate compressed feed outputs using Gemini (Call 3: Compress).

        Uses shared article_system_prompt + compression_feed_outputs_prompt.
        Returns dict with feed_title, feed_summary, detail_title, section.

        Includes validation and retry for feed_summary banned phrases.

        Raises NeutralizationResponseError if no API key or compression fails.
        """
        MAX_FEED_SUMMARY_RETRIES = 2

        if not body and not detail_brief:
            return {
                "feed_title": "",
                "feed_summary": "",
                "detail_title": "",
                "section": "world",
            }

        if not self._api_key:
            logger.error("No GOOGLE_API_KEY or GEMINI_API_KEY set - cannot generate feed outputs")
            raise NeutralizationResponseError("No GOOGLE_API_KEY or GEMINI_API_KEY configured")

        try:
            import json
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)

            # Use lighter headline prompt for feed outputs (not aggressive article prompt)
            system_prompt = get_headline_system_prompt()
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
            result = {
                "feed_title": data.get("feed_title", ""),
                "feed_summary": data.get("feed_summary", ""),
                "detail_title": data.get("detail_title", ""),
                "section": data.get("section", "world"),
            }

            # Validate and retry feed_summary if it contains banned phrases
            repair_model = genai.GenerativeModel(
                self._model,
                system_instruction="You are a neutral news editor. Return only the rewritten text.",
                generation_config=genai.GenerationConfig(temperature=0.3),
            )

            for attempt in range(MAX_FEED_SUMMARY_RETRIES):
                violations = validate_feed_summary(result['feed_summary'])
                if not violations:
                    break

                logger.warning(
                    f"Feed summary validation failed (attempt {attempt + 1}/{MAX_FEED_SUMMARY_RETRIES + 1}): {violations}"
                )

                # Generate repair prompt and retry
                repair_prompt = build_feed_summary_repair_prompt(result['feed_summary'], violations)
                repair_response = repair_model.generate_content(repair_prompt)
                result['feed_summary'] = repair_response.text.strip()

            # Final validation
            violations = validate_feed_summary(result['feed_summary'])
            if violations:
                logger.error(
                    f"Feed summary validation failed after {MAX_FEED_SUMMARY_RETRIES + 1} attempts: {violations}"
                )

            # Apply sentence-boundary truncation as safety net
            result['feed_summary'] = truncate_at_sentence(result['feed_summary'], 130)

            # Validate feed outputs for garbled content
            _validate_feed_outputs(result)
            return result

        except Exception as e:
            logger.error(f"Gemini feed outputs compression failed: {e}")
            raise NeutralizationResponseError(f"Gemini feed outputs compression failed: {str(e)}")


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
        """Neutralize using Anthropic Claude API.

        Raises NeutralizationResponseError if no API key or neutralization fails.
        """
        if not self._api_key:
            logger.error("No ANTHROPIC_API_KEY set - cannot neutralize")
            raise NeutralizationResponseError("No ANTHROPIC_API_KEY configured")

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

        except NeutralizationResponseError:
            raise  # Re-raise our own exceptions
        except Exception as e:
            logger.error(f"Anthropic neutralization failed: {e}")
            raise NeutralizationResponseError(f"Anthropic neutralization failed: {str(e)}")

    def _neutralize_detail_full(self, body: str, retry_count: int = 0) -> DetailFullResult:
        """
        Neutralize an article body using Anthropic Claude with SYNTHESIS approach.

        Uses synthesis mode (plain text output) as the primary approach.
        Spans are detected via hybrid LLM + position matching for context awareness.
        Returns failure status if synthesis fails (no mock fallback).
        """
        MAX_RETRIES = 2

        if not body:
            return DetailFullResult(detail_full="", spans=[])

        if not self._api_key:
            logger.error("No ANTHROPIC_API_KEY set - cannot neutralize")
            return DetailFullResult(
                detail_full="",
                spans=[],
                status="failed_llm",
                failure_reason="No ANTHROPIC_API_KEY configured"
            )

        # Get spans via config-aware detection (respects SPAN_DETECTION_MODE)
        # Uses multi_pass for 99% recall if configured, otherwise single-pass
        spans = _detect_spans_with_config(
            body=body,
            provider_api_key=self._api_key,
            provider_type="anthropic",
            provider_model=self._model,
        )
        logger.info(f"Span detection completed with {len(spans)} spans")

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self._api_key)

            # Use SYNTHESIS prompt (plain text output, not JSON)
            system_prompt = get_article_system_prompt()
            user_prompt = build_synthesis_detail_full_prompt(body)

            response = client.messages.create(
                model=self._model,
                max_tokens=8192,  # Larger max for full article synthesis
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt},
                ],
            )

            detail_full = response.content[0].text.strip()

            # Validate output isn't garbled
            if _detect_garbled_output(body, detail_full):
                logger.error("Anthropic synthesis produced garbled output")
                return DetailFullResult(
                    detail_full="",
                    spans=spans,
                    status="failed_garbled",
                    failure_reason="Anthropic synthesis produced garbled output"
                )

            return DetailFullResult(detail_full=detail_full, spans=spans)

        except Exception as e:
            # API error - retry, then return failure status
            if retry_count < MAX_RETRIES:
                logger.warning(
                    f"Anthropic synthesis error (attempt {retry_count + 1}/{MAX_RETRIES + 1}): {e}, retrying..."
                )
                import time
                time.sleep(1)
                return self._neutralize_detail_full(body, retry_count + 1)
            else:
                logger.error(f"Anthropic synthesis failed after {MAX_RETRIES + 1} attempts: {e}")
                return DetailFullResult(
                    detail_full="",
                    spans=spans,
                    status="failed_llm",
                    failure_reason=f"Anthropic synthesis failed after {MAX_RETRIES + 1} attempts: {str(e)}"
                )

    def _neutralize_detail_brief(self, body: str) -> str:
        """
        Synthesize an article body into a brief using Anthropic Claude (Call 2: Synthesize).

        Uses shared article_system_prompt + synthesis_detail_brief_prompt.
        Returns plain text (3-5 paragraphs, no headers or bullets).

        Includes retry logic: if the brief contains banned phrases, retry with
        a repair prompt up to MAX_BRIEF_RETRIES times.

        Raises NeutralizationResponseError if no API key or synthesis fails.
        """
        MAX_BRIEF_RETRIES = 2

        if not body:
            return ""

        if not self._api_key:
            logger.error("No ANTHROPIC_API_KEY set - cannot synthesize brief")
            raise NeutralizationResponseError("No ANTHROPIC_API_KEY configured")

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

            brief = response.content[0].text.strip()

            # Validate and retry if violations found
            for attempt in range(MAX_BRIEF_RETRIES):
                violations = validate_brief_neutralization(brief)
                if not violations:
                    return brief

                logger.warning(
                    f"Brief validation failed (attempt {attempt + 1}/{MAX_BRIEF_RETRIES + 1}): {violations}"
                )

                # Generate repair prompt and retry
                repair_prompt = build_brief_repair_prompt(brief, violations)
                repair_response = client.messages.create(
                    model=self._model,
                    max_tokens=2048,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": repair_prompt},
                    ],
                )
                brief = repair_response.content[0].text.strip()

            # Final validation after all retries
            violations = validate_brief_neutralization(brief)
            if violations:
                logger.error(
                    f"Brief validation failed after {MAX_BRIEF_RETRIES + 1} attempts: {violations}"
                )
            return brief

        except Exception as e:
            logger.error(f"Anthropic detail_brief synthesis failed: {e}")
            raise NeutralizationResponseError(f"Anthropic detail_brief synthesis failed: {str(e)}")

    def _neutralize_feed_outputs(self, body: str, detail_brief: str) -> dict:
        """
        Generate compressed feed outputs using Anthropic Claude (Call 3: Compress).

        Uses shared article_system_prompt + compression_feed_outputs_prompt.
        Returns dict with feed_title, feed_summary, detail_title, section.

        Includes validation and retry for feed_summary banned phrases.

        Raises NeutralizationResponseError if no API key or compression fails.
        """
        MAX_FEED_SUMMARY_RETRIES = 2

        if not body and not detail_brief:
            return {
                "feed_title": "",
                "feed_summary": "",
                "detail_title": "",
                "section": "world",
            }

        if not self._api_key:
            logger.error("No ANTHROPIC_API_KEY set - cannot generate feed outputs")
            raise NeutralizationResponseError("No ANTHROPIC_API_KEY configured")

        try:
            import json
            import anthropic
            client = anthropic.Anthropic(api_key=self._api_key)

            # Use lighter headline prompt for feed outputs (not aggressive article prompt)
            system_prompt = get_headline_system_prompt()
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
            result = {
                "feed_title": data.get("feed_title", ""),
                "feed_summary": data.get("feed_summary", ""),
                "detail_title": data.get("detail_title", ""),
                "section": data.get("section", "world"),
            }

            # Validate and retry feed_summary if it contains banned phrases
            for attempt in range(MAX_FEED_SUMMARY_RETRIES):
                violations = validate_feed_summary(result['feed_summary'])
                if not violations:
                    break

                logger.warning(
                    f"Feed summary validation failed (attempt {attempt + 1}/{MAX_FEED_SUMMARY_RETRIES + 1}): {violations}"
                )

                # Generate repair prompt and retry
                repair_prompt = build_feed_summary_repair_prompt(result['feed_summary'], violations)
                repair_response = client.messages.create(
                    model=self._model,
                    max_tokens=256,
                    system="You are a neutral news editor. Return only the rewritten text.",
                    messages=[
                        {"role": "user", "content": repair_prompt},
                    ],
                )
                result['feed_summary'] = repair_response.content[0].text.strip()

            # Final validation
            violations = validate_feed_summary(result['feed_summary'])
            if violations:
                logger.error(
                    f"Feed summary validation failed after {MAX_FEED_SUMMARY_RETRIES + 1} attempts: {violations}"
                )

            # Apply sentence-boundary truncation as safety net
            result['feed_summary'] = truncate_at_sentence(result['feed_summary'], 130)

            # Validate feed outputs for garbled content
            _validate_feed_outputs(result)
            return result

        except Exception as e:
            logger.error(f"Anthropic feed outputs compression failed: {e}")
            raise NeutralizationResponseError(f"Anthropic feed outputs compression failed: {str(e)}")


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

                    # Check for failure status (new architecture: no mock fallback)
                    if detail_full_result.status != "success":
                        logger.error(
                            f"Neutralization FAILED for story {story.id}: "
                            f"status={detail_full_result.status}, "
                            f"reason={detail_full_result.failure_reason}"
                        )
                        # Save failed record to database for tracking
                        version = 1
                        if existing:
                            existing.is_current = False
                            version = existing.version + 1

                        failed_neutralized = models.StoryNeutralized(
                            id=uuid.uuid4(),
                            story_raw_id=story.id,
                            version=version,
                            is_current=True,
                            feed_title="",
                            feed_summary="",
                            detail_title="",
                            detail_brief="",
                            detail_full="",
                            disclosure="",
                            has_manipulative_content=False,
                            model_name=self.provider.model_name,
                            prompt_version="v3",
                            neutralization_status=detail_full_result.status,
                            failure_reason=detail_full_result.failure_reason,
                            created_at=datetime.utcnow(),
                        )
                        db.add(failed_neutralized)
                        db.flush()

                        self._log_pipeline(
                            db,
                            stage=PipelineStage.NEUTRALIZE,
                            status=PipelineStatus.FAILED,
                            story_raw_id=story.id,
                            started_at=started_at,
                            error_message=detail_full_result.failure_reason,
                            metadata={
                                'failure_status': detail_full_result.status,
                            },
                        )
                        return None

                    transparency_spans = detail_full_result.spans

                    # V2 pattern-based detection disabled - produces too many false positives
                    # (256+ spans per article vs ~20-50 from LLM). The regex/spaCy patterns
                    # flag neutral news language like "Sunday", "protesters", "intensive".
                    # LLM detection is contextually aware and sufficient.
                    # See: https://github.com/anthropics/claude-code/issues/XXX
                    #
                    # try:
                    #     enhanced_spans = _enhance_spans_with_v2_scan(body, transparency_spans)
                    #     if len(enhanced_spans) != len(transparency_spans):
                    #         logger.info(
                    #             f"Story {story.id}: V2 scan enhanced spans "
                    #             f"({len(transparency_spans)} LLM → {len(enhanced_spans)} total)"
                    #         )
                    #     transparency_spans = enhanced_spans
                    # except Exception as e:
                    #     logger.warning(f"V2 scan enhancement failed for story {story.id}: {e}")
                    #     # Continue with LLM spans only
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
                neutralization_status="success",
                failure_reason=None,
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

                    # V2 pattern-based detection disabled - produces too many false positives
                    # (256+ spans per article vs ~20-50 from LLM). The regex/spaCy patterns
                    # flag neutral news language like "Sunday", "protesters", "intensive".
                    # LLM detection is contextually aware and sufficient.
                    #
                    # try:
                    #     enhanced_spans = _enhance_spans_with_v2_scan(body, transparency_spans)
                    #     if len(enhanced_spans) != len(transparency_spans):
                    #         logger.info(
                    #             f"Story {story_id}: V2 scan enhanced spans "
                    #             f"({len(transparency_spans)} LLM → {len(enhanced_spans)} total)"
                    #         )
                    #     transparency_spans = enhanced_spans
                    # except Exception as e:
                    #     logger.warning(f"V2 scan enhancement failed for story {story_id}: {e}")
                    #     # Continue with LLM spans only
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
