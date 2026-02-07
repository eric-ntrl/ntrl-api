# app/services/deduper.py
"""
Deduplication service for detecting duplicate stories.

Dedupe rules:
1. Exact URL match (same url_hash)
2. Similar title match (same title_hash after normalization)
3. Same story across sources (title similarity > threshold)
"""

import hashlib
import re
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import models


class Deduper:
    """Deduplication service."""

    # Similarity threshold for title matching
    TITLE_SIMILARITY_THRESHOLD = 0.85

    @staticmethod
    def normalize_text(text: str) -> str:
        """Normalize text for comparison."""
        if not text:
            return ""
        # Lowercase
        text = text.lower()
        # Remove punctuation
        text = re.sub(r"[^\w\s]", "", text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def hash_url(url: str) -> str:
        """Generate SHA256 hash of URL."""
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    @staticmethod
    def hash_title(title: str) -> str:
        """Generate SHA256 hash of normalized title."""
        normalized = Deduper.normalize_text(title)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def jaccard_similarity(text1: str, text2: str) -> float:
        """Calculate Jaccard similarity between two texts."""
        words1 = set(Deduper.normalize_text(text1).split())
        words2 = set(Deduper.normalize_text(text2).split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    def is_duplicate(
        self,
        db: Session,
        url: str,
        title: str,
        lookback_hours: int = 72,
    ) -> tuple[bool, models.StoryRaw | None]:
        """
        Check if a story is a duplicate.

        Returns:
            Tuple of (is_duplicate, original_story_if_duplicate)
        """
        url_hash = self.hash_url(url)
        title_hash = self.hash_title(title)
        cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)

        # Check 1: Exact URL match
        existing = db.query(models.StoryRaw).filter(models.StoryRaw.url_hash == url_hash).first()
        if existing:
            return True, existing

        # Check 2: Exact title hash match
        existing = (
            db.query(models.StoryRaw)
            .filter(
                models.StoryRaw.title_hash == title_hash,
                models.StoryRaw.ingested_at >= cutoff,
            )
            .first()
        )
        if existing:
            return True, existing

        # Check 3: Similar title (more expensive, limit scope)
        recent_stories = (
            db.query(models.StoryRaw)
            .filter(
                models.StoryRaw.ingested_at >= cutoff,
                models.StoryRaw.is_duplicate == False,
            )
            .order_by(models.StoryRaw.ingested_at.desc())
            .limit(500)
            .all()
        )

        for story in recent_stories:
            similarity = self.jaccard_similarity(title, story.original_title)
            if similarity >= self.TITLE_SIMILARITY_THRESHOLD:
                return True, story

        return False, None

    def find_duplicates_batch(
        self,
        db: Session,
        stories: list,
        lookback_hours: int = 72,
    ) -> dict:
        """
        Find duplicates for a batch of stories.

        Args:
            stories: List of dicts with 'url' and 'title' keys

        Returns:
            Dict mapping story index to (is_duplicate, original_id)
        """
        results = {}
        for idx, story in enumerate(stories):
            is_dup, original = self.is_duplicate(
                db,
                url=story.get("url", ""),
                title=story.get("title", ""),
                lookback_hours=lookback_hours,
            )
            results[idx] = {
                "is_duplicate": is_dup,
                "duplicate_of_id": str(original.id) if original else None,
            }
        return results
