# tests/unit/test_brief_assembly.py
"""
Unit tests for brief assembly service — homepage URL wiring.

Covers:
- source_homepage_url is populated when Source has homepage_url
- source_homepage_url is None when Source lacks homepage_url
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.models import FeedCategory
from app.services.brief_assembly import BriefAssemblyService, StoryRow


def _make_source(slug="ap", name="AP News", homepage_url="https://apnews.com"):
    source = MagicMock()
    source.id = uuid.uuid4()
    source.slug = slug
    source.name = name
    source.homepage_url = homepage_url
    return source


def _make_story_raw(source_id=None, feed_category="world"):
    raw = MagicMock()
    raw.id = uuid.uuid4()
    raw.source_id = source_id or uuid.uuid4()
    raw.published_at = datetime.now(UTC) - timedelta(hours=1)
    raw.original_url = "https://example.com/article"
    raw.is_duplicate = False
    raw.feed_category = feed_category
    return raw


def _make_neutralized(story_raw_id=None):
    n = MagicMock()
    n.id = uuid.uuid4()
    n.story_raw_id = story_raw_id or uuid.uuid4()
    n.is_current = True
    n.neutralization_status = "success"
    n.qc_status = "passed"
    n.feed_title = "Test Headline"
    n.feed_summary = "Test summary for the article."
    n.has_manipulative_content = False
    return n


class TestBriefAssemblyHomepageUrl:
    """Test that source_homepage_url flows into DailyBriefItem."""

    def test_homepage_url_populated(self):
        """When source has homepage_url, DailyBriefItem should get it."""
        svc = BriefAssemblyService()
        source = _make_source(homepage_url="https://apnews.com")
        raw = _make_story_raw(source_id=source.id, feed_category="world")
        neutralized = _make_neutralized(story_raw_id=raw.id)

        db = MagicMock()

        # Mock get_qualifying_stories to return one story in "world"
        stories_by_cat = {cat: [] for cat in FeedCategory}
        stories_by_cat[FeedCategory.WORLD] = [StoryRow(neutralized, raw, source)]

        with patch.object(svc, "get_qualifying_stories", return_value=stories_by_cat):
            result = svc.assemble_brief(db, cutoff_hours=24, force=True)

        # Find the DailyBriefItem that was added to the session
        add_calls = db.add.call_args_list
        brief_items = [call.args[0] for call in add_calls if hasattr(call.args[0], "source_homepage_url")]

        assert len(brief_items) >= 1
        assert brief_items[0].source_homepage_url == "https://apnews.com"

    def test_homepage_url_none_when_missing(self):
        """When source has no homepage_url, DailyBriefItem should have None."""
        svc = BriefAssemblyService()
        source = _make_source(homepage_url=None)
        raw = _make_story_raw(source_id=source.id, feed_category="world")
        neutralized = _make_neutralized(story_raw_id=raw.id)

        db = MagicMock()

        stories_by_cat = {cat: [] for cat in FeedCategory}
        stories_by_cat[FeedCategory.WORLD] = [StoryRow(neutralized, raw, source)]

        with patch.object(svc, "get_qualifying_stories", return_value=stories_by_cat):
            result = svc.assemble_brief(db, cutoff_hours=24, force=True)

        add_calls = db.add.call_args_list
        brief_items = [call.args[0] for call in add_calls if hasattr(call.args[0], "source_homepage_url")]

        assert len(brief_items) >= 1
        assert brief_items[0].source_homepage_url is None
