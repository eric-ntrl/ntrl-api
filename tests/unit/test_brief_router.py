# tests/unit/test_brief_router.py
"""
Unit tests for brief router — publisher_url in API response.

Covers:
- publisher_url appears in BriefStory when source_homepage_url is set
- publisher_url is None when source_homepage_url is not set
"""

import uuid
from datetime import UTC, datetime

from app.schemas.brief import BriefStory


class TestBriefStoryPublisherUrl:
    """Test publisher_url field on BriefStory schema."""

    def test_publisher_url_present(self):
        """publisher_url should appear when provided."""
        story = BriefStory(
            id=str(uuid.uuid4()),
            feed_title="Test Headline",
            feed_summary="Test summary for the article.",
            source_name="AP News",
            source_url="https://example.com/article",
            published_at=datetime.now(UTC),
            has_manipulative_content=False,
            publisher_url="https://apnews.com",
            position=0,
        )
        assert story.publisher_url == "https://apnews.com"

    def test_publisher_url_none_by_default(self):
        """publisher_url should default to None."""
        story = BriefStory(
            id=str(uuid.uuid4()),
            feed_title="Test Headline",
            feed_summary="Test summary for the article.",
            source_name="AP News",
            source_url="https://example.com/article",
            published_at=datetime.now(UTC),
            has_manipulative_content=False,
            position=0,
        )
        assert story.publisher_url is None

    def test_publisher_url_in_serialized_output(self):
        """publisher_url should appear in model_dump() output."""
        story = BriefStory(
            id=str(uuid.uuid4()),
            feed_title="Test Headline",
            feed_summary="Test summary.",
            source_name="Reuters",
            source_url="https://example.com/article",
            published_at=datetime.now(UTC),
            has_manipulative_content=True,
            publisher_url="https://www.reuters.com",
            position=1,
        )
        data = story.model_dump()
        assert "publisher_url" in data
        assert data["publisher_url"] == "https://www.reuters.com"

    def test_publisher_url_none_in_serialized_output(self):
        """publisher_url=None should still appear in model_dump()."""
        story = BriefStory(
            id=str(uuid.uuid4()),
            feed_title="Test Headline",
            feed_summary="Test summary.",
            source_name="Unknown Source",
            source_url="https://example.com/article",
            published_at=datetime.now(UTC),
            has_manipulative_content=False,
            position=0,
        )
        data = story.model_dump()
        assert "publisher_url" in data
        assert data["publisher_url"] is None
