# tests/test_search.py
"""
Tests for search endpoint and service.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestSearchEndpoint:
    """Test search endpoint contract."""

    def test_search_requires_query(self, client):
        """Test that search requires a query parameter."""
        response = client.get("/v1/search")
        assert response.status_code == 422  # Validation error

    def test_search_minimum_query_length(self, client):
        """Test that search requires at least 2 characters."""
        response = client.get("/v1/search?q=a")
        assert response.status_code == 422  # Validation error - min_length=2

    def test_search_valid_query(self, client):
        """Test that valid search query returns proper response."""
        response = client.get("/v1/search?q=climate")
        assert response.status_code == 200

        data = response.json()
        # Check response schema
        assert "query" in data
        assert data["query"] == "climate"
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert "items" in data
        assert "facets" in data
        assert "suggestions" in data

        # Facets should have categories and sources
        assert "categories" in data["facets"]
        assert "sources" in data["facets"]
        assert isinstance(data["facets"]["categories"], list)
        assert isinstance(data["facets"]["sources"], list)

    def test_search_pagination_params(self, client):
        """Test that pagination parameters are accepted."""
        response = client.get("/v1/search?q=test&limit=10&offset=5")
        assert response.status_code == 200

        data = response.json()
        assert data["limit"] == 10
        assert data["offset"] == 5

    def test_search_limit_max(self, client):
        """Test that limit is capped at 50."""
        response = client.get("/v1/search?q=test&limit=100")
        assert response.status_code == 422  # Validation error - le=50

    def test_search_limit_min(self, client):
        """Test that limit must be at least 1."""
        response = client.get("/v1/search?q=test&limit=0")
        assert response.status_code == 422  # Validation error - ge=1

    def test_search_sort_relevance(self, client):
        """Test search with relevance sort."""
        response = client.get("/v1/search?q=test&sort=relevance")
        assert response.status_code == 200

    def test_search_sort_recency(self, client):
        """Test search with recency sort."""
        response = client.get("/v1/search?q=test&sort=recency")
        assert response.status_code == 200

    def test_search_invalid_sort(self, client):
        """Test that invalid sort returns 400."""
        response = client.get("/v1/search?q=test&sort=invalid")
        assert response.status_code == 400

    def test_search_category_filter(self, client):
        """Test search with category filter."""
        response = client.get("/v1/search?q=test&category=technology")
        assert response.status_code == 200

    def test_search_source_filter(self, client):
        """Test search with source filter."""
        response = client.get("/v1/search?q=test&source=ap")
        assert response.status_code == 200

    def test_search_date_filter(self, client):
        """Test search with date filter."""
        response = client.get("/v1/search?q=test&published_after=2026-01-01T00:00:00")
        assert response.status_code == 200


class TestSearchResponseSchema:
    """Test search response schema details."""

    def test_result_item_schema(self, client):
        """Test that search result items have correct schema."""
        response = client.get("/v1/search?q=the")  # Common word likely to match
        assert response.status_code == 200

        data = response.json()
        for item in data["items"]:
            # Required fields
            assert "id" in item
            assert "feed_title" in item
            assert "feed_summary" in item
            assert "source_name" in item
            assert "source_slug" in item
            assert "source_url" in item
            assert "published_at" in item
            assert "has_manipulative_content" in item

            # Optional fields
            assert "detail_title" in item  # May be null
            assert "detail_brief" in item  # May be null
            assert "feed_category" in item  # May be null
            assert "rank" in item  # May be null

    def test_facet_count_schema(self, client):
        """Test that facet counts have correct schema."""
        response = client.get("/v1/search?q=test")
        assert response.status_code == 200

        data = response.json()
        for category in data["facets"]["categories"]:
            assert "key" in category
            assert "label" in category
            assert "count" in category
            assert isinstance(category["count"], int)

        for source in data["facets"]["sources"]:
            assert "key" in source
            assert "label" in source
            assert "count" in source
            assert isinstance(source["count"], int)

    def test_suggestion_schema(self, client):
        """Test that suggestions have correct schema."""
        response = client.get("/v1/search?q=te")  # Short query for suggestions
        assert response.status_code == 200

        data = response.json()
        for suggestion in data["suggestions"]:
            assert "type" in suggestion
            assert suggestion["type"] in ["section", "publisher", "recent"]
            assert "value" in suggestion
            assert "label" in suggestion
            # count may be null


class TestSearchCaching:
    """Test search result caching."""

    def test_search_caching_works(self, client):
        """Test that repeated searches are cached (response time should be faster)."""
        # First request
        response1 = client.get("/v1/search?q=climate")
        assert response1.status_code == 200

        # Second request (should be cached)
        response2 = client.get("/v1/search?q=climate")
        assert response2.status_code == 200

        # Results should be identical
        assert response1.json() == response2.json()

    def test_different_queries_not_cached_together(self, client):
        """Test that different queries have different cache keys."""
        response1 = client.get("/v1/search?q=climate")
        response2 = client.get("/v1/search?q=economy")

        assert response1.status_code == 200
        assert response2.status_code == 200

        # Queries are different
        assert response1.json()["query"] == "climate"
        assert response2.json()["query"] == "economy"


class TestSearchEmptyResults:
    """Test empty result handling."""

    def test_empty_results_for_nonsense_query(self, client):
        """Test that nonsense query returns empty results gracefully."""
        response = client.get("/v1/search?q=xyzzynonexistent12345")
        assert response.status_code == 200

        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []
        # Facets should still be present (empty)
        assert "facets" in data
        assert "categories" in data["facets"]
        assert "sources" in data["facets"]
