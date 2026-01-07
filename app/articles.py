# app/articles.py

from __future__ import annotations

import html
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app import models

router = APIRouter(prefix="/articles", tags=["articles"])


# ---------- DB dependency ----------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- Redline helper ----------

def build_redlined_html(text: str, spans: Optional[List[Dict[str, Any]]]) -> str:
    """
    Returns HTML with bias spans wrapped in:
      <span class="ntrl-bias" data-label="..." data-severity="...">...</span>

    NOTE: We HTML-escape all text to avoid injection issues.
    """
    if not text:
        return ""

    if not spans:
        return html.escape(text)

    # sanitize spans
    clean = []
    n = len(text)
    for s in spans:
        try:
            start = int(s.get("start"))
            end = int(s.get("end"))
        except Exception:
            continue
        if start < 0 or end <= start or end > n:
            continue
        clean.append(
            {
                "start": start,
                "end": end,
                "label": str(s.get("label") or "non_neutral"),
                "severity": float(s.get("severity") or 0.6),
            }
        )

    if not clean:
        return html.escape(text)

    # sort and drop overlaps (keep earliest)
    clean.sort(key=lambda x: (x["start"], -(x["end"] - x["start"])))
    non_overlapping = []
    cursor = -1
    for s in clean:
        if s["start"] < cursor:
            continue
        non_overlapping.append(s)
        cursor = s["end"]

    out = []
    last = 0
    for s in non_overlapping:
        out.append(html.escape(text[last : s["start"]]))
        chunk = html.escape(text[s["start"] : s["end"]])
        out.append(
            f'<span class="ntrl-bias" data-label="{html.escape(s["label"])}" '
            f'data-severity="{s["severity"]}">{chunk}</span>'
        )
        last = s["end"]

    out.append(html.escape(text[last:]))
    return "".join(out)


@router.get("/{article_raw_id}")
def get_article_detail(article_raw_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    # Validate UUID
    try:
        article_uuid = uuid.UUID(article_raw_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid article_raw_id (must be UUID).")

    # Load article
    article = (
        db.query(models.ArticleRaw)
        .filter(models.ArticleRaw.id == article_uuid)
        .one_or_none()
    )
    if not article:
        raise HTTPException(status_code=404, detail="Article not found.")

    # Load "current" summary (fallback: latest)
    summary = (
        db.query(models.ArticleSummary)
        .filter(models.ArticleSummary.article_raw_id == article.id)
        .order_by(models.ArticleSummary.is_current.desc(), models.ArticleSummary.generated_at.desc())
        .first()
    )

    # Choose what to redline (body > description > title)
    redline_field = "original_body"
    redline_text = article.original_body or ""
    if not redline_text:
        redline_field = "original_description"
        redline_text = article.original_description or ""
    if not redline_text:
        redline_field = "original_title"
        redline_text = article.original_title or ""

    bias_spans = (summary.bias_spans if summary else None)  # may be None
    redlined_html = build_redlined_html(redline_text, bias_spans)

    # Source fields (relationship should work, but keep it safe)
    source_name = None
    source_domain = None
    try:
        if article.source:
            source_name = article.source.name
            source_domain = article.source.domain
    except Exception:
        pass

    return {
        "article_raw_id": str(article.id),
        "source_name": source_name,
        "source_domain": source_domain,
        "source_url": article.source_url,
        "published_at": article.published_at.isoformat() if article.published_at else None,

        "original_title": article.original_title,
        "original_description": article.original_description,
        "original_body": article.original_body,

        "summary": None if not summary else {
            "article_summary_id": str(summary.id),
            "version_tag": summary.version_tag,
            "model_name": summary.model_name,
            "prompt_version": summary.prompt_version,
            "generated_at": summary.generated_at.isoformat() if summary.generated_at else None,

            "neutral_title": summary.neutral_title,
            "neutral_summary_short": summary.neutral_summary_short,
            "neutral_summary_extended": summary.neutral_summary_extended,

            "neutrality_score": summary.neutrality_score,
            "bias_terms": summary.bias_terms,
            "bias_spans": summary.bias_spans,
            "reading_level": summary.reading_level,
            "political_lean": summary.political_lean,
            "is_current": summary.is_current,
        },

        "redline": {
            "field": redline_field,
            "text": redline_text,
            "html": redlined_html,
        },
    }
