# tests/test_brief_assembly.py
"""
Tests for BriefAssemblyService.

Covers:
- Deterministic story sorting (published_at DESC, source priority ASC, story ID ASC)
- Empty category handling
- Story grouping into correct feed categories
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from app.models import FEED_CATEGORY_ORDER, FeedCategory
from app.services.brief_assembly import (
    DEFAULT_PRIORITY,
    BriefAssemblyService,
    StoryRow,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(slug: str = "ap", name: str = "AP News") -> MagicMock:
    """Create a mock Source object."""
    source = MagicMock()
    source.slug = slug
    source.name = name
    return source


def _make_story_raw(
    story_id: uuid.UUID | None = None,
    published_at: datetime | None = None,
    source_id: uuid.UUID | None = None,
    feed_category: str | None = "world",
    section: str | None = None,
    is_duplicate: bool = False,
    original_url: str = "https://example.com/article",
) -> MagicMock:
    """Create a mock StoryRaw object."""
    raw = MagicMock()
    raw.id = story_id or uuid.uuid4()
    raw.published_at = published_at or datetime.now(UTC)
    raw.source_id = source_id or uuid.uuid4()
    raw.feed_category = feed_category
    raw.section = section
    raw.is_duplicate = is_duplicate
    raw.original_url = original_url
    return raw


def _make_neutralized(
    neutralized_id: uuid.UUID | None = None,
    story_raw_id: uuid.UUID | None = None,
    is_current: bool = True,
    status: str = "success",
    feed_title: str = "Test Title",
    feed_summary: str = "Test summary.",
    has_manipulative_content: bool = False,
) -> MagicMock:
    """Create a mock StoryNeutralized object."""
    n = MagicMock()
    n.id = neutralized_id or uuid.uuid4()
    n.story_raw_id = story_raw_id or uuid.uuid4()
    n.is_current = is_current
    n.neutralization_status = status
    n.feed_title = feed_title
    n.feed_summary = feed_summary
    n.has_manipulative_content = has_manipulative_content
    return n


def _make_story_row(
    slug: str = "ap",
    published_at: datetime | None = None,
    story_id: uuid.UUID | None = None,
    feed_category: str | None = "world",
    section: str | None = None,
) -> StoryRow:
    """Create a StoryRow named tuple with mock data."""
    source = _make_source(slug=slug)
    raw = _make_story_raw(
        story_id=story_id,
        published_at=published_at,
        feed_category=feed_category,
        section=section,
    )
    neutralized = _make_neutralized(story_raw_id=raw.id)
    return StoryRow(neutralized=neutralized, raw=raw, source=source)


# ---------------------------------------------------------------------------
# Test: Source priority lookup
# ---------------------------------------------------------------------------


class TestSourcePriority:
    """Tests for _get_source_priority."""

    def setup_method(self):
        self.service = BriefAssemblyService()

    def test_ap_has_highest_priority(self):
        assert self.service._get_source_priority("ap") == 1

    def test_ap_news_alias(self):
        assert self.service._get_source_priority("ap-news") == 1

    def test_reuters_priority(self):
        assert self.service._get_source_priority("reuters") == 2

    def test_bbc_priority(self):
        assert self.service._get_source_priority("bbc") == 3

    def test_npr_priority(self):
        assert self.service._get_source_priority("npr") == 4

    def test_unknown_source_gets_default(self):
        assert self.service._get_source_priority("random-blog") == DEFAULT_PRIORITY

    def test_case_insensitive(self):
        assert self.service._get_source_priority("AP") == 1
        assert self.service._get_source_priority("Reuters") == 2
        assert self.service._get_source_priority("BBC") == 3


# ---------------------------------------------------------------------------
# Test: Deterministic sorting
# ---------------------------------------------------------------------------


class TestSortStories:
    """Tests for _sort_stories deterministic ordering."""

    def setup_method(self):
        self.service = BriefAssemblyService()

    def test_sort_by_published_at_desc(self):
        """Most recent stories should come first."""
        now = datetime.now(UTC)
        older = _make_story_row(slug="ap", published_at=now - timedelta(hours=2))
        newer = _make_story_row(slug="ap", published_at=now - timedelta(hours=1))
        newest = _make_story_row(slug="ap", published_at=now)

        result = self.service._sort_stories([older, newest, newer])

        assert result[0].raw.published_at == newest.raw.published_at
        assert result[1].raw.published_at == newer.raw.published_at
        assert result[2].raw.published_at == older.raw.published_at

    def test_tiebreak_by_source_priority(self):
        """When published_at is the same, AP should come before Reuters."""
        same_time = datetime(2025, 1, 15, 12, 0, 0)
        reuters_story = _make_story_row(slug="reuters", published_at=same_time)
        ap_story = _make_story_row(slug="ap", published_at=same_time)
        unknown_story = _make_story_row(slug="daily-mail", published_at=same_time)

        result = self.service._sort_stories([reuters_story, unknown_story, ap_story])

        assert result[0].source.slug == "ap"
        assert result[1].source.slug == "reuters"
        assert result[2].source.slug == "daily-mail"

    def test_tiebreak_by_story_id(self):
        """When published_at and source priority are the same, sort by story ID string ASC."""
        same_time = datetime(2025, 1, 15, 12, 0, 0)

        # Create UUIDs with known sort order
        id_a = uuid.UUID("00000000-0000-0000-0000-000000000001")
        id_b = uuid.UUID("00000000-0000-0000-0000-000000000002")
        id_c = uuid.UUID("00000000-0000-0000-0000-000000000003")

        story_c = _make_story_row(slug="ap", published_at=same_time, story_id=id_c)
        story_a = _make_story_row(slug="ap", published_at=same_time, story_id=id_a)
        story_b = _make_story_row(slug="ap", published_at=same_time, story_id=id_b)

        result = self.service._sort_stories([story_c, story_a, story_b])

        assert str(result[0].raw.id) == str(id_a)
        assert str(result[1].raw.id) == str(id_b)
        assert str(result[2].raw.id) == str(id_c)

    def test_empty_list_returns_empty(self):
        """Sorting an empty list should return an empty list."""
        result = self.service._sort_stories([])
        assert result == []

    def test_single_story_unchanged(self):
        """A single-element list should remain unchanged."""
        story = _make_story_row()
        result = self.service._sort_stories([story])
        assert len(result) == 1
        assert result[0] is story

    def test_full_tiebreak_cascade(self):
        """Verify the full 3-tier tiebreak: published_at DESC, source ASC, ID ASC."""
        now = datetime.now(UTC)

        # Same time, same source, different IDs
        id_1 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
        id_2 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")

        # Same time, different sources
        s1 = _make_story_row(slug="ap", published_at=now, story_id=id_2)
        s2 = _make_story_row(slug="reuters", published_at=now, story_id=id_1)
        s3 = _make_story_row(slug="ap", published_at=now, story_id=id_1)

        # Newer story should be first regardless
        newer_time = now + timedelta(seconds=1)
        s4 = _make_story_row(slug="daily-mail", published_at=newer_time)

        result = self.service._sort_stories([s1, s2, s3, s4])

        # s4 is newest => first
        assert result[0] is s4
        # s3 and s1 are AP (priority 1) at same time; s3 has lower ID string
        assert result[1] is s3
        assert result[2] is s1
        # s2 is Reuters (priority 2) at same time
        assert result[3] is s2


# ---------------------------------------------------------------------------
# Test: Empty categories
# ---------------------------------------------------------------------------


class TestEmptyCategories:
    """Tests that empty categories are handled correctly."""

    def setup_method(self):
        self.service = BriefAssemblyService()

    def test_no_stories_returns_all_categories_empty(self):
        """When there are no DB results, every FeedCategory should be an empty list."""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        cutoff = datetime.now(UTC) - timedelta(hours=24)
        result = self.service.get_qualifying_stories(mock_db, cutoff)

        # All 10 categories should exist as keys
        assert len(result) == len(FeedCategory)
        for cat in FeedCategory:
            assert cat in result
            assert result[cat] == []

    def test_stories_only_in_one_category(self):
        """When all stories are in one category, others should remain empty."""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query

        # One story in "technology"
        source = _make_source(slug="ap")
        raw = _make_story_raw(feed_category="technology")
        neutralized = _make_neutralized(story_raw_id=raw.id)
        mock_query.all.return_value = [(neutralized, raw, source)]

        cutoff = datetime.now(UTC) - timedelta(hours=24)
        result = self.service.get_qualifying_stories(mock_db, cutoff)

        assert len(result[FeedCategory.TECHNOLOGY]) == 1
        # All other categories should be empty
        for cat in FeedCategory:
            if cat != FeedCategory.TECHNOLOGY:
                assert result[cat] == [], f"{cat} should be empty"


# ---------------------------------------------------------------------------
# Test: Story grouping into feed categories
# ---------------------------------------------------------------------------


class TestStoryGrouping:
    """Tests that stories are grouped into the correct feed categories."""

    def setup_method(self):
        self.service = BriefAssemblyService()

    def _run_with_db_results(self, db_results):
        """Helper: run get_qualifying_stories with given mock DB results."""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = db_results

        cutoff = datetime.now(UTC) - timedelta(hours=24)
        return self.service.get_qualifying_stories(mock_db, cutoff)

    def test_stories_group_by_feed_category(self):
        """Stories with different feed_category values go to different buckets."""
        source = _make_source(slug="reuters")

        raw_world = _make_story_raw(feed_category="world")
        n_world = _make_neutralized(story_raw_id=raw_world.id)

        raw_sports = _make_story_raw(feed_category="sports")
        n_sports = _make_neutralized(story_raw_id=raw_sports.id)

        raw_health = _make_story_raw(feed_category="health")
        n_health = _make_neutralized(story_raw_id=raw_health.id)

        result = self._run_with_db_results(
            [
                (n_world, raw_world, source),
                (n_sports, raw_sports, source),
                (n_health, raw_health, source),
            ]
        )

        assert len(result[FeedCategory.WORLD]) == 1
        assert len(result[FeedCategory.SPORTS]) == 1
        assert len(result[FeedCategory.HEALTH]) == 1
        assert len(result[FeedCategory.BUSINESS]) == 0

    def test_multiple_stories_in_same_category(self):
        """Multiple stories in the same category all appear in that bucket."""
        source = _make_source(slug="ap")

        stories = []
        for i in range(5):
            raw = _make_story_raw(feed_category="business")
            n = _make_neutralized(story_raw_id=raw.id, feed_title=f"Business Story {i}")
            stories.append((n, raw, source))

        result = self._run_with_db_results(stories)
        assert len(result[FeedCategory.BUSINESS]) == 5

    def test_unclassified_articles_skipped(self):
        """Stories without feed_category are skipped (not misrouted via legacy section)."""
        source = _make_source(slug="ap")

        raw = _make_story_raw(feed_category=None, section="world")
        n = _make_neutralized(story_raw_id=raw.id)

        result = self._run_with_db_results([(n, raw, source)])
        for cat in FeedCategory:
            assert result[cat] == [], f"Category {cat} should be empty"

    def test_no_category_no_section_skipped(self):
        """Stories with neither feed_category nor section are skipped entirely."""
        source = _make_source(slug="ap")

        raw = _make_story_raw(feed_category=None, section=None)
        n = _make_neutralized(story_raw_id=raw.id)

        result = self._run_with_db_results([(n, raw, source)])
        for cat in FeedCategory:
            assert result[cat] == [], f"Category {cat} should be empty"

    def test_invalid_feed_category_skipped(self):
        """Stories with an invalid/unknown feed_category value are skipped."""
        source = _make_source(slug="ap")

        raw = _make_story_raw(feed_category="nonexistent_category")
        n = _make_neutralized(story_raw_id=raw.id)

        result = self._run_with_db_results([(n, raw, source)])
        for cat in FeedCategory:
            assert result[cat] == [], f"Category {cat} should be empty"

    def test_stories_sorted_within_each_category(self):
        """Stories within each category should be sorted deterministically."""
        source_ap = _make_source(slug="ap")
        source_reuters = _make_source(slug="reuters")
        now = datetime.now(UTC)

        # Two stories in same category, different times
        raw_old = _make_story_raw(
            feed_category="world",
            published_at=now - timedelta(hours=2),
        )
        raw_new = _make_story_raw(
            feed_category="world",
            published_at=now - timedelta(hours=1),
        )
        n_old = _make_neutralized(story_raw_id=raw_old.id)
        n_new = _make_neutralized(story_raw_id=raw_new.id)

        result = self._run_with_db_results(
            [
                (n_old, raw_old, source_reuters),
                (n_new, raw_new, source_ap),
            ]
        )

        world_stories = result[FeedCategory.WORLD]
        assert len(world_stories) == 2
        # Newer story should come first (published_at DESC)
        assert world_stories[0].raw.published_at == raw_new.published_at
        assert world_stories[1].raw.published_at == raw_old.published_at

    def test_all_ten_categories_present_as_keys(self):
        """The result dict always has all 10 FeedCategory keys, even if empty."""
        result = self._run_with_db_results([])

        expected_categories = {
            FeedCategory.WORLD,
            FeedCategory.US,
            FeedCategory.LOCAL,
            FeedCategory.BUSINESS,
            FeedCategory.TECHNOLOGY,
            FeedCategory.SCIENCE,
            FeedCategory.HEALTH,
            FeedCategory.ENVIRONMENT,
            FeedCategory.SPORTS,
            FeedCategory.CULTURE,
        }
        assert set(result.keys()) == expected_categories

    def test_feed_category_order_covers_all_categories(self):
        """Verify FEED_CATEGORY_ORDER has an entry for every FeedCategory."""
        for cat in FeedCategory:
            assert cat in FEED_CATEGORY_ORDER, f"{cat} missing from FEED_CATEGORY_ORDER"
