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


# -----------------------------------------------------------------------------
# Provider abstraction
# -----------------------------------------------------------------------------

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


# -----------------------------------------------------------------------------
# Mock provider for testing
# -----------------------------------------------------------------------------

# Manipulative patterns to detect (for mock)
MANIPULATIVE_PATTERNS = {
    SpanReason.CLICKBAIT: [
        r'\b(shocking|unbelievable|you won\'t believe|mind-blowing|jaw-dropping)\b',
        r'\b(must see|must read|can\'t miss|don\'t miss)\b',
        r'\b(secret|hidden|exposed|revealed)\b',
    ],
    SpanReason.URGENCY_INFLATION: [
        r'\b(breaking|urgent|just in|developing|happening now)\b',
        r'\b(alert|emergency|crisis|chaos)\b',
    ],
    SpanReason.EMOTIONAL_TRIGGER: [
        r'\b(outrage|fury|furious|enraged|livid)\b',
        r'\b(slams|blasts|destroys|demolishes|eviscerates)\b',
        r'\b(heartbreaking|devastating|horrifying|terrifying)\b',
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
        )


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
- Purpose: Fast scanning in feed
- Length: ≤6 words preferred, 12 words maximum (hard cap)
- Content: Factual, neutral, descriptive
- Avoid: Emotional language, urgency, clickbait, questions, teasers

FEED SUMMARY (feed_summary)
- Purpose: Lightweight context
- Length: 1-2 complete sentences, must fit within 3 lines
- If 2 sentences don't fit cleanly, use a single shorter sentence

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

You are a FILTER, not a rewriter. Your job is to:
1. PRESERVE the full article content, structure, quotes, and factual detail
2. REMOVE only manipulative language, urgency inflation, and editorial framing
3. TRACK every change you make with transparency spans

═══════════════════════════════════════════════════════════════════════════════
PRESERVE EXACTLY
═══════════════════════════════════════════════════════════════════════════════

- Original paragraph structure and flow
- All direct quotes with their attribution
- All facts, names, dates, numbers, places, statistics
- Real tension, conflict, and uncertainty (these are news, not manipulation)
- Epistemic markers (alleged, suspected, confirmed, reportedly)
- Causal relationships as stated (don't infer motives)

═══════════════════════════════════════════════════════════════════════════════
REMOVE OR SOFTEN
═══════════════════════════════════════════════════════════════════════════════

1. URGENCY FRAMING
   - "BREAKING", "JUST IN", "DEVELOPING", "HAPPENING NOW"
   - False time pressure language

2. EMOTIONAL AMPLIFICATION
   - Conflict theater: "slams", "blasts", "destroys", "eviscerates", "torches"
   - Fear amplifiers: "terrifying", "alarming", "chilling", "horrifying"
   - Outrage bait: "shocking", "disgusting", "unbelievable", "insane"

3. EDITORIAL FRAMING
   - Loaded adjectives: "controversial", "embattled", "troubled", "disgraced"
   - Leading questions that imply answers
   - Weasel words: "some say", "critics say" (without attribution)

4. CLICKBAIT & SELLING
   - "You won't believe...", "Must see", "Essential"
   - ALL CAPS for emphasis (except acronyms)
   - Excessive punctuation (!!, ?!)

5. PUBLISHER CRUFT
   - Newsletter sign-up prompts
   - "Read more" or "Continue reading" calls to action
   - Social sharing prompts
   - Author bios and promotional content mid-article

═══════════════════════════════════════════════════════════════════════════════
DO NOT
═══════════════════════════════════════════════════════════════════════════════

- Add new facts, context, or explanation
- Remove facts even if uncomfortable
- Downshift factual severity ("killed" → "shot" is wrong if death occurred)
- Infer motives or intent beyond what's stated
- Soften real conflict into blandness
- Change quoted material (preserve exactly as written)

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
        Neutralize a single story with audit validation.

        Two-pass system:
        1. Neutralize content
        2. Audit output against NTRL rules
        3. Retry if audit fails (up to MAX_RETRY_ATTEMPTS)

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
            repair_instructions = None
            result = None
            audit_result = None

            # Neutralize with retry loop
            for attempt in range(MAX_RETRY_ATTEMPTS + 1):
                # Run neutralization
                result = self.provider.neutralize(
                    title=story.original_title,
                    description=story.original_description,
                    body=body,
                    repair_instructions=repair_instructions,
                )

                # Build model output for audit (use feed_title/feed_summary for current auditor)
                model_output = {
                    "neutral_headline": result.feed_title,
                    "neutral_summary": result.feed_summary,
                    "has_manipulative_content": result.has_manipulative_content,
                    "removed_phrases": [],  # We don't track these granularly yet
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
                        repair_instructions = audit_result.suggested_action.repair_instructions
                        logger.info(f"Retrying with: {repair_instructions}")
                    else:
                        # Max retries exceeded
                        logger.warning(f"Story {story.id} failed audit after {MAX_RETRY_ATTEMPTS} retries")

            # Determine version
            version = 1
            if existing:
                existing.is_current = False
                version = existing.version + 1

            # Create neutralized record
            neutralized = models.StoryNeutralized(
                id=uuid.uuid4(),
                story_raw_id=story.id,
                version=version,
                is_current=True,
                feed_title=result.feed_title,
                feed_summary=result.feed_summary,
                detail_title=result.detail_title,
                detail_brief=result.detail_brief,
                detail_full=result.detail_full,
                disclosure="Manipulative language removed." if result.has_manipulative_content else "",
                has_manipulative_content=result.has_manipulative_content,
                model_name=self.provider.model_name,
                prompt_version="v2",  # Updated prompt version
                created_at=datetime.utcnow(),
            )
            db.add(neutralized)
            db.flush()

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
                    'has_manipulative': result.has_manipulative_content,
                    'audit_verdict': audit_result.verdict.value if audit_result else 'none',
                    'retry_count': attempt if 'attempt' in dir() else 0,
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
        Neutralize content using LLM (thread-safe, no db operations).

        This method can be called in parallel from multiple threads.

        Returns:
            Dict with neutralization result or error
        """
        from app.services.auditor import Auditor, AuditVerdict

        try:
            auditor = Auditor()
            repair_instructions = None
            result = None
            audit_result = None
            attempt = 0

            # Neutralize with retry loop
            for attempt in range(MAX_RETRY_ATTEMPTS + 1):
                result = self.provider.neutralize(
                    title=title,
                    description=description,
                    body=body,
                    repair_instructions=repair_instructions,
                )

                # Build model output for audit (use feed_title/feed_summary for current auditor)
                model_output = {
                    "neutral_headline": result.feed_title,
                    "neutral_summary": result.feed_summary,
                    "has_manipulative_content": result.has_manipulative_content,
                    "removed_phrases": [],
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
                        repair_instructions = audit_result.suggested_action.repair_instructions
                        logger.info(f"Retrying with: {repair_instructions}")
                    else:
                        logger.warning(f"Story {story_id} failed audit after {MAX_RETRY_ATTEMPTS} retries")

            return {
                'story_id': story_id,
                'status': 'completed',
                'result': result,
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
        query = db.query(models.StoryRaw).filter(models.StoryRaw.is_duplicate == False)

        if story_ids:
            query = query.filter(models.StoryRaw.id.in_([uuid.UUID(sid) for sid in story_ids]))
        elif not force:
            # Only get stories without current neutralization
            subq = (
                db.query(models.StoryNeutralized.story_raw_id)
                .filter(models.StoryNeutralized.is_current == True)
            )
            query = query.filter(~models.StoryRaw.id.in_(subq))

        stories = query.limit(limit).all()

        result = {
            'status': 'completed',
            'started_at': started_at,
            'finished_at': None,
            'duration_ms': 0,
            'total_processed': 0,
            'total_skipped': 0,
            'total_failed': 0,
            'story_results': [],
            'max_workers': max_workers,
        }

        if not stories:
            result['finished_at'] = datetime.utcnow()
            result['duration_ms'] = int((result['finished_at'] - started_at).total_seconds() * 1000)
            return result

        # Prepare data for parallel processing (extract from ORM objects)
        story_data = []
        for story in stories:
            body = _get_body_from_storage(story)
            story_data.append({
                'story_id': story.id,
                'title': story.original_title,
                'description': story.original_description,
                'body': body,
                'story_obj': story,  # Keep reference for db operations
            })

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
                    prompt_version="v2",
                    created_at=datetime.utcnow(),
                )
                db.add(neutralized)

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
                        'audit_verdict': llm_result.get('audit_verdict', 'none'),
                        'retry_count': llm_result.get('retry_count', 0),
                    },
                )

                story_result['feed_title'] = neutralization.feed_title
                story_result['has_manipulative_content'] = neutralization.has_manipulative_content
                story_result['span_count'] = 0
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
