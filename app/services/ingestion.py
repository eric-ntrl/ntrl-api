# app/services/ingestion.py
"""
RSS ingestion service.

Pipeline:
1. Fetch RSS feeds from configured sources
2. Normalize entries
3. Deduplicate against existing stories
4. Classify into sections
5. Store raw articles
6. Log pipeline steps
"""

import hashlib
import logging
import ssl
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen

import feedparser
from sqlalchemy.orm import Session

from app import models
from app.models import PipelineStage, PipelineStatus
from app.services.deduper import Deduper
from app.services.classifier import SectionClassifier

logger = logging.getLogger(__name__)

# SSL context for fetching feeds
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE


class IngestionService:
    """RSS ingestion and normalization service."""

    def __init__(self):
        self.deduper = Deduper()
        self.classifier = SectionClassifier()

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

    def _fetch_feed(self, rss_url: str, timeout: int = 30) -> feedparser.FeedParserDict:
        """Fetch and parse RSS feed."""
        headers = {
            'User-Agent': 'NTRL-Bot/1.0 (Neutral News Aggregator)',
            'Accept': 'application/rss+xml, application/xml, text/xml',
        }
        request = Request(rss_url, headers=headers)
        with urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
            content = response.read()
        return feedparser.parse(content)

    def _normalize_entry(
        self,
        entry: dict,
        source: models.Source,
    ) -> Dict[str, Any]:
        """Normalize a feed entry to standard format."""
        # Get URL
        url = entry.get('link') or entry.get('id') or ''

        # Get title
        title = entry.get('title', 'Untitled')

        # Get description/summary
        description = entry.get('summary') or entry.get('description') or ''
        # Strip HTML if present
        if '<' in description:
            import re
            description = re.sub(r'<[^>]+>', '', description)

        # Get body (if available)
        body = None
        if 'content' in entry and entry['content']:
            body = entry['content'][0].get('value', '')
            if '<' in body:
                import re
                body = re.sub(r'<[^>]+>', '', body)

        # Get author
        author = entry.get('author') or entry.get('dc_creator')

        # Get published date
        published = None
        if 'published_parsed' in entry and entry['published_parsed']:
            try:
                published = datetime(*entry['published_parsed'][:6])
            except (TypeError, ValueError):
                pass
        if not published and 'updated_parsed' in entry and entry['updated_parsed']:
            try:
                published = datetime(*entry['updated_parsed'][:6])
            except (TypeError, ValueError):
                pass
        if not published:
            published = datetime.utcnow()

        return {
            'url': url,
            'title': title,
            'description': description,
            'body': body,
            'author': author,
            'published_at': published,
            'source_slug': source.slug,
            'raw_entry': dict(entry),
        }

    def ingest_source(
        self,
        db: Session,
        source: models.Source,
        max_items: int = 20,
    ) -> Dict[str, Any]:
        """
        Ingest stories from a single source.

        Returns:
            Dict with ingested count, skipped count, errors
        """
        started_at = datetime.utcnow()
        result = {
            'source_slug': source.slug,
            'source_name': source.name,
            'ingested': 0,
            'skipped_duplicate': 0,
            'errors': [],
        }

        try:
            # Fetch feed
            feed = self._fetch_feed(source.rss_url)
            entries = feed.entries[:max_items]

            for entry in entries:
                try:
                    # Normalize
                    normalized = self._normalize_entry(entry, source)

                    if not normalized['url']:
                        continue

                    # Check for duplicates
                    is_dup, original = self.deduper.is_duplicate(
                        db,
                        url=normalized['url'],
                        title=normalized['title'],
                    )

                    if is_dup:
                        result['skipped_duplicate'] += 1
                        continue

                    # Classify section
                    section = self.classifier.classify(
                        title=normalized['title'],
                        description=normalized['description'],
                        body=normalized['body'],
                        source_slug=source.slug,
                    )

                    # Create story
                    story = models.StoryRaw(
                        id=uuid.uuid4(),
                        source_id=source.id,
                        original_url=normalized['url'],
                        original_title=normalized['title'],
                        original_description=normalized['description'],
                        original_body=normalized['body'],
                        original_author=normalized['author'],
                        url_hash=self.deduper.hash_url(normalized['url']),
                        title_hash=self.deduper.hash_title(normalized['title']),
                        published_at=normalized['published_at'],
                        ingested_at=datetime.utcnow(),
                        section=section.value,
                        is_duplicate=False,
                        raw_payload=normalized['raw_entry'],
                    )
                    db.add(story)
                    result['ingested'] += 1

                    # Log successful ingest
                    self._log_pipeline(
                        db,
                        stage=PipelineStage.INGEST,
                        status=PipelineStatus.COMPLETED,
                        story_raw_id=story.id,
                        started_at=started_at,
                        metadata={'source': source.slug, 'url': normalized['url']},
                    )

                except Exception as e:
                    logger.error(f"Error processing entry from {source.slug}: {e}")
                    result['errors'].append(str(e))

            db.commit()

        except Exception as e:
            logger.error(f"Error fetching feed from {source.slug}: {e}")
            result['errors'].append(f"Feed fetch failed: {e}")
            self._log_pipeline(
                db,
                stage=PipelineStage.INGEST,
                status=PipelineStatus.FAILED,
                started_at=started_at,
                error_message=str(e),
                metadata={'source': source.slug},
            )

        return result

    def ingest_all(
        self,
        db: Session,
        source_slugs: Optional[List[str]] = None,
        max_items_per_source: int = 20,
    ) -> Dict[str, Any]:
        """
        Ingest stories from all active sources (or specified sources).

        Returns:
            Dict with overall results and per-source breakdown
        """
        started_at = datetime.utcnow()

        # Get sources
        query = db.query(models.Source).filter(models.Source.is_active == True)
        if source_slugs:
            query = query.filter(models.Source.slug.in_(source_slugs))
        sources = query.all()

        result = {
            'status': 'completed',
            'started_at': started_at,
            'finished_at': None,
            'duration_ms': 0,
            'sources_processed': 0,
            'total_ingested': 0,
            'total_skipped_duplicate': 0,
            'source_results': [],
            'errors': [],
        }

        for source in sources:
            source_result = self.ingest_source(db, source, max_items=max_items_per_source)
            result['source_results'].append(source_result)
            result['sources_processed'] += 1
            result['total_ingested'] += source_result['ingested']
            result['total_skipped_duplicate'] += source_result['skipped_duplicate']
            if source_result['errors']:
                result['errors'].extend(source_result['errors'])

        finished_at = datetime.utcnow()
        result['finished_at'] = finished_at
        result['duration_ms'] = int((finished_at - started_at).total_seconds() * 1000)

        if result['errors'] and result['total_ingested'] == 0:
            result['status'] = 'failed'
        elif result['errors']:
            result['status'] = 'partial'

        return result
