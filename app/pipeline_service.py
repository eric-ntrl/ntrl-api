# app/pipeline_service.py

from __future__ import annotations

import html
import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app import models
from app.llm import get_llm_provider, LLMProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source handling
# ---------------------------------------------------------------------------

def get_or_create_source(
    db: Session,
    *,
    name: str,
    domain: str,
    api_identifier: Optional[str] = None,
) -> models.Source:
    """
    Find a Source by domain, or create it if it doesn't exist.
    """
    source = (
        db.query(models.Source)
        .filter(models.Source.domain == domain)
        .one_or_none()
    )
    if source:
        return source

    source = models.Source(
        id=uuid.uuid4(),
        name=name,
        domain=domain,
        api_identifier=api_identifier,
    )
    db.add(source)
    db.flush()  # populate id
    return source


# ---------------------------------------------------------------------------
# LLM Provider singleton (lazy initialization)
# ---------------------------------------------------------------------------

_llm_provider: Optional[LLMProvider] = None


def get_provider() -> LLMProvider:
    """Get or create the LLM provider instance."""
    global _llm_provider
    if _llm_provider is None:
        _llm_provider = get_llm_provider()
    return _llm_provider


def set_provider(provider: LLMProvider) -> None:
    """Set a custom LLM provider (useful for testing)."""
    global _llm_provider
    _llm_provider = provider


# ---------------------------------------------------------------------------
# Summary + Neutrality analysis (LLM-powered)
# ---------------------------------------------------------------------------

def generate_neutral_summary(
    title: str,
    description: Optional[str],
    body: Optional[str],
) -> Dict[str, str]:
    """
    Generate a neutral summary using the configured LLM provider.
    """
    provider = get_provider()
    result = provider.generate_neutral_summary(title, description, body)

    return {
        "neutral_title": result.neutral_title,
        "neutral_summary_short": result.neutral_summary_short,
        "neutral_summary_extended": result.neutral_summary_extended or "",
    }


