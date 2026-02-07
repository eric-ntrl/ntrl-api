# tests/unit/test_newsdata_fetcher.py
"""
Unit tests for NewsData.io API fetcher.

Tests article normalization, full content handling, error handling,
and API response processing.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.api_fetchers.newsdata_fetcher import (
    NEWSDATA_CATEGORY_MAP,
    NewsDataFetcher,
)


class TestNewsDataFetcher:
    """Tests for NewsDataFetcher class."""

    @pytest.fixture
    def fetcher(self):
        """Create a NewsDataFetcher instance for testing."""
        return NewsDataFetcher(api_key="test-api-key")

    @pytest.fixture
    def fetcher_no_full_content(self):
        """Create a fetcher that doesn't request full content."""
        return NewsDataFetcher(api_key="test-api-key", request_full_content=False)

    @pytest.fixture
    def sample_article(self):
        """Sample NewsData.io API article response."""
        return {
            "article_id": "xyz789",
            "link": "https://example.com/news/story",
            "title": "Important News: Test Story",
            "full_content": "This is the full article content from NewsData.io with detailed information.",
            "content": "Shorter content without full text.",
            "description": "A brief description of the news story.",
            "pubDate": "2024-01-15 14:30:00",
            "creator": ["Jane Smith", "Bob Jones"],
            "source_name": "News Source",
            "source_url": "https://newssource.com",
            "category": ["technology", "business"],
            "keywords": ["AI", "innovation", "startup"],
        }

    @pytest.fixture
    def sample_article_no_full_content(self, sample_article):
        """Article without full_content field."""
        article = sample_article.copy()
        del article["full_content"]
        return article

    @pytest.fixture
    def sample_api_response(self, sample_article):
        """Sample NewsData.io API response."""
        return {
            "status": "success",
            "totalResults": 1,
            "results": [sample_article],
        }

    def test_source_type(self, fetcher):
        """Test source_type property."""
        assert fetcher.source_type == "newsdata"

    def test_normalize_article_success(self, fetcher, sample_article):
        """Test successful article normalization."""
        start_time = datetime.utcnow().timestamp()
        result = fetcher._normalize_article(sample_article, start_time)

        assert result is not None
        assert result["url"] == "https://example.com/news/story"
        assert result["title"] == "Important News: Test Story"
        assert result["body"] == "This is the full article content from NewsData.io with detailed information."
        assert result["description"] == "A brief description of the news story."
        assert result["author"] == "Jane Smith"  # First author from list
        assert result["source_name"] == "News Source"
        assert result["source_domain"] == "https://newssource.com"
        assert result["api_source"] == "newsdata"
        assert result["api_article_id"] == "xyz789"
        assert "technology" in result["categories"]
        assert "business" in result["categories"]
        assert "AI" in result["entities"]["keywords"]
        assert result["body_downloaded"] is True
        assert result["extractor_used"] == "newsdata_api"

    def test_normalize_article_fallback_to_content(self, fetcher, sample_article_no_full_content):
        """Test normalization falls back to content when no full_content."""
        result = fetcher._normalize_article(sample_article_no_full_content, datetime.utcnow().timestamp())

        assert result is not None
        assert result["body"] == "Shorter content without full text."
        # body_downloaded is True because we have some content
        assert result["body_downloaded"] is True

    def test_normalize_article_fallback_to_description(self, fetcher):
        """Test normalization falls back to description when no content."""
        article = {
            "link": "https://example.com",
            "title": "Test",
            "description": "Just a description",
            "pubDate": "2024-01-15 12:00:00",
        }
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())

        assert result is not None
        assert result["body"] == "Just a description"

    def test_normalize_article_missing_url(self, fetcher):
        """Test normalization returns None for missing URL."""
        article = {"title": "Test", "full_content": "Body"}
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())
        assert result is None

    def test_normalize_article_missing_title(self, fetcher):
        """Test normalization returns None for missing title."""
        article = {"link": "https://example.com", "full_content": "Body"}
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())
        assert result is None

    def test_normalize_article_no_body(self, fetcher):
        """Test normalization with no body content."""
        article = {
            "link": "https://example.com",
            "title": "Test Article",
            "pubDate": "2024-01-15 12:00:00",
        }
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())

        assert result is not None
        assert result["body"] == ""
        assert result["body_downloaded"] is False
        assert result["extraction_failure_reason"] == "no_content"

    def test_normalize_article_string_creator(self, fetcher):
        """Test normalization with string creator (not list)."""
        article = {
            "link": "https://example.com",
            "title": "Test",
            "creator": "Single Author",
            "pubDate": "2024-01-15 12:00:00",
        }
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())

        assert result is not None
        assert result["author"] == "Single Author"

    def test_normalize_article_string_category(self, fetcher):
        """Test normalization with string category (not list)."""
        article = {
            "link": "https://example.com",
            "title": "Test",
            "category": "technology",
            "pubDate": "2024-01-15 12:00:00",
        }
        result = fetcher._normalize_article(article, datetime.utcnow().timestamp())

        assert result is not None
        assert "technology" in result["categories"]

    def test_normalize_article_date_formats(self, fetcher):
        """Test various date format handling."""
        # Standard NewsData.io format
        article1 = {
            "link": "https://example.com",
            "title": "Test",
            "pubDate": "2024-01-15 12:30:00",
        }
        result1 = fetcher._normalize_article(article1, datetime.utcnow().timestamp())
        assert result1["published_at"] == datetime(2024, 1, 15, 12, 30, 0)

        # ISO format with Z
        article2 = {
            "link": "https://example.com",
            "title": "Test",
            "pubDate": "2024-01-15T12:30:00Z",
        }
        result2 = fetcher._normalize_article(article2, datetime.utcnow().timestamp())
        assert result2 is not None

    def test_normalize_article_invalid_date(self, fetcher):
        """Test normalization with invalid date falls back to now."""
        article = {
            "link": "https://example.com",
            "title": "Test",
            "pubDate": "not-a-date",
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

        with patch.object(fetcher.client, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            articles = await fetcher.fetch_articles(max_results=10)

            assert len(articles) == 1
            assert articles[0]["title"] == "Important News: Test Story"
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_articles_requests_full_content(self, fetcher, sample_api_response):
        """Test that full_content=1 is requested."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_api_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(fetcher.client, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            await fetcher.fetch_articles()

            call_args = mock_get.call_args
            params = call_args.kwargs.get("params", {})
            assert params.get("full_content") == 1

    @pytest.mark.asyncio
    async def test_fetch_articles_without_full_content(self, fetcher_no_full_content, sample_api_response):
        """Test fetch without full_content parameter."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_api_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(fetcher_no_full_content.client, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            await fetcher_no_full_content.fetch_articles()

            call_args = mock_get.call_args
            params = call_args.kwargs.get("params", {})
            assert "full_content" not in params

    @pytest.mark.asyncio
    async def test_fetch_articles_with_categories(self, fetcher, sample_api_response):
        """Test fetch with category filter."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_api_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(fetcher.client, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            await fetcher.fetch_articles(categories=["technology", "science"])

            call_args = mock_get.call_args
            params = call_args.kwargs.get("params", {})
            assert "technology,science" in params.get("category", "")

    @pytest.mark.asyncio
    async def test_fetch_articles_api_error_status(self, fetcher):
        """Test API error response handling."""
        error_response = {
            "status": "error",
            "results": {"message": "Invalid API key"},
        }
        mock_response = MagicMock()
        mock_response.json.return_value = error_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(fetcher.client, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            with pytest.raises(ValueError, match="Invalid API key"):
                await fetcher.fetch_articles()

    @pytest.mark.asyncio
    async def test_fetch_articles_http_error(self, fetcher):
        """Test HTTP error handling."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=MagicMock(),
            response=mock_response,
        )

        with patch.object(fetcher.client, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            with pytest.raises(httpx.HTTPStatusError):
                await fetcher.fetch_articles()

    @pytest.mark.asyncio
    async def test_fetch_by_keywords(self, fetcher, sample_api_response):
        """Test keyword search."""
        mock_response = MagicMock()
        mock_response.json.return_value = sample_api_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(fetcher.client, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            articles = await fetcher.fetch_by_keywords(keywords=["AI", "machine learning"])

            assert len(articles) == 1
            call_args = mock_get.call_args
            params = call_args.kwargs.get("params", {})
            assert "AI OR machine learning" in params.get("q", "")

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        async with NewsDataFetcher(api_key="test") as fetcher:
            assert fetcher.api_key == "test"

    @pytest.mark.asyncio
    async def test_close(self, fetcher):
        """Test client cleanup."""
        with patch.object(fetcher.client, "aclose", new_callable=AsyncMock) as mock_close:
            await fetcher.close()
            mock_close.assert_called_once()


class TestNewsDataCategoryMapping:
    """Tests for NewsData.io category to NTRL mapping."""

    def test_direct_mappings(self):
        """Test direct category mappings exist."""
        assert NEWSDATA_CATEGORY_MAP["business"] == "business"
        assert NEWSDATA_CATEGORY_MAP["technology"] == "technology"
        assert NEWSDATA_CATEGORY_MAP["sports"] == "sports"
        assert NEWSDATA_CATEGORY_MAP["health"] == "health"
        assert NEWSDATA_CATEGORY_MAP["science"] == "science"

    def test_world_mappings(self):
        """Test world category mappings."""
        assert NEWSDATA_CATEGORY_MAP["world"] == "world"
        assert NEWSDATA_CATEGORY_MAP["top"] == "world"

    def test_culture_mappings(self):
        """Test culture category mappings."""
        assert NEWSDATA_CATEGORY_MAP["entertainment"] == "culture"
        assert NEWSDATA_CATEGORY_MAP["food"] == "culture"
        assert NEWSDATA_CATEGORY_MAP["tourism"] == "culture"

    def test_environment_mapping(self):
        """Test environment category mapping."""
        assert NEWSDATA_CATEGORY_MAP["environment"] == "environment"
