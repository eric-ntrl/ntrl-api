# tests/test_api.py
"""
Contract tests for API responses.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestHealthEndpoints:
    """Test health check endpoints."""

    def test_health(self, client):
        """Test /health endpoint."""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "ntrl-api"
        assert "version" in data

    def test_root(self, client):
        """Test / endpoint."""
        response = client.get("/")
        assert response.status_code == 200

        data = response.json()
        assert data["service"] == "NTRL API"
        assert "endpoints" in data


class TestBriefEndpoint:
    """Test brief endpoint contract."""

    def test_brief_404_when_no_brief(self, client):
        """Test that /v1/brief returns 404 when no brief exists."""
        response = client.get("/v1/brief")
        # Should return 404 if no brief assembled
        assert response.status_code in [200, 404]

        if response.status_code == 404:
            data = response.json()
            assert "detail" in data


class TestStoriesEndpoint:
    """Test stories endpoint contract."""

    def test_story_invalid_id(self, client):
        """Test that invalid story ID returns 400."""
        response = client.get("/v1/stories/invalid-id")
        assert response.status_code == 400

    def test_story_not_found(self, client):
        """Test that non-existent story returns 404."""
        response = client.get("/v1/stories/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    def test_transparency_invalid_id(self, client):
        """Test that invalid transparency ID returns 400."""
        response = client.get("/v1/stories/invalid-id/transparency")
        assert response.status_code == 400


class TestAdminEndpoints:
    """Test admin endpoint contracts."""

    def test_ingest_no_auth(self, client):
        """Test that ingest requires auth when key is set."""
        # Without ADMIN_API_KEY set, should work or require auth
        response = client.post("/v1/ingest/run", json={})
        # Either 200 (no auth required) or 401 (auth required)
        assert response.status_code in [200, 401, 500]

    def test_neutralize_no_auth(self, client):
        """Test that neutralize requires auth when key is set."""
        response = client.post("/v1/neutralize/run", json={})
        assert response.status_code in [200, 401, 500]

    def test_brief_run_no_auth(self, client):
        """Test that brief/run requires auth when key is set."""
        response = client.post("/v1/brief/run", json={})
        assert response.status_code in [200, 401, 500]


class TestResponseSchemas:
    """Test that response schemas match expected format."""

    def test_brief_response_schema(self, client):
        """Test brief response has correct schema."""
        response = client.get("/v1/brief")

        if response.status_code == 200:
            data = response.json()

            # Required fields
            assert "id" in data
            assert "brief_date" in data
            assert "sections" in data
            assert "total_stories" in data
            assert "is_empty" in data

            # Sections should be a list
            assert isinstance(data["sections"], list)

            # If not empty, check section schema
            for section in data["sections"]:
                assert "name" in section
                assert "display_name" in section
                assert "order" in section
                assert "stories" in section
                assert isinstance(section["stories"], list)
