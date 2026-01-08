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

logger = logging.getLogger(__name__)


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
    neutral_headline: str
    neutral_summary: str
    what_happened: Optional[str]
    why_it_matters: Optional[str]
    what_is_known: Optional[str]
    what_is_uncertain: Optional[str]
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
    ) -> NeutralizationResult:
        """
        Neutralize content and return result with spans.
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
    ) -> NeutralizationResult:
        """Neutralize content using pattern matching."""
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

        # Generate structured parts (simplified for mock)
        what_happened = neutral_summary.split('.')[0] + '.' if neutral_summary else None
        why_it_matters = None
        what_is_known = neutral_summary
        what_is_uncertain = "Further details are pending confirmation."

        return NeutralizationResult(
            neutral_headline=neutral_headline,
            neutral_summary=neutral_summary,
            what_happened=what_happened,
            why_it_matters=why_it_matters,
            what_is_known=what_is_known,
            what_is_uncertain=what_is_uncertain,
            has_manipulative_content=has_manipulative,
            spans=all_spans,
        )


# -----------------------------------------------------------------------------
# OpenAI provider (actual LLM)
# -----------------------------------------------------------------------------

class OpenAINeutralizerProvider(NeutralizerProvider):
    """OpenAI-based neutralizer."""

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
    ) -> NeutralizationResult:
        """Neutralize using OpenAI API."""
        if not self._api_key:
            # Fallback to mock if no API key
            return MockNeutralizerProvider().neutralize(title, description, body)

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self._api_key)

            system_prompt = """You are a neutral news editor for NTRL, a calm news service that removes manipulative language while preserving facts.

YOUR GOAL: Transform sensationalized news into calm, factual reporting. Think BBC World Service or AP wire style.

DETECT AND FLAG THESE MANIPULATIVE PATTERNS:

1. CLICKBAIT: Language designed to provoke curiosity without informing
   - "You won't believe...", "What happened next...", "The reason will surprise you"
   - ALL CAPS for emphasis, excessive punctuation (!!, ?!)
   - Vague teasers that withhold key information

2. URGENCY INFLATION: False or exaggerated time pressure
   - "BREAKING" (when not actually breaking), "JUST IN", "DEVELOPING"
   - "Act now", "Don't miss", implying scarcity where none exists

3. EMOTIONAL TRIGGERS: Words chosen to provoke reaction over understanding
   - Conflict words: "slams", "destroys", "eviscerates", "blasts", "rips"
   - Fear words: "terrifying", "alarming", "dangerous", "threat"
   - Outrage words: "shocking", "disgusting", "unbelievable", "insane"