def _safe_json(raw_payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Ensure payload is JSON-serializable.
    Stringifies non-serializable types (HttpUrl, datetime, UUID, etc).
    """
    if raw_payload is None:
        return None
    # json.dumps(..., default=str) converts unknown objects to strings
    return json.loads(json.dumps(raw_payload, default=str))


def analyze_neutrality(
    title: str,
    description: Optional[str],
    body: Optional[str],
) -> Dict[str, Any]:
    """
    Analyze content for bias using the configured LLM provider.
    """
    provider = get_provider()
    result = provider.analyze_neutrality(title, description, body)

    # Choose the exact field for redlining (body > description > title)
    if body:
        span_text, field = body, "original_body"
    elif description:
        span_text, field = description, "original_description"
    else:
        span_text, field = title or "", "original_title"

    # Convert BiasSpan objects to dicts
    bias_spans = [span.to_dict() for span in result.bias_spans]

    return {
        "neutrality_score": result.neutrality_score,
        "bias_terms": result.bias_terms,
        "bias_spans": bias_spans,
        "reading_level": result.reading_level,
        "political_lean": result.political_lean,
        "redline": {
            "field": field,
            "text": span_text,
            "html": build_redline_html(span_text, bias_spans),
        },
    }


def build_redline_html(text: str, spans: List[Dict[str, Any]]) -> str:
    """
    Convert `text` + `bias_spans` into minimal HTML with highlights.

    - text is HTML-escaped
    - biased ranges wrapped in <mark data-label=... data-severity=...>

    This is framework-agnostic markup you can style later.
    """
    if not text:
        return ""

    if not spans:
        return html.escape(text)

    spans_sorted = sorted(spans, key=lambda s: int(s.get("start", 0)))
    n = len(text)
    out: List[str] = []
    cursor = 0

    for s in spans_sorted:
        start = int(s.get("start", 0))
        end = int(s.get("end", 0))
        label = str(s.get("label", "non_neutral"))
        severity = float(s.get("severity", 0.60))

        # Clamp
        start = max(0, min(n, start))
        end = max(0, min(n, end))
        if end <= start:
            continue
        if start < cursor:
            # overlap / out-of-order; ignore
            continue

        out.append(html.escape(text[cursor:start]))
        chunk = html.escape(text[start:end])
        out.append(
            f'<mark data-label="{html.escape(label)}" '
            f'data-severity="{severity:.2f}">{chunk}</mark>'
        )
        cursor = end

    out.append(html.escape(text[cursor:]))
    return "".join(out)


# ---------------------------------------------------------------------------
# Core pipeline function
# ---------------------------------------------------------------------------

def run_neutral_pipeline(
    db: Session,
    *,
    source_name: str,
    source_url: str,
    published_at: datetime,
    title: str,
    description: Optional[str],
    body: Optional[str],
    raw_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    End-to-end pipeline for a single article.

    Stages:
      1) INGEST raw article into articles_raw
      2) GENERATE_NEUTRAL_SUMMARY (LLM-powered)
      3) ANALYZE_NEUTRALITY (LLM-powered)
      4) SAVE_RESULTS into article_summaries (including bias_spans)
      5) Record PipelineRun
    """
    started_at = datetime.utcnow()

    # Get provider info for metadata
    provider = get_provider()
    model_name = f"{provider.name}/{provider.model_name}"

    # 1) Resolve domain from URL
    parsed = urlparse(source_url)
    domain = parsed.netloc or (source_name.lower().replace(" ", "") + ".unknown")

    # 2) Get or create Source
    source = get_or_create_source(
        db,
        name=source_name,
        domain=domain,
        api_identifier=None,
    )

    # 3) Normalize raw_payload so it is JSON-serializable
    safe_raw_payload = _safe_json(raw_payload)

    # 4) Create ArticleRaw
    article_raw = models.ArticleRaw(
        id=uuid.uuid4(),
        source_id=source.id,
        external_id=None,
        original_title=title,
        original_description=description,
        original_body=body,
        source_url=source_url,
        language="en",
        published_at=published_at,
        ingested_at=datetime.utcnow(),
        raw_payload=safe_raw_payload,
    )
    db.add(article_raw)
    db.flush()  # ensure article_raw.id exists

    # 5) Generate neutral summary (LLM-powered)
    logger.info(f"Generating neutral summary for article: {title[:50]}...")
    summary_data = generate_neutral_summary(title, description, body)

    # 6) Analyze neutrality + build bias spans (LLM-powered)
    logger.info(f"Analyzing neutrality for article: {title[:50]}...")
    neutrality_data = analyze_neutrality(title, description, body)

    # Hard guarantee: never store NULL for bias_spans
    bias_spans_value: List[Dict[str, Any]] = neutrality_data.get("bias_spans") or []

    # 7) Create ArticleSummary row
    article_summary = models.ArticleSummary(
        id=uuid.uuid4(),
        article_raw_id=article_raw.id,
        version_tag="v1",
        model_name=model_name,
        prompt_version="v1-summary+score",
        generated_at=datetime.utcnow(),
        neutral_title=summary_data["neutral_title"],
        neutral_summary_short=summary_data["neutral_summary_short"],
        neutral_summary_extended=summary_data["neutral_summary_extended"],
        tone_flag=False,
        tone_issues=None,
        misinfo_flag=False,
        misinfo_notes=None,
        is_current=True,
        neutrality_score=neutrality_data["neutrality_score"],
        bias_terms=neutrality_data["bias_terms"],
        bias_spans=bias_spans_value,
        reading_level=neutrality_data["reading_level"],
        political_lean=neutrality_data["political_lean"],
    )
    db.add(article_summary)

    # Mark other summaries for same article as not current (safety)
    (
        db.query(models.ArticleSummary)
        .filter(
            models.ArticleSummary.article_raw_id == article_raw.id,
            models.ArticleSummary.id != article_summary.id,
        )
        .update({"is_current": False})
    )

    # 8) Record PipelineRun
    pipeline_run = models.PipelineRun(
        id=uuid.uuid4(),
        article_raw_id=article_raw.id,
        stage="FULL_PIPELINE",
        status="COMPLETED",
        model_name=model_name,
        prompt_version="v1-summary+score",
        started_at=started_at,
        finished_at=datetime.utcnow(),
        error_message=None,
        extra_metadata={
            "stages": [
                "INGEST",
                "GENERATE_NEUTRAL_SUMMARY",
                "ANALYZE_NEUTRALITY",
                "SAVE_RESULTS",
            ],
            "llm_provider": provider.name,
            "bias_term_count": len(neutrality_data.get("bias_terms") or []),
            "bias_span_count": len(bias_spans_value),
            "redline_field": (neutrality_data.get("redline") or {}).get("field"),
        },
    )
    db.add(pipeline_run)

    db.commit()
    db.refresh(article_raw)
    db.refresh(article_summary)
    db.refresh(pipeline_run)

    return {
        "pipeline_run_id": str(pipeline_run.id),
        "article_raw_id": str(article_raw.id),
        "article_summary_id": str(article_summary.id),
        "neutral_title": article_summary.neutral_title,
        "neutral_summary_short": article_summary.neutral_summary_short,
        "neutral_summary_extended": article_summary.neutral_summary_extended,
        "neutrality_score": article_summary.neutrality_score,
        "bias_terms": article_summary.bias_terms,
        "bias_spans": article_summary.bias_spans,
        "reading_level": article_summary.reading_level,
        "political_lean": article_summary.political_lean,
        "redline": neutrality_data.get("redline"),
    }
