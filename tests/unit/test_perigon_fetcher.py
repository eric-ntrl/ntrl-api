# tests/unit/test_perigon_fetcher.py
"""
Unit tests for Perigon News API fetcher.

Tests article normalization, category mapping, error handling,
and API response processing.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services.api_fetchers.perigon_fetcher import (
    PerigonFetcher,
    PERIGON_CATEGORY_MAP,
)


class TestPerigonFetcher:
    """Tests for PerigonFetcher class."""

    @pytest.fixture
    def fetcher(self):
        """Create a PerigonFetcher instance for testing."""
        return PerigonFetcher(api_key="test-api-key")

    @pytest.fixture
    def sample_article(self):
        """Sample Perigon API article response."""
        return {
            "articleId": "abc123",
            "url": "https://example.com/news/article",
            "title": "Breaking News: Test Article",
            "content": "This is the full article body text with multiple paragraphs.",
            "description": "A short summary of the article.",
            "pubDate": "2024-01-15T12:30:00Z",
            "authorsByline": "John Doe",
            "source": {
                "name": "Example News",
                "domain": "example.com",
            },
            "categories": [
                {"name": "Technology"},
                {"name": "Business"},
            ],
            "people": [
                {"name": "Elon Musk"},
                {"name": "Tim Cook"},
            ],
            "organizations": [
                {"name": "Apple Inc."},
            ],
            "locations": [
                {"name": "San Francisco"},
            ],
        }

    @pytest.fixture
    def sample_api_response(self, sample_article):
        """Sample Perigon API response."""
        return {
            "status": 200,
            "numResults": 1,
            "articles": [sample_article],
        }

    def test_source_type(self, fetcher):
        """Test source_type property."""
        assert fetcher.source_type == "perigon"

    def test_normalize_article_success(self, fetcher, sample_article):
        """Test successful article normalization."""
        start_time = datetime.utcnow().timestamp()
        result = fetcher._normalize_article(sample_article, start_time)

        assert result is not None
        assert result["url"] == "https://example.com/news/article"
        assert result["title"] == "Breaking News: Test Article"
        assert result["body"] == "This is the full article body text with multiple paragraphs."
        assert result["description"] == "A short summary of the article."
        assert result["author"] == "John Doe"
        assert result["source_name"] == "Example News"
        assert result["source_domain"] == "example.com"
        assert result["api_source"] == "perigon"
        assert result["api_article_id"] == "abc123"
        assert "Technology" in result["categories"]
        assert "Business" in result["categories"]
        assert "Elon Musk" in result["entities"]["people"]
        assert "Apple Inc." in result["entities"]["organizations"]
        assert "San Francisco" in result["entities"]["locations"]
        assert result["body_downloaded"] is True
        assert result["extractor_used"] == "perigon_api"

    def test_normalize_article_missing_url(self, fetcher):
        """Test normalization returns None for missing URL."""
        article = {"title": "Test", "content": "Body"}
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())
        assert result is None

    def test_normalize_article_missing_title(self, fetcher):
        """Test normalization returns None for missing title."""
        article = {"url": "https://example.com", "content": "Body"}
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())
        assert result is None

    def test_normalize_article_no_body(self, fetcher):
        """Test normalization with missing body."""
        article = {
            "url": "https://example.com",
            "title": "Test Article",
            "pubDate": "2024-01-15T12:00:00Z",
        }
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())

        assert result is not None
        assert result["body"] == ""
        assert result["body_downloaded"] is False
        assert result["extraction_failure_reason"] == "no_content"

    def test_normalize_article_string_categories(self, fetcher):
        """Test normalization with string categories (not dicts)."""
        article = {
            "url": "https://example.com",
            "title": "Test",
            "pubDate": "2024-01-15T12:00:00Z",
            "categories": ["Tech", "Science"],
        }
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())

        assert result is not None
        assert "Tech" in result["categories"]
        assert "Science" in result["categories"]

    def test_normalize_article_invalid_date(self, fetcher):
        """Test normalization with invalid date falls back to now."""
        article = {
            "url": "https://example.com",
            "title": "Test",
            "pubDate": "invalid-date",
        }
        before = datetime.utcnow()
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())
        after = datetime.utcnow()

        assert result is not None
        assert before <= result["published_at"] <= after

    @pytest.mark.asyncio
    async def test_fetch_articles_success(self, fetcher, sample_api_response):
        """Test successful article fetch."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_api_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(
            fetcher.client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            articles = await fetcher.fetch_articles(max_results=10)

            assert len(articles) == 1
            assert articles[0]["title"] == "Breaking News: Test Article"
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_articles_with_categories(self, fetcher, sample_api_response):
        """Test fetch with category filter."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_api_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(
            fetcher.client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            await fetcher.fetch_articles(categories=["Technology", "Business"])

            call_args = mock_get.call_args
            params = call_args.kwargs.get("params", {})
            assert "Technology,Business" in params.get("category", "")

    @pytest.mark.asyncio
    async def test_fetch_articles_with_date_filter(self, fetcher, sample_api_response):
        """Test fetch with date filter."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_api_response
        mock_response.raise_for_status = MagicMock()

        from_date = datetime(2024, 1, 1, 12, 0, 0)

        with patch.object(
            fetcher.client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            await fetcher.fetch_articles(from_date=from_date)

            call_args = mock_get.call_args
            params = call_args.kwargs.get("params", {})
            assert "2024-01-01T12:00:00" in params.get("from", "")

    @pytest.mark.asyncio
    async def test_fetch_articles_api_error(self, fetcher):
        """Test API error handling."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=mock_response,
        )

        with patch.object(
            fetcher.client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            with pytest.raises(httpx.HTTPStatusError):
                await fetcher.fetch_articles()

    @pytest.mark.asyncio
    async def test_fetch_stories(self, fetcher):
        """Test fetching clustered stories."""
        stories_response = {
            "stories": [
                {
                    "id": "story1",
                    "title": "Major Tech Event",
                    "articleCount": 15,
                },
            ],
        }
        mock_response = MagicMock()
        mock_response.json.return_value = stories_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(
            fetcher.client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_response

            stories = await fetcher.fetch_stories(max_results=10)

            assert len(stories) == 1
            assert stories[0]["title"] == "Major Tech Event"
            assert stories[0]["articleCount"] == 15

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        async with PerigonFetcher(api_key="test") as fetcher:
            assert fetcher.api_key == "test"

    @pytest.mark.asyncio
    async def test_close(self, fetcher):
        """Test client cleanup."""
        with patch.object(fetcher.client, "aclose", new_callable=AsyncMock) as mock_close:
            await fetcher.close()
            mock_close.assert_called_once()


class TestPerigonSourceNameFallback:
    """Tests for source name fallback when Perigon omits source.name."""

    @pytest.fixture
    def fetcher(self):
        return PerigonFetcher(api_key="test-api-key")

    def test_missing_source_name_uses_domain(self, fetcher):
        """When source.name is null but source.domain exists, derive from domain."""
        article = {
            "url": "https://www.reuters.com/article/123",
            "title": "Test Article",
            "content": "Full body text here.",
            "pubDate": "2024-01-15T12:00:00Z",
            "source": {"name": None, "domain": "reuters.com"},
        }
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())
        assert result is not None
        assert result["source_name"] == "reuters.com"

    def test_missing_source_name_strips_www(self, fetcher):
        """Domain with www. prefix should be stripped."""
        article = {
            "url": "https://www.nytimes.com/article/123",
            "title": "Test Article",
            "content": "Full body text here.",
            "pubDate": "2024-01-15T12:00:00Z",
            "source": {"name": None, "domain": "www.nytimes.com"},
        }
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())
        assert result is not None
        assert result["source_name"] == "nytimes.com"

    def test_missing_source_name_and_domain_uses_url(self, fetcher):
        """When both source.name and source.domain are null, extract from URL."""
        article = {
            "url": "https://www.apnews.com/article/election-2024",
            "title": "Test Article",
            "content": "Full body text here.",
            "pubDate": "2024-01-15T12:00:00Z",
            "source": {},
        }
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())
        assert result is not None
        assert result["source_name"] == "apnews.com"

    def test_source_name_present_not_overridden(self, fetcher):
        """When source.name is present, it should be used as-is."""
        article = {
            "url": "https://reuters.com/article/123",
            "title": "Test Article",
            "content": "Full body text here.",
            "pubDate": "2024-01-15T12:00:00Z",
            "source": {"name": "Reuters", "domain": "reuters.com"},
        }
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())
        assert result is not None
        assert result["source_name"] == "Reuters"


class TestPerigonTruncationDetection:
    """Tests for Perigon content truncation detection."""

    @pytest.fixture
    def fetcher(self):
        return PerigonFetcher(api_key="test-api-key")

    def test_detects_symbols_marker(self, fetcher):
        """Body with ...[1811 symbols] should be detected as truncated."""
        body = "Some article text that ends abruptly...[1811 symbols]"
        assert fetcher._is_body_truncated(body) is True

    def test_detects_chars_marker(self, fetcher):
        """Body with ...[234 chars] should be detected as truncated."""
        body = "Article beginning...[234 chars]"
        assert fetcher._is_body_truncated(body) is True

    def test_detects_characters_marker(self, fetcher):
        """Body with ...[500 characters] should be detected as truncated."""
        body = "Article text...[500 characters]"
        assert fetcher._is_body_truncated(body) is True

    def test_normal_body_not_truncated(self, fetcher):
        """Normal article body should not be flagged as truncated."""
        body = "This is a normal article body with multiple paragraphs."
        assert fetcher._is_body_truncated(body) is False

    def test_empty_body_not_truncated(self, fetcher):
        """Empty body should not be flagged as truncated."""
        assert fetcher._is_body_truncated("") is False
        assert fetcher._is_body_truncated(None) is False

    def test_truncated_body_flags_correctly(self, fetcher):
        """Truncated body should set body_downloaded=False and extraction_failure_reason."""
        article = {
            "url": "https://example.com/article",
            "title": "Test Article",
            "content": "Some text that ends...[1811 symbols]",
            "pubDate": "2024-01-15T12:00:00Z",
            "source": {"name": "Example News", "domain": "example.com"},
        }
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())
        assert result is not None
        assert result["body_downloaded"] is False
        assert result["extraction_failure_reason"] == "truncated_content"
        assert result["extractor_used"] is None
        # Truncated body is still stored as fallback
        assert result["body"] == "Some text that ends...[1811 symbols]"


class TestPerigonMarkerPreservation:
    """Verify that Perigon fetcher preserves truncation markers in the body.

    Stripping is the ingestion layer's responsibility, not the fetcher's.
    The fetcher should pass the raw body through so ingestion can detect
    and flag truncation.
    """

    @pytest.fixture
    def fetcher(self):
        return PerigonFetcher(api_key="test-api-key")

    def test_truncated_body_preserved_in_output(self, fetcher):
        """Fetcher should NOT strip markers — ingestion handles that."""
        article = {
            "url": "https://example.com/article",
            "title": "Test Article",
            "content": "Some text that ends...[1811 symbols]",
            "pubDate": "2024-01-15T12:00:00Z",
            "source": {"name": "Example News", "domain": "example.com"},
        }
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())
        assert result is not None
        # Markers should be preserved in the body
        assert "...[1811 symbols]" in result["body"]


class TestPerigonCategoryMapping:
    """Tests for Perigon category to NTRL mapping."""

    def test_direct_mappings(self):
        """Test direct category mappings exist."""
        assert PERIGON_CATEGORY_MAP["Business"] == "business"
        assert PERIGON_CATEGORY_MAP["Tech"] == "technology"
        assert PERIGON_CATEGORY_MAP["Sports"] == "sports"
        assert PERIGON_CATEGORY_MAP["Health"] == "health"

    def test_world_mappings(self):
        """Test world/international mappings."""
        assert PERIGON_CATEGORY_MAP["World"] == "world"
        assert PERIGON_CATEGORY_MAP["International"] == "world"

    def test_culture_mappings(self):
        """Test culture category mappings."""
        assert PERIGON_CATEGORY_MAP["Entertainment"] == "culture"
        assert PERIGON_CATEGORY_MAP["Lifestyle"] == "culture"
        assert PERIGON_CATEGORY_MAP["Arts"] == "culture"
