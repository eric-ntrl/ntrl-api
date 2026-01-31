# app/routers/stories.py
"""
Story endpoints.

GET /v1/stories/{id} - Get story detail (neutralized content first)
GET /v1/stories/{id}/transparency - Get transparency view with what was removed
"""

import concurrent.futures
import logging
import uuid
from typing import List, Optional

from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.schemas.stories import (
    StoryDetail,
    StoryTransparency,
    TransparencySpanResponse,
    StoryDebug,
    SpanDetectionDebug,
    PipelineTrace,
    LLMPhraseItem,
)
from app.storage.factory import get_storage_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/stories", tags=["stories"])

# In-memory cache for story detail (1 hour TTL, max 200 entries)
_story_cache: TTLCache = TTLCache(maxsize=200, ttl=3600)
# In-memory cache for transparency data (1 hour TTL, max 200 entries)
_transparency_cache: TTLCache = TTLCache(maxsize=200, ttl=3600)


def invalidate_transparency_cache(story_id: str) -> bool:
    """
    Invalidate the transparency cache for a specific story.

    Called when an article is re-neutralized to ensure fresh data is returned.

    Args:
        story_id: The story ID to invalidate (can be raw_id or neutralized_id)

    Returns:
        True if the entry was found and removed, False otherwise
    """
    if story_id in _transparency_cache:
        del _transparency_cache[story_id]
        return True
    return False


def _do_download(uri: str) -> Optional[str]:
    """Download content from storage (runs in thread for timeout support)."""
    storage = get_storage_provider()
    result = storage.download(uri)
    if result and result.exists:
        return result.content.decode("utf-8")
    return None


def _get_body_from_storage(story_raw: models.StoryRaw, timeout_seconds: int = 8) -> Optional[str]:
    """
    Retrieve body content from object storage with timeout.

    Returns None if:
    - No content was stored
    - Content has expired
    - Storage retrieval fails
    - Download exceeds timeout_seconds
    """
    if not story_raw.raw_content_available or not story_raw.raw_content_uri:
        return None

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_download, story_raw.raw_content_uri)
            return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError:
        logger.warning(f"Storage download timed out after {timeout_seconds}s")
        return None
    except Exception as e:
        logger.warning(f"Failed to retrieve body from storage: {e}")
        return None


