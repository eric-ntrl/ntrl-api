# app/cli/backfill_truncation.py
"""
Backfill body_is_truncated flag on existing Perigon articles.

Scans stories_raw for Perigon-sourced articles, downloads the body from S3,
checks for truncation markers, and sets body_is_truncated = True where found.

Usage:
    pipenv run python -m app.cli.backfill_truncation            # execute
    pipenv run python -m app.cli.backfill_truncation --dry-run   # preview only
"""

import argparse
import sys

import os
from dotenv import load_dotenv
load_dotenv()


def get_db_session():
    """Get a database session."""
    from app.database import SessionLocal
    return SessionLocal()


def _download_body(uri: str) -> str | None:
    """Download body content from S3 URI."""
    from app.services.storage import download_content
    try:
        return download_content(uri)
    except Exception as e:
        print(f"    Failed to download {uri}: {e}")
        return None


def run(dry_run: bool = False):
    """Scan Perigon articles and flag truncated bodies."""
    from app import models
    from app.utils.content_sanitizer import has_truncation_markers

    db = get_db_session()
    try:
        # Query all Perigon articles that haven't been flagged yet
        query = (
            db.query(models.StoryRaw)
            .filter(models.StoryRaw.source_type == "perigon")
            .filter(models.StoryRaw.body_is_truncated == False)  # noqa: E712
            .filter(models.StoryRaw.raw_content_available == True)  # noqa: E712
        )

        articles = query.all()
        print(f"Found {len(articles)} Perigon articles to check")

        flagged = 0
        errors = 0

        for i, article in enumerate(articles):
            if not article.raw_content_uri:
                continue

            body = _download_body(article.raw_content_uri)
            if body is None:
                errors += 1
                continue

            if has_truncation_markers(body):
                flagged += 1
                title_preview = (article.original_title or "")[:60]
                print(f"  [{flagged}] TRUNCATED: {title_preview}")

                if not dry_run:
                    article.body_is_truncated = True

            if (i + 1) % 50 == 0:
                print(f"  ... checked {i + 1}/{len(articles)}")

        if not dry_run:
            db.commit()
            print(f"\nDone: {flagged} articles flagged as truncated ({errors} download errors)")
        else:
            print(f"\nDry run: {flagged} articles would be flagged ({errors} download errors)")

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Backfill body_is_truncated flag")
    parser.add_argument("--dry-run", action="store_true", help="Preview without updating")
    args = parser.parse_args()

    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
