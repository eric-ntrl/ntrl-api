# app/services/ingestion.py
"""
RSS ingestion service.

Pipeline:
1. Fetch RSS feeds from configured sources
2. Normalize entries
3. Deduplicate against existing stories
4. Classify into sections
5. Store raw content in S3
6. Store metadata in Postgres
7. Log pipeline steps
"""

import hashlib
import logging
import os
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
from app.services.body_extractor import BodyExtractor, ExtractionResult
from app.storage.factory import get_storage_provider
from app.storage.base import ContentType

logger = logging.getLogger(__name__)

# SSL context for fetching feeds
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE


class IngestionService:
    """RSS ingestion and normalization service."""

    # Default retention period for raw content (days)
    DEFAULT_RETENTION_DAYS = int(os.getenv("RAW_CONTENT_RETENTION_DAYS", "30"))

    def __init__(self):
        self.deduper = Deduper()
        self.classifier = SectionClassifier()
        self.body_extractor = BodyExtractor()
        self._storage = None

    def _deduplicate_paragraphs(self, body: str) -> str:
        """Remove duplicate paragraphs from article body.

        News sites often repeat intro text in image captions, pull quotes,
        and sidebar summaries. This removes exact or near-duplicate paragraphs.

        Args:
            body: Raw article body text

        Returns:
            Body text with duplicate paragraphs removed
        """
        if not body:
            return body

        paragraphs = body.split('\n\n')
        seen: set[str] = set()
        unique: list[str] = []

        for para in paragraphs:
            # Normalize for comparison (lowercase, collapse whitespace)
            normalized = ' '.join(para.lower().split())

            # Skip if too short (likely a caption fragment) - keep as-is
            if len(normalized) < 50:
                unique.append(para)
                continue

            # Check for exact or near-duplicate
            if normalized not in seen:
                seen.add(normalized)
                unique.append(para)

        return '\n\n'.join(unique)

    @property
    def storage(self):
        """Lazy-load storage provider."""
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage

    def _upload_body_to_storage(
        self,
        story_id: str,
        body: str,
        published_at: datetime,
    ) -> Optional[Dict[str, Any]]:
        """
        Upload body content to object storage.

        Returns dict with storage metadata or None if no body.
        """
        if not body:
            return None

        body_bytes = body.encode("utf-8")
        key = self.storage.generate_key(
            story_id=story_id,
            field="body",
            timestamp=published_at,
        )

        try:
            metadata = self.storage.upload(
                key=key,
                content=body_bytes,
                content_type=ContentType.TEXT_PLAIN,
                expires_days=self.DEFAULT_RETENTION_DAYS,
                metadata={"story_id": story_id},
            )
            return {
                "uri": metadata.uri,
                "hash": metadata.content_hash,
                "type": metadata.content_type.value,
                "encoding": metadata.content_encoding.value,
                "size": metadata.original_size_bytes,
            }
        except Exception as e:
            logger.error(f"Failed to upload body to storage for {story_id}: {e}")
            return None

    def _log_pipeline(
        self,
        db: Session,
        stage: PipelineStage,
        status: PipelineStatus,
        story_raw_id: Optional[uuid.UUID] = None,
        started_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
        metadata: Optional[dict] = None,
        trace_id: Optional[str] = None,
        entry_url: Optional[str] = None,
        failure_reason: Optional[str] = None,
        retry_count: int = 0,
    ) -> models.PipelineLog:
        """Create a pipeline log entry with enhanced observability."""
        now = datetime.utcnow()
        duration_ms = None
        if started_at:
            duration_ms = int((now - started_at).total_seconds() * 1000)

        # Compute entry_url_hash for indexing
        entry_url_hash = None
        if entry_url:
            entry_url_hash = hashlib.sha256(entry_url.encode()).hexdigest()

        log = models.PipelineLog(
            id=uuid.uuid4(),
            stage=stage.value,
            status=status.value,
            story_raw_id=story_raw_id,
            started_at=started_at or now,
            finished_at=now,
            duration_ms=duration_ms,
            error_message=error_message,
            log_metadata=metadata,
            trace_id=trace_id,
            entry_url=entry_url,
            entry_url_hash=entry_url_hash,
            failure_reason=failure_reason,
            retry_count=retry_count,
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

    def _extract_article_body(self, url: str) -> ExtractionResult:
        """
        Extract article body text using the hardened BodyExtractor.

        Uses retries with exponential backoff and newspaper3k fallback.
        Returns ExtractionResult with success status and failure details.
        """
        if not url:
            from app.services.body_extractor import ExtractionFailureReason
            return ExtractionResult(
                success=False,
                failure_reason=ExtractionFailureReason.DOWNLOAD_FAILED,
            )

        return self.body_extractor.extract(url)

    def _normalize_entry(
        self,
        entry: dict,
        source: models.Source,
    ) -> Dict[str, Any]:
        """Normalize a feed entry to standard format with extraction metrics."""
        import re

        # Get URL
        url = entry.get('link') or entry.get('id') or ''

        # Get title
        title = entry.get('title', 'Untitled')

        # Get description/summary
        description = entry.get('summary') or entry.get('description') or ''
        # Strip HTML if present
        if '<' in description:
            description = re.sub(r'<[^>]+>', '', description)

        # Get body - try RSS content field first
        rss_body = None
        if 'content' in entry and entry['content']:
            rss_body = entry['content'][0].get('value', '')
            if '<' in rss_body:
                rss_body = re.sub(r'<[^>]+>', '', rss_body)

        # Extract from article URL (RSS feeds usually only have short excerpts)
        extraction_result = self._extract_article_body(url) if url else None

        # Use extracted body if available and longer, otherwise fall back to RSS
        body = None
        body_downloaded = False
        extractor_used = None
        extraction_failure_reason = None
        extraction_duration_ms = 0

        if extraction_result:
            extraction_duration_ms = extraction_result.duration_ms
            if extraction_result.success and extraction_result.body:
                if len(extraction_result.body) > len(rss_body or ''):
                    body = extraction_result.body
                    body_downloaded = True
                    extractor_used = extraction_result.extractor_used
                else:
                    body = rss_body
            else:
                # Extraction failed - record reason
                extraction_failure_reason = (
                    extraction_result.failure_reason.value
                    if extraction_result.failure_reason else None
                )
                body = rss_body

        if not body:
            body = rss_body

        # Remove duplicate paragraphs (common in news sites with captions/pull quotes)
        if body:
            body = self._deduplicate_paragraphs(body)

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
            # Extraction metrics
            'body_downloaded': body_downloaded,
            'extractor_used': extractor_used,
            'extraction_failure_reason': extraction_failure_reason,
            'extraction_duration_ms': extraction_duration_ms,
        }

    def ingest_source(
        self,
        db: Session,
        source: models.Source,
        max_items: int = 20,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ingest stories from a single source with enhanced observability.

        Returns:
            Dict with ingested count, skipped count, body download stats, errors
        """
        started_at = datetime.utcnow()
        result = {
            'source_slug': source.slug,
            'source_name': source.name,
            'ingested': 0,
            'skipped_duplicate': 0,
            'body_downloaded': 0,
            'body_failed': 0,
            'errors': [],
        }

        try:
            # Fetch feed
            feed = self._fetch_feed(source.rss_url)
            entries = feed.entries[:max_items]

            for entry in entries:
                entry_started_at = datetime.utcnow()
                entry_url = entry.get('link') or entry.get('id') or ''

                try:
                    # Normalize (includes body extraction with retries)
                    normalized = self._normalize_entry(entry, source)

                    if not normalized['url']:
                        continue

                    # Track body extraction metrics
                    if normalized.get('body_downloaded'):
                        result['body_downloaded'] += 1
                    elif normalized.get('extraction_failure_reason'):
                        result['body_failed'] += 1

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
                    story_id = uuid.uuid4()

                    # Upload body to object storage
                    storage_meta = self._upload_body_to_storage(
                        story_id=str(story_id),
                        body=normalized['body'],
                        published_at=normalized['published_at'],
                    )

                    story = models.StoryRaw(
                        id=story_id,
                        source_id=source.id,
                        original_url=normalized['url'],
                        original_title=normalized['title'],
                        original_description=normalized['description'],
                        original_author=normalized['author'],
                        url_hash=self.deduper.hash_url(normalized['url']),
                        title_hash=self.deduper.hash_title(normalized['title']),
                        published_at=normalized['published_at'],
                        ingested_at=datetime.utcnow(),
                        section=section.value,
                        is_duplicate=False,
                        feed_entry_id=normalized['raw_entry'].get('id'),
                        # S3 storage references
                        raw_content_uri=storage_meta['uri'] if storage_meta else None,
                        raw_content_hash=storage_meta['hash'] if storage_meta else None,
                        raw_content_type=storage_meta['type'] if storage_meta else None,
                        raw_content_encoding=storage_meta['encoding'] if storage_meta else None,
                        raw_content_size=storage_meta['size'] if storage_meta else None,
                        raw_content_available=storage_meta is not None,
                    )
                    db.add(story)
                    db.flush()  # Flush to satisfy FK constraint for pipeline log
                    result['ingested'] += 1

                    # Log successful ingest with extraction metrics
                    self._log_pipeline(
                        db,
                        stage=PipelineStage.INGEST,
                        status=PipelineStatus.COMPLETED,
                        story_raw_id=story.id,
                        started_at=entry_started_at,
                        trace_id=trace_id,
                        entry_url=normalized['url'],
                        metadata={
                            'source': source.slug,
                            'body_downloaded': normalized.get('body_downloaded', False),
                            'extractor_used': normalized.get('extractor_used'),
                            'extraction_duration_ms': normalized.get('extraction_duration_ms', 0),
                        },
                    )

                except Exception as e:
                    logger.error(f"Error processing entry from {source.slug}: {e}")
                    result['errors'].append(str(e))
                    # Log failed entry with details
                    self._log_pipeline(
                        db,
                        stage=PipelineStage.INGEST,
                        status=PipelineStatus.FAILED,
                        started_at=entry_started_at,
                        trace_id=trace_id,
                        entry_url=entry_url,
                        error_message=str(e),
                        metadata={'source': source.slug},
                    )

            db.commit()

        except Exception as e:
            db.rollback()  # Rollback any pending changes before logging
            source_slug = source.slug if source else "unknown"
            logger.error(f"Error fetching feed from {source_slug}: {e}")
            result['errors'].append(f"Feed fetch failed: {e}")
            self._log_pipeline(
                db,
                stage=PipelineStage.INGEST,
                status=PipelineStatus.FAILED,
                started_at=started_at,
                trace_id=trace_id,
                error_message=str(e),
                metadata={'source': source_slug},
            )
            db.commit()  # Commit the error log

        return result

    def ingest_all(
        self,
        db: Session,
        source_slugs: Optional[List[str]] = None,
        max_items_per_source: int = 20,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ingest stories from all active sources (or specified sources).

        Returns:
            Dict with overall results, per-source breakdown, and body download metrics
        """
        started_at = datetime.utcnow()

        # Generate trace_id if not provided
        if trace_id is None:
            trace_id = str(uuid.uuid4())

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
            'trace_id': trace_id,
            'sources_processed': 0,
            'total_ingested': 0,
            'total_skipped_duplicate': 0,
            'total_body_downloaded': 0,
            'total_body_failed': 0,
            'source_results': [],
            'errors': [],
        }

        for source in sources:
            source_result = self.ingest_source(
                db, source, max_items=max_items_per_source, trace_id=trace_id
            )
            result['source_results'].append(source_result)
            result['sources_processed'] += 1
            result['total_ingested'] += source_result['ingested']
            result['total_skipped_duplicate'] += source_result['skipped_duplicate']
            result['total_body_downloaded'] += source_result.get('body_downloaded', 0)
            result['total_body_failed'] += source_result.get('body_failed', 0)
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