4. AGENDA SIGNALING: Editorializing disguised as reporting
   - "Finally", "It's about time", "Long overdue" (implies the writer's view)
   - Loaded adjectives: "controversial", "divisive", "embattled" (without evidence)
   - Scare quotes around legitimate terms

5. RHETORICAL FRAMING: Structure that manipulates interpretation
   - Leading questions: "Is this the end of...?"
   - False equivalence or false balance
   - Burying the lede to prioritize sensational details

6. SELLING: Promotional language disguised as news
   - "Must-read", "Essential", "You need to know"
   - Superlatives without evidence: "best", "worst", "most important"

PRESERVE:
- All facts, data, statistics, dates, names, places
- Direct quotes with attribution
- Nuance, uncertainty, and complexity
- Multiple perspectives when present

OUTPUT STYLE:
- Calm, measured, factual
- Active voice, clear structure
- Present what is known, acknowledge what is not
- No judgment, no urgency, no hype"""

            user_prompt = f"""Analyze this news content and provide a neutral version.

ORIGINAL TITLE: {title}

ORIGINAL DESCRIPTION: {description or 'N/A'}

ORIGINAL BODY: {(body or '')[:3000]}

Respond with JSON:
{{
  "neutral_headline": "Rewrite the headline to be factual and calm. Remove hype but keep it informative.",
  "neutral_summary": "2-3 sentence summary answering: What happened? Why does it matter? Keep it factual.",
  "what_happened": "One clear sentence stating the core event/news.",
  "why_it_matters": "One sentence on significance or impact. Say 'Significance unclear' if not evident.",
  "what_is_known": "Confirmed facts from the article.",
  "what_is_uncertain": "What questions remain unanswered? What is speculation vs fact?",
  "manipulative_spans": [
    {{
      "field": "title or description or body",
      "start_char": 0,
      "end_char": 10,
      "original_text": "exact text that is manipulative",
      "action": "removed or replaced or softened",
      "reason": "clickbait or urgency_inflation or emotional_trigger or selling or agenda_signaling or rhetorical_framing",
      "replacement_text": "neutral replacement if action is replaced/softened, null if removed"
    }}
  ]
}}

If the content is already neutral and factual, return empty manipulative_spans array."""

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

            spans = []
            for span_data in data.get("manipulative_spans", []):
                try:
                    spans.append(TransparencySpan(
                        field=span_data.get("field", "title"),
                        start_char=span_data.get("start_char", 0),
                        end_char=span_data.get("end_char", 0),
                        original_text=span_data.get("original_text", ""),
                        action=SpanAction(span_data.get("action", "removed")),
                        reason=SpanReason(span_data.get("reason", "clickbait")),
                        replacement_text=span_data.get("replacement_text"),
                    ))
                except (ValueError, KeyError):
                    continue

            return NeutralizationResult(
                neutral_headline=data.get("neutral_headline", title),
                neutral_summary=data.get("neutral_summary", description or title),
                what_happened=data.get("what_happened"),
                why_it_matters=data.get("why_it_matters"),
                what_is_known=data.get("what_is_known"),
                what_is_uncertain=data.get("what_is_uncertain"),
                has_manipulative_content=len(spans) > 0,
                spans=spans,
            )

        except Exception as e:
            logger.error(f"OpenAI neutralization failed: {e}")
            # Fallback to mock
            return MockNeutralizerProvider().neutralize(title, description, body)


# -----------------------------------------------------------------------------
# Neutralizer service
# -----------------------------------------------------------------------------

def get_neutralizer_provider() -> NeutralizerProvider:
    """Get the configured neutralizer provider."""
    provider_name = os.getenv("NEUTRALIZER_PROVIDER", "mock")

    if provider_name == "openai":
        return OpenAINeutralizerProvider()
    else:
        return MockNeutralizerProvider()


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
        Neutralize a single story.

        Args:
            story: The raw story to neutralize
            force: Re-neutralize even if already done

        Returns:
            The neutralized story record, or None if skipped
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

            # Run neutralization
            result = self.provider.neutralize(
                title=story.original_title,
                description=story.original_description,
                body=body,
            )

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
                neutral_headline=result.neutral_headline,
                neutral_summary=result.neutral_summary,
                what_happened=result.what_happened,
                why_it_matters=result.why_it_matters,
                what_is_known=result.what_is_known,
                what_is_uncertain=result.what_is_uncertain,
                disclosure="Manipulative language removed." if result.has_manipulative_content else "",
                has_manipulative_content=result.has_manipulative_content,
                model_name=self.provider.model_name,
                prompt_version="v1",
                created_at=datetime.utcnow(),
            )
            db.add(neutralized)
            db.flush()

            # Create transparency spans
            for span in result.spans:
                span_record = models.TransparencySpan(
                    id=uuid.uuid4(),
                    story_neutralized_id=neutralized.id,
                    field=span.field,
                    start_char=span.start_char,
                    end_char=span.end_char,
                    original_text=span.original_text,
                    action=span.action.value,
                    reason=span.reason.value,
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
                    'has_manipulative': result.has_manipulative_content,
                    'span_count': len(result.spans),
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

    def neutralize_pending(
        self,
        db: Session,
        story_ids: Optional[List[str]] = None,
        force: bool = False,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Neutralize pending stories.

        Returns:
            Dict with processing results
        """
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
        }

        for story in stories:
            story_result = {
                'story_id': str(story.id),
                'status': 'completed',
                'neutral_headline': None,
                'has_manipulative_content': False,
                'span_count': 0,
                'error': None,
            }

            try:
                neutralized = self.neutralize_story(db, story, force=force)

                if neutralized:
                    story_result['neutral_headline'] = neutralized.neutral_headline
                    story_result['has_manipulative_content'] = neutralized.has_manipulative_content
                    story_result['span_count'] = len(neutralized.spans)
                    result['total_processed'] += 1
                else:
                    story_result['status'] = 'skipped'
                    result['total_skipped'] += 1

            except Exception as e:
                story_result['status'] = 'failed'
                story_result['error'] = str(e)
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
