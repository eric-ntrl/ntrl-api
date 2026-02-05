# app/services/ingestion.py
"""
Multi-source ingestion service.

Pipeline:
1. Fetch articles from RSS feeds and/or News APIs (Perigon, NewsData.io)
2. Normalize entries to common format
3. Deduplicate against existing stories
4. Classify into sections
5. Store raw content in S3
6. Store metadata in Postgres
7. Log pipeline steps

Supports additive sources: RSS (default) + Perigon (primary API) + NewsData.io (backup)
"""

import hashlib
import logging
import os
import ssl
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen

import feedparser
from sqlalchemy.orm import Session

from app import models
from app.models import PipelineStage, PipelineStatus, SourceType
from app.services.deduper import Deduper
from app.services.classifier import SectionClassifier
from app.services.body_extractor import BodyExtractor, ExtractionResult
from app.storage.factory import get_storage_provider
from app.storage.base import ContentType
from app.config import get_settings

logger = logging.getLogger(__name__)

# SSL context for fetching feeds — use default verification
SSL_CONTEXT = ssl.create_default_context()


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

        # Ingest from News APIs (additive to RSS)
        settings = get_settings()

        # Perigon API (primary)
        if settings.PERIGON_ENABLED and settings.PERIGON_API_KEY:
            try:
                import asyncio
                api_result = asyncio.run(
                    self._ingest_from_perigon(
                        db,
                        api_key=settings.PERIGON_API_KEY,
                        max_items=max_items_per_source,
                        trace_id=trace_id,
                    )
                )
                result['source_results'].append(api_result)
                result['sources_processed'] += 1
                result['total_ingested'] += api_result['ingested']
                result['total_skipped_duplicate'] += api_result['skipped_duplicate']
                result['total_body_downloaded'] += api_result.get('body_downloaded', 0)
                result['total_body_failed'] += api_result.get('body_failed', 0)
                if api_result['errors']:
                    result['errors'].extend(api_result['errors'])
            except Exception as e:
                logger.error(f"Perigon ingestion failed: {e}")
                result['errors'].append(f"Perigon: {e}")

        # NewsData.io API (backup)
        if settings.NEWSDATA_ENABLED and settings.NEWSDATA_API_KEY:
            try:
                import asyncio
                api_result = asyncio.run(
                    self._ingest_from_newsdata(
                        db,
                        api_key=settings.NEWSDATA_API_KEY,
                        max_items=max_items_per_source,
                        trace_id=trace_id,
                    )
                )
                result['source_results'].append(api_result)
                result['sources_processed'] += 1
                result['total_ingested'] += api_result['ingested']
                result['total_skipped_duplicate'] += api_result['skipped_duplicate']
                result['total_body_downloaded'] += api_result.get('body_downloaded', 0)
                result['total_body_failed'] += api_result.get('body_failed', 0)
                if api_result['errors']:
                    result['errors'].extend(api_result['errors'])
            except Exception as e:
                logger.error(f"NewsData.io ingestion failed: {e}")
                result['errors'].append(f"NewsData.io: {e}")

        finished_at = datetime.utcnow()
        result['finished_at'] = finished_at
        result['duration_ms'] = int((finished_at - started_at).total_seconds() * 1000)

        if result['errors'] and result['total_ingested'] == 0:
            result['status'] = 'failed'
        elif result['errors']:
            result['status'] = 'partial'

        return result

    def _get_or_create_api_source(
        self,
        db: Session,
        source_type: SourceType,
        source_name: str,
    ) -> models.Source:
        """Get or create a Source record for an API source."""
        slug = f"api-{source_type.value}"
        source = db.query(models.Source).filter(models.Source.slug == slug).first()
        if not source:
            source = models.Source(
                name=source_name,
                slug=slug,
                rss_url=f"https://{source_type.value}-api.internal",  # placeholder
                is_active=False,  # Don't include in RSS ingestion loop
                default_section=None,
            )
            db.add(source)
            db.flush()
        elif source.is_active:
            # Ensure API sources stay out of RSS loop
            source.is_active = False
            db.flush()
        return source

    @staticmethod
    def _slugify_publisher(publisher_name: str, source_type: SourceType) -> str:
        """Create a URL-safe slug for a publisher name, prefixed by source type."""
        import re
        slug = publisher_name.lower().strip()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        slug = slug.strip('-')
        return f"{source_type.value}-{slug}"

    def _get_or_create_publisher_source(
        self,
        db: Session,
        source_type: SourceType,
        publisher_name: str,
        cache: Dict[str, models.Source],
    ) -> models.Source:
        """Get or create a Source record for a specific publisher.

        Uses an in-memory cache to avoid repeated DB lookups within a batch.
        """
        slug = self._slugify_publisher(publisher_name, source_type)

        # Check local cache first
        if slug in cache:
            return cache[slug]

        # Check database
        source = db.query(models.Source).filter(models.Source.slug == slug).first()
        if not source:
            source = models.Source(
                name=publisher_name,
                slug=slug,
                rss_url=f"https://{source_type.value}-api.internal/{slug}",
                is_active=False,
                default_section=None,
            )
            db.add(source)
            db.flush()

        cache[slug] = source
        return source

    async def _ingest_from_perigon(
        self,
        db: Session,
        api_key: str,
        max_items: int = 100,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ingest articles from Perigon News API.

        Args:
            db: Database session
            api_key: Perigon API key
            max_items: Maximum articles to fetch
            trace_id: Pipeline trace ID

        Returns:
            Dict with ingestion results
        """
        from app.services.api_fetchers.perigon_fetcher import PerigonFetcher

        started_at = datetime.utcnow()
        result = {
            'source_slug': 'perigon',
            'source_name': 'Perigon News API',
            'source_type': SourceType.PERIGON.value,
            'ingested': 0,
            'skipped_duplicate': 0,
            'body_downloaded': 0,
            'body_failed': 0,
            'errors': [],
        }

        try:
            async with PerigonFetcher(api_key) as fetcher:
                # Fetch articles from last 24 hours
                from_date = datetime.utcnow() - timedelta(hours=24)
                articles = await fetcher.fetch_articles(
                    language="en",
                    max_results=max_items,
                    from_date=from_date,
                )

                result = self._process_api_articles(
                    db=db,
                    articles=articles,
                    source_type=SourceType.PERIGON,
                    source_name='Perigon News API',
                    trace_id=trace_id,
                    started_at=started_at,
                    result=result,
                )

        except Exception as e:
            logger.error(f"Perigon fetch failed: {e}")
            result['errors'].append(str(e))
            self._log_pipeline(
                db,
                stage=PipelineStage.INGEST,
                status=PipelineStatus.FAILED,
                started_at=started_at,
                trace_id=trace_id,
                error_message=str(e),
                metadata={'source': 'perigon', 'source_type': SourceType.PERIGON.value},
            )
            db.commit()

        return result

    async def _ingest_from_newsdata(
        self,
        db: Session,
        api_key: str,
        max_items: int = 50,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ingest articles from NewsData.io API.

        Args:
            db: Database session
            api_key: NewsData.io API key
            max_items: Maximum articles to fetch
            trace_id: Pipeline trace ID

        Returns:
            Dict with ingestion results
        """
        from app.services.api_fetchers.newsdata_fetcher import NewsDataFetcher

        started_at = datetime.utcnow()
        result = {
            'source_slug': 'newsdata',
            'source_name': 'NewsData.io',
            'source_type': SourceType.NEWSDATA.value,
            'ingested': 0,
            'skipped_duplicate': 0,
            'body_downloaded': 0,
            'body_failed': 0,
            'errors': [],
        }

        try:
            async with NewsDataFetcher(api_key, request_full_content=False) as fetcher:
                articles = await fetcher.fetch_articles(
                    language="en",
                    max_results=max_items,
                )

                result = self._process_api_articles(
                    db=db,
                    articles=articles,
                    source_type=SourceType.NEWSDATA,
                    source_name='NewsData.io',
                    trace_id=trace_id,
                    started_at=started_at,
                    result=result,
                )

        except Exception as e:
            logger.error(f"NewsData.io fetch failed: {e}")
            result['errors'].append(str(e))
            self._log_pipeline(
                db,
                stage=PipelineStage.INGEST,
                status=PipelineStatus.FAILED,
                started_at=started_at,
                trace_id=trace_id,
                error_message=str(e),
                metadata={'source': 'newsdata', 'source_type': SourceType.NEWSDATA.value},
            )
            db.commit()

        return result

    def _process_api_articles(
        self,
        db: Session,
        articles: List[Dict[str, Any]],
        source_type: SourceType,
        source_name: str,
        trace_id: Optional[str],
        started_at: datetime,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Process articles from an API source through the pipeline.

        Handles deduplication, classification, storage, and logging
        for articles from any API source.

        Args:
            db: Database session
            articles: List of normalized article entries
            source_type: Source type enum value
            source_name: Human-readable source name
            trace_id: Pipeline trace ID
            started_at: Processing start time
            result: Result dict to update

        Returns:
            Updated result dict
        """
        # Fallback API source for articles without a publisher name
        api_source = self._get_or_create_api_source(
            db, source_type, source_name
        )
        db.commit()

        # Cache for per-publisher Source records within this batch
        publisher_source_cache: Dict[str, models.Source] = {}

        for article in articles:
            entry_started_at = datetime.utcnow()
            entry_url = article.get('url', '')

            try:
                # Track body metrics
                if article.get('body_downloaded'):
                    result['body_downloaded'] += 1
                elif article.get('extraction_failure_reason'):
                    result['body_failed'] += 1

                # Check for duplicates
                is_dup, original = self.deduper.is_duplicate(
                    db,
                    url=entry_url,
                    title=article.get('title', ''),
                )

                if is_dup:
                    result['skipped_duplicate'] += 1
                    continue

                # Classify section
                section = self.classifier.classify(
                    title=article.get('title', ''),
                    description=article.get('description', ''),
                    body=article.get('body', ''),
                    source_slug=source_type.value,
                )

                # Create story
                story_id = uuid.uuid4()

                # Upload body to object storage
                body = article.get('body', '')

                # If body is missing or was flagged as truncated, try web scraping
                needs_scraping = (
                    not body
                    or article.get('extraction_failure_reason') == 'truncated_content'
                )
                if needs_scraping and entry_url:
                    logger.info(
                        f"API article body {'truncated' if body else 'missing'}, "
                        f"attempting web scraping: {entry_url}"
                    )
                    try:
                        extraction_result = self._extract_article_body(entry_url)
                        if extraction_result.success and extraction_result.body:
                            if len(extraction_result.body) > len(body):
                                body = extraction_result.body
                                logger.info(
                                    f"Web scraping successful for {entry_url}: "
                                    f"{extraction_result.char_count} chars via "
                                    f"{extraction_result.extractor_used}"
                                )
                            else:
                                logger.warning(
                                    f"Web scraping returned shorter content than API for "
                                    f"{entry_url} ({extraction_result.char_count} vs {len(body)} chars)"
                                )
                        else:
                            logger.warning(
                                f"Web scraping failed for {entry_url}: "
                                f"{extraction_result.failure_reason}"
                            )
                    except Exception as e:
                        logger.warning(f"Web scraping error for {entry_url}: {e}")

                # Check if body still has truncation markers after scraping fallback
                from app.utils.content_sanitizer import has_truncation_markers, strip_truncation_markers
                body_is_truncated = has_truncation_markers(body)
                if body_is_truncated:
                    body = strip_truncation_markers(body)
                    logger.info(
                        f"Body still truncated after scraping fallback for {entry_url}"
                    )

                if body:
                    body = self._deduplicate_paragraphs(body)

                storage_meta = self._upload_body_to_storage(
                    story_id=str(story_id),
                    body=body,
                    published_at=article.get('published_at', datetime.utcnow()),
                )

                # Truncate author to fit varchar(255)
                author = article.get('author')
                if author and len(author) > 255:
                    author = author[:255]

                # Resolve per-publisher Source (fall back to API source)
                publisher_name = article.get('source_name')
                if publisher_name and publisher_name.strip():
                    article_source = self._get_or_create_publisher_source(
                        db, source_type, publisher_name.strip(),
                        publisher_source_cache,
                    )
                else:
                    article_source = api_source

                # Create StoryRaw record
                story = models.StoryRaw(
                    id=story_id,
                    source_id=article_source.id,
                    original_url=entry_url,
                    original_title=article.get('title', ''),
                    original_description=article.get('description', ''),
                    original_author=author,
                    url_hash=self.deduper.hash_url(entry_url),
                    title_hash=self.deduper.hash_title(article.get('title', '')),
                    published_at=article.get('published_at', datetime.utcnow()),
                    ingested_at=datetime.utcnow(),
                    section=section.value,
                    is_duplicate=False,
                    feed_entry_id=article.get('api_article_id'),
                    # Source tracking
                    source_type=source_type.value,
                    api_source_id=article.get('api_article_id'),
                    # Content completeness
                    body_is_truncated=body_is_truncated,
                    # S3 storage references
                    raw_content_uri=storage_meta['uri'] if storage_meta else None,
                    raw_content_hash=storage_meta['hash'] if storage_meta else None,
                    raw_content_type=storage_meta['type'] if storage_meta else None,
                    raw_content_encoding=storage_meta['encoding'] if storage_meta else None,
                    raw_content_size=storage_meta['size'] if storage_meta else None,
                    raw_content_available=storage_meta is not None,
                )
                db.add(story)
                db.flush()
                result['ingested'] += 1

                # Log successful ingest
                self._log_pipeline(
                    db,
                    stage=PipelineStage.INGEST,
                    status=PipelineStatus.COMPLETED,
                    story_raw_id=story.id,
                    started_at=entry_started_at,
                    trace_id=trace_id,
                    entry_url=entry_url,
                    metadata={
                        'source': source_type.value,
                        'source_type': source_type.value,
                        'source_name': article.get('source_name'),
                        'body_downloaded': article.get('body_downloaded', False),
                        'extractor_used': article.get('extractor_used'),
                        'extraction_duration_ms': article.get('extraction_duration_ms', 0),
                    },
                )

            except Exception as e:
                db.rollback()  # Reset session so next article can proceed
                logger.error(f"Error processing {source_type.value} article {entry_url}: {e}")
                result['body_failed'] += 1

        db.commit()
        return result