def _get_story_or_404(db: Session, story_id: str) -> tuple:
    """Get story with neutralization or raise 404.

    Always returns the current neutralization, even if an old
    neutralized ID is passed. This ensures transparency data
    reflects the latest neutralization.
    """
    try:
        story_uuid = uuid.UUID(story_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid story ID format")

    # First try to find by neutralized ID
    neutralized = (
        db.query(models.StoryNeutralized)
        .filter(models.StoryNeutralized.id == story_uuid)
        .first()
    )

    if neutralized:
        story_raw = neutralized.story_raw
        # If this is an old version, get the current one instead
        if not neutralized.is_current:
            current = (
                db.query(models.StoryNeutralized)
                .filter(
                    models.StoryNeutralized.story_raw_id == story_raw.id,
                    models.StoryNeutralized.is_current == True,
                )
                .first()
            )
            if current:
                neutralized = current
    else:
        # Try by raw story ID
        story_raw = (
            db.query(models.StoryRaw)
            .filter(models.StoryRaw.id == story_uuid)
            .first()
        )

        if not story_raw:
            raise HTTPException(status_code=404, detail="Story not found")

        # Get current neutralization
        neutralized = (
            db.query(models.StoryNeutralized)
            .filter(
                models.StoryNeutralized.story_raw_id == story_raw.id,
                models.StoryNeutralized.is_current == True,
            )
            .first()
        )

        if not neutralized:
            raise HTTPException(
                status_code=404,
                detail="Story has not been neutralized yet",
            )

    source = story_raw.source
    return neutralized, story_raw, source


# -----------------------------------------------------------------------------
# List Stories
# -----------------------------------------------------------------------------

from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime

class StoryListItem(BaseModel):
    """Story list item showing before/after comparison."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    # Original (before)
    original_title: str
    original_description: Optional[str]
    # Filtered (after)
    feed_title: Optional[str]
    feed_summary: Optional[str]
    # Metadata
    source_name: str
    source_slug: str
    source_url: str
    published_at: datetime
    section: Optional[str]
    has_manipulative_content: bool
    is_neutralized: bool


class StoryListResponse(BaseModel):
    """List of stories."""
    stories: List[StoryListItem]
    total: int


@router.get("", response_model=StoryListResponse)
def list_stories(
    source_slug: Optional[str] = None,
    neutralized_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> StoryListResponse:
    """
    List stories with before/after comparison.

    Filter by source_slug or show only neutralized stories.
    """
    query = (
        db.query(models.StoryRaw)
        .filter(models.StoryRaw.is_duplicate == False)
        .join(models.Source)
    )

    if source_slug:
        query = query.filter(models.Source.slug == source_slug)

    if neutralized_only:
        query = query.join(
            models.StoryNeutralized,
            models.StoryRaw.id == models.StoryNeutralized.story_raw_id
        ).filter(
            models.StoryNeutralized.is_current == True,
            models.StoryNeutralized.neutralization_status == "success",  # Only show successful
        )

    total = query.count()
    stories_raw = (
        query
        .order_by(models.StoryRaw.published_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    result = []
    for story in stories_raw:
        # Get current neutralization if exists
        neutralized = (
            db.query(models.StoryNeutralized)
            .filter(
                models.StoryNeutralized.story_raw_id == story.id,
                models.StoryNeutralized.is_current == True
            )
            .first()
        )

        result.append(StoryListItem(
            id=str(story.id),
            original_title=story.original_title,
            original_description=story.original_description,
            feed_title=neutralized.feed_title if neutralized else None,
            feed_summary=neutralized.feed_summary if neutralized else None,
            source_name=story.source.name,
            source_slug=story.source.slug,
            source_url=story.original_url,
            published_at=story.published_at,
            section=story.section,
            has_manipulative_content=neutralized.has_manipulative_content if neutralized else False,
            is_neutralized=neutralized is not None,
        ))

    return StoryListResponse(stories=result, total=total)


@router.get("/{story_id}", response_model=StoryDetail)
def get_story(
    story_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> StoryDetail:
    """
    Get story detail.

    Shows neutralized/filtered content first with disclosure.
    Always links to original source URL.
    No engagement mechanics (likes, saves, shares).
    """
    cached = _story_cache.get(story_id)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        response.headers["Cache-Control"] = "public, max-age=3600"
        return cached

    response.headers["X-Cache"] = "MISS"
    response.headers["Cache-Control"] = "public, max-age=3600"

    neutralized, story_raw, source = _get_story_or_404(db, story_id)

    result = StoryDetail(
        id=str(neutralized.id),
        feed_title=neutralized.feed_title,
        feed_summary=neutralized.feed_summary,
        detail_title=neutralized.detail_title,
        detail_brief=neutralized.detail_brief,
        detail_full=neutralized.detail_full,
        disclosure=neutralized.disclosure if neutralized.has_manipulative_content else "",
        has_manipulative_content=neutralized.has_manipulative_content,
        source_name=source.name,
        source_url=story_raw.original_url,
        published_at=story_raw.published_at,
        section=story_raw.feed_category or story_raw.section or "world",
    )

    _story_cache[story_id] = result
    return result


@router.get("/{story_id}/transparency", response_model=StoryTransparency)
def get_story_transparency(
    story_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> StoryTransparency:
    """
    Get transparency view for a story.

    Shows what manipulative content was removed/changed and why.
    Includes original content for comparison.
    Always links to original source.
    """
    cached = _transparency_cache.get(story_id)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        response.headers["Cache-Control"] = "public, max-age=3600"
        return cached

    response.headers["X-Cache"] = "MISS"
    response.headers["Cache-Control"] = "public, max-age=3600"

    neutralized, story_raw, source = _get_story_or_404(db, story_id)

    # Get spans
    spans = (
        db.query(models.TransparencySpan)
        .filter(models.TransparencySpan.story_neutralized_id == neutralized.id)
        .order_by(models.TransparencySpan.field, models.TransparencySpan.start_char)
        .all()
    )

    span_responses = [
        TransparencySpanResponse(
            field=span.field,
            start_char=span.start_char,
            end_char=span.end_char,
            original_text=span.original_text,
            action=span.action,
            reason=span.reason,
            replacement_text=span.replacement_text,
        )
        for span in spans
    ]

    # Retrieve body from object storage
    original_body = _get_body_from_storage(story_raw)

    result = StoryTransparency(
        id=str(neutralized.id),
        original_title=story_raw.original_title,
        original_description=story_raw.original_description,
        original_body=original_body,
        original_body_available=story_raw.raw_content_available,
        original_body_expired=not story_raw.raw_content_available and story_raw.raw_content_expired_at is not None,
        feed_title=neutralized.feed_title,
        feed_summary=neutralized.feed_summary,
        detail_full=neutralized.detail_full,
        spans=span_responses,
        disclosure=neutralized.disclosure if neutralized.has_manipulative_content else "",
        has_manipulative_content=neutralized.has_manipulative_content,
        source_url=story_raw.original_url,
        model_name=neutralized.model_name,
        prompt_version=neutralized.prompt_version,
        processed_at=neutralized.created_at,
    )

    _transparency_cache[story_id] = result
    return result


def _check_readability(text: Optional[str]) -> tuple[bool, list[str]]:
    """
    Basic readability check for neutralized text.
    Returns (is_readable, list_of_issues).
    """
    if not text:
        return True, []

    issues = []

    # Check for garbled text indicators
    # 1. Unusual character sequences (non-English patterns)
    unusual_chars = len([c for c in text if ord(c) > 127 and c not in '""''—–…'])
    if unusual_chars > len(text) * 0.05:  # More than 5% unusual chars
        issues.append(f"High unusual character ratio: {unusual_chars}/{len(text)}")

    # 2. Repetitive patterns (LLM loop indicator)
    words = text.split()
    if len(words) > 10:
        # Check for 3+ consecutive repeated words
        for i in range(len(words) - 2):
            if words[i] == words[i + 1] == words[i + 2]:
                issues.append(f"Repetitive pattern detected: '{words[i]}' repeated 3+ times")
                break

    # 3. Missing sentence boundaries
    sentences = text.split('.')
    avg_sentence_len = len(text) / max(len(sentences), 1)
    if avg_sentence_len > 500:  # Very long sentences suggest missing punctuation
        issues.append(f"Long sentence avg: {avg_sentence_len:.0f} chars")

    # 4. Truncation indicator
    if text.endswith('...') or text.endswith('…') or text.endswith('['):
        issues.append("Text appears truncated")

    # 5. JSON/structured data leak
    if '{' in text and '}' in text and ':' in text:
        if text.count('{') > 2 or text.count('"') > 10:
            issues.append("Possible JSON/structured data in text")

    return len(issues) == 0, issues


@router.get("/{story_id}/debug", response_model=StoryDebug)
def get_story_debug(
    story_id: str,
    db: Session = Depends(get_db),
) -> StoryDebug:
    """
    Get debug info for a story to diagnose content display issues.

    Returns truncated content samples and diagnostic metadata to help
    identify problems with original_body, detail_full, detail_brief, and spans.
    """
    neutralized, story_raw, source = _get_story_or_404(db, story_id)

    # Get original body from storage
    original_body = _get_body_from_storage(story_raw)
    original_body_length = len(original_body) if original_body else 0
    original_body_sample = original_body[:500] if original_body else None

    # Get spans
    spans = (
        db.query(models.TransparencySpan)
        .filter(models.TransparencySpan.story_neutralized_id == neutralized.id)
        .order_by(models.TransparencySpan.field, models.TransparencySpan.start_char)
        .limit(3)
        .all()
    )

    span_responses = [
        TransparencySpanResponse(
            field=span.field,
            start_char=span.start_char,
            end_char=span.end_char,
            original_text=span.original_text,
            action=span.action,
            reason=span.reason,
            replacement_text=span.replacement_text,
        )
        for span in spans
    ]

    # Get total span count
    total_spans = (
        db.query(models.TransparencySpan)
        .filter(models.TransparencySpan.story_neutralized_id == neutralized.id)
        .count()
    )

    # Check readability of detail_full
    detail_full = neutralized.detail_full
    detail_full_length = len(detail_full) if detail_full else 0
    detail_full_sample = detail_full[:500] if detail_full else None
    is_readable, issues = _check_readability(detail_full)

    # Add span validity check
    if original_body and spans:
        for span in spans:
            if span.start_char >= original_body_length or span.end_char > original_body_length:
                issues.append(f"Span out of bounds: {span.start_char}-{span.end_char} (body len: {original_body_length})")
                break

    # Check detail_brief
    detail_brief = neutralized.detail_brief
    detail_brief_length = len(detail_brief) if detail_brief else 0
    detail_brief_sample = detail_brief[:500] if detail_brief else None

    return StoryDebug(
        story_id=str(neutralized.id),
        original_body=original_body_sample,
        original_body_length=original_body_length,
        original_body_available=story_raw.raw_content_available,
        detail_full=detail_full_sample,
        detail_full_length=detail_full_length,
        detail_brief=detail_brief_sample,
        detail_brief_length=detail_brief_length,
        span_count=total_spans,
        spans_sample=span_responses,
        model_used=neutralized.model_name,
        has_manipulative_content=neutralized.has_manipulative_content,
        detail_full_readable=is_readable,
        issues=issues,
    )


@router.get("/{story_id}/debug/spans", response_model=SpanDetectionDebug)
def get_story_debug_spans(
    story_id: str,
    db: Session = Depends(get_db),
) -> SpanDetectionDebug:
    """
    Debug span detection for a story.

    Runs the span detection pipeline fresh and returns full diagnostics:
    - Raw LLM response
    - All phrases the LLM returned
    - What was filtered at each pipeline stage
    - Final spans

    This endpoint re-runs detection on the original body, so it may return
    different results than stored spans if the prompt or model has changed.
    """
    import os
    from app.services.neutralizer import detect_spans_debug_openai

    neutralized, story_raw, source = _get_story_or_404(db, story_id)

    # Get original body from storage
    original_body = _get_body_from_storage(story_raw)
    if not original_body:
        return SpanDetectionDebug(
            story_id=str(neutralized.id),
            original_body_preview=None,
            original_body_length=0,
            llm_raw_response=None,
            llm_phrases_count=0,
            llm_phrases=[],
            pipeline_trace=PipelineTrace(),
            final_span_count=0,
            final_spans=[],
            model_used=None,
        )

    # Get OpenAI API key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return SpanDetectionDebug(
            story_id=str(neutralized.id),
            original_body_preview=original_body[:500] if original_body else None,
            original_body_length=len(original_body),
            llm_raw_response=None,
            llm_phrases_count=0,
            llm_phrases=[],
            pipeline_trace=PipelineTrace(),
            final_span_count=0,
            final_spans=[],
            model_used=None,
        )

    # Run debug detection
    # IMPORTANT: Use same model as production to avoid confusing discrepancies
    # Production uses SPAN_DETECTION_MODEL for span detection (defaults to gpt-4o)
    model = os.environ.get("SPAN_DETECTION_MODEL", "gpt-4o")
    debug_result = detect_spans_debug_openai(original_body, api_key, model)

    # Convert to response schema
    llm_phrases_items = [
        LLMPhraseItem(
            phrase=p.get("phrase", ""),
            reason=p.get("reason"),
            action=p.get("action"),
            replacement=p.get("replacement"),
        )
        for p in debug_result.llm_phrases
    ]

    pipeline_trace = PipelineTrace(
        after_position_matching=len(debug_result.spans_after_position),
        after_quote_filter=len(debug_result.spans_after_quotes),
        after_false_positive_filter=len(debug_result.spans_final),
        phrases_filtered_by_quotes=debug_result.filtered_by_quotes,
        phrases_filtered_as_false_positives=debug_result.filtered_as_false_positives,
        phrases_not_found_in_text=debug_result.not_found_in_text,
    )

    final_spans = [
        TransparencySpanResponse(
            field=span.field,
            start_char=span.start_char,
            end_char=span.end_char,
            original_text=span.original_text,
            action=span.action.value if hasattr(span.action, 'value') else str(span.action),
            reason=span.reason.value if hasattr(span.reason, 'value') else str(span.reason),
            replacement_text=span.replacement_text,
        )
        for span in debug_result.spans_final
    ]

    return SpanDetectionDebug(
        story_id=str(neutralized.id),
        original_body_preview=original_body[:500] if original_body else None,
        original_body_length=len(original_body),
        llm_raw_response=debug_result.llm_raw_response,
        llm_phrases_count=len(debug_result.llm_phrases),
        llm_phrases=llm_phrases_items,
        pipeline_trace=pipeline_trace,
        final_span_count=len(debug_result.spans_final),
        final_spans=final_spans,
        model_used=model,
    )
