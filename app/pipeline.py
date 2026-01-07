# app/pipeline.py

from datetime import datetime
from typing import Dict, Any

import feedparser
from sqlalchemy.orm import Session

from .database import SessionLocal
from . import models


# --- Config ------------------------------------------------------------------

# You can change these later – this is just a simple “hello world” ingestion.
DEFAULT_SOURCES = [
    {
        "name": "AP News – Top Stories",
        "homepage_url": "https://apnews.com",
        "rss_url": "https://rss.apnews.com/apf-topnews",
    }
]

MAX_ARTICLES_PER_SOURCE = 5  # keep this small while developing


# --- Helpers -----------------------------------------------------------------


def _get_or_create_source(
    db: Session, name: str, homepage_url: str, rss_url: str
) -> models.Source:
    """Find a Source row by rss_url or create it."""
    src = (
        db.query(models.Source)
        .filter(models.Source.rss_url == rss_url)
        .one_or_none()
    )
    if src:
        return src

    src = models.Source(
        name=name,
        homepage_url=homepage_url,
        rss_url=rss_url,
        is_active=True,
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _upsert_article_from_entry(
    db: Session, source: models.Source, entry
) -> tuple[models.ArticleRaw | None, bool]:
    """
    Insert an ArticleRaw from an RSS entry if we don't already have it.
    Returns (article, created_flag).
    """
    url = entry.get("link") or entry.get("id")
    if not url:
        return None, False

    existing = (
        db.query(models.ArticleRaw)
        .filter(models.ArticleRaw.url == url)
        .one_or_none()
    )
    if existing:
        return existing, False

    title = entry.get("title", "Untitled")
    # RSS description/summary is usually good enough for a stub.
    content = entry.get("summary") or entry.get("description") or ""

    published_at = None
    if getattr(entry, "published_parsed", None):
        import time

        published_at = datetime.fromtimestamp(
            time.mktime(entry.published_parsed)
        )

    article = models.ArticleRaw(
        source_id=source.id,
        external_id=entry.get("id"),
        url=url,
        title=title,
        content=content,
        published_at=published_at,
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    return article, True


def _generate_stub_summaries(article: models.ArticleRaw) -> tuple[str, str]:
    """
    Temporary stand-in for a real LLM call.

    short: <= ~240 chars
    long:  full description/content
    """
    base_text = (article.content or article.title or "").strip()
    if not base_text:
        return (
            "No content available yet – stub summary.",
            "No content available yet – stub summary.",
        )

    short = base_text.replace("\n", " ")
    if len(short) > 240:
        short = short[:237] + "..."

    long = base_text
    return short, long


# --- Public API --------------------------------------------------------------


def run_pipeline() -> Dict[str, Any]:
    """
    End-to-end ingestion + stub summarization.

    - Creates a PipelineRun row
    - Pulls a few RSS articles
    - Inserts into sources + articles_raw
    - Creates stub summaries in article_summaries
    - Marks the run as completed or failed
    """
    db = SessionLocal()

    stats: Dict[str, int] = {
        "sources_processed": 0,
        "articles_inserted": 0,
        "articles_skipped_existing": 0,
        "summaries_created": 0,
    }

    run = models.PipelineRun(
        status="running",
        started_at=datetime.utcnow(),
        message="Pipeline started.",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        for src_cfg in DEFAULT_SOURCES:
            source = _get_or_create_source(
                db,
                name=src_cfg["name"],
                homepage_url=src_cfg["homepage_url"],
                rss_url=src_cfg["rss_url"],
            )

            feed = feedparser.parse(src_cfg["rss_url"])
            stats["sources_processed"] += 1

            for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:
                article, created = _upsert_article_from_entry(db, source, entry)
                if not article:
                    continue

                if created:
                    stats["articles_inserted"] += 1
                else:
                    stats["articles_skipped_existing"] += 1

                # Only create a summary if one doesn't already exist
                existing_summary = (
                    db.query(models.ArticleSummary)
                    .filter(models.ArticleSummary.article_id == article.id)
                    .one_or_none()
                )
                if existing_summary:
                    continue

                short, long_ = _generate_stub_summaries(article)
                summary = models.ArticleSummary(
                    article_id=article.id,
                    summary_short=short,
                    summary_long=long_,
                    model="stub",
                    prompt_version="v0",
                )
                db.add(summary)
                stats["summaries_created"] += 1

        run.status = "completed"
        run.finished_at = datetime.utcnow()
        run.message = (
            f"Processed {stats['sources_processed']} sources; "
            f"{stats['articles_inserted']} new articles; "
            f"{stats['summaries_created']} summaries."
        )
        db.add(run)
        db.commit()

    except Exception as exc:
        db.rollback()
        run.status = "failed"
        run.finished_at = datetime.utcnow()
        run.message = f"Pipeline failed: {exc}"
        db.add(run)
        db.commit()
        raise

    finally:
        db.close()

    return {
        "status": run.status,
        "run_id": str(run.id),
        **stats,
        "message": run.message,
    }
