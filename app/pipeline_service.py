# app/pipeline_service.py

from __future__ import annotations

import html
import json
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app import models


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
# Option B stubs: Summary + Neutrality analysis
# ---------------------------------------------------------------------------

def generate_neutral_summary_stub(
    title: str,
    description: Optional[str],
    body: Optional[str],
) -> Dict[str, str]:
    """
    STUB for neutral summary generation.
    Replace later with an LLM call.
    """
    base_text = body or description or title or "No article text provided."

    short = base_text.strip()
    if len(short) > 280:
        short = short[:277] + "..."

    extended = base_text.strip()
    if len(extended) > 1000:
        extended = extended[:997] + "..."

    neutral_title = title or "Neutral summary of article"

    return {
        "neutral_title": neutral_title,
        "neutral_summary_short": short,
        "neutral_summary_extended": extended,
    }


# Opinionated keyword list for stub (expand later).
_BIAS_KEYWORDS: List[str] = [
    "shocking",
    "you won't believe",
    "explosive",
    "furious",
    "slams",
    "destroyed",
    "goes viral",
    "must see",
]

# Stub severities for UI weighting (0.0–1.0)
_SEVERITY_MAP: Dict[str, float] = {
    "shocking": 0.70,
    "you won't believe": 0.75,
    "explosive": 0.65,
    "furious": 0.60,
    "slams": 0.55,
    "destroyed": 0.55,
    "goes viral": 0.60,
    "must see": 0.60,
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


def _find_bias_spans(text: str, terms: List[str], *, field: str) -> List[Dict[str, Any]]:
    """
    Find case-insensitive spans for each term in `text`.
    Offsets are relative to the exact `text` string scanned.
    Returns a de-overlapped list sorted by start index.
    """
    if not text or not terms:
        return []

    matches: List[Dict[str, Any]] = []
    for term in terms:
        t = (term or "").strip()
        if not t:
            continue

        pat = re.compile(re.escape(t), re.IGNORECASE)
        for m in pat.finditer(text):
            term_lc = t.lower()
            matches.append(
                {
                    "start": int(m.start()),
                    "end": int(m.end()),
                    "text": text[m.start() : m.end()],
                    "label": "non_neutral",
                    "severity": float(_SEVERITY_MAP.get(term_lc, 0.60)),
                    "term": t,
                    "field": field,
                }
            )

    if not matches:
        return []

    # Sort by start asc; for same start, prefer longer match
    matches.sort(key=lambda x: (x["start"], -(x["end"] - x["start"])))

    # Drop overlaps: keep earliest; if overlap, skip the later one
    spans: List[Dict[str, Any]] = []
    occupied_until = -1
    for m in matches:
        if m["start"] < occupied_until:
            continue
        spans.append(m)
        occupied_until = m["end"]

    return spans


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


def analyze_neutrality_stub(
    title: str,
    description: Optional[str],
    body: Optional[str],
    summary: Dict[str, str],
) -> Dict[str, Any]:
    """
    STUB for neutrality analysis.
    Replace later with an LLM call that returns:
      - neutrality_score (0–100),
      - bias_terms,
      - bias_spans,
      - reading_level,
      - political_lean
    """
    combined = " ".join([p for p in [title, description, body] if p])
    combined_lower = combined.lower()

    found_terms: List[str] = [kw for kw in _BIAS_KEYWORDS if kw in combined_lower]

    neutrality_score = max(0, 100 - 10 * len(found_terms))

    word_count = len(combined.split()) if combined else 0
    reading_level = max(1, min(18, word_count // 25 or 1))

    political_lean = 0.0  # placeholder for [-1.0, 1.0] later

    # Choose the exact field you'll "redline" first (body > description > title)
    if body:
        span_text, field = body, "original_body"
    elif description:
        span_text, field = description, "original_description"
    else:
        span_text, field = title or "", "original_title"

    bias_spans = _find_bias_spans(span_text, found_terms, field=field)

    return {
        "neutrality_score": int(neutrality_score),
        "bias_terms": found_terms,
        # IMPORTANT: return [] (not None) when no spans found
        "bias_spans": bias_spans or [],
        "reading_level": int(reading_level),
        "political_lean": float(political_lean),
        # Optional helper payload for UI debugging later
        "redline": {
            "field": field,
            "text": span_text,
            "html": build_redline_html(span_text, bias_spans or []),
        },
    }


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

    Stages (Option B):
      1) INGEST raw article into articles_raw
      2) GENERATE_NEUTRAL_SUMMARY  (stubbed)
      3) ANALYZE_NEUTRALITY        (stubbed)
      4) SAVE_RESULTS into article_summaries (including bias_spans)
      5) Record PipelineRun
    """
    started_at = datetime.utcnow()

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

    # 5) Generate neutral summary (stub)
    summary_data = generate_neutral_summary_stub(title, description, body)

    # 6) Analyze neutrality + build bias spans (stub)
    neutrality_data = analyze_neutrality_stub(title, description, body, summary_data)

    # Hard guarantee: never store NULL for bias_spans
    bias_spans_value: List[Dict[str, Any]] = neutrality_data.get("bias_spans") or []

    # 7) Create ArticleSummary row
    article_summary = models.ArticleSummary(
        id=uuid.uuid4(),
        article_raw_id=article_raw.id,
        version_tag="v1",
        model_name="stub-model",
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
        bias_spans=bias_spans_value,  # <-- will be [] not NULL
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
        model_name="stub-model",
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
        # helpful for debugging UI quickly (optional)
        "redline": neutrality_data.get("redline"),
    }
