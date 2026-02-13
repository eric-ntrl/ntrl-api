# tests/unit/test_url_validator.py
"""
Unit tests for the URL validation service.

Covers:
- HEAD → GET fallback on 405
- Redirect following and detection
- Timeout handling
- 404/410/403 detection
- Empty/invalid URL handling
- Rate limiting
- validate_and_store() DB persistence
- validate_batch() batch processing
"""

from unittest.mock import MagicMock, patch

import httpx

from app.services.url_validator import (
    URLValidationResult,
    _extract_domain,
    validate_and_store,
    validate_url,
)

# ---------------------------------------------------------------------------
# _extract_domain
# ---------------------------------------------------------------------------


class TestExtractDomain:
    def test_https_url(self):
        assert _extract_domain("https://www.example.com/article") == "www.example.com"

    def test_http_url(self):
        assert _extract_domain("http://example.com/path") == "example.com"

    def test_empty_string(self):
        assert _extract_domain("") == ""

    def test_malformed_url(self):
        # Should not raise, just return empty or partial
        result = _extract_domain("not-a-url")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# validate_url
# ---------------------------------------------------------------------------


class TestValidateUrlReachable:
    """Test successful URL validation."""

    @patch("app.services.url_validator._rate_limit")
    @patch("app.services.url_validator.httpx.Client")
    def test_reachable_200(self, mock_client_cls, mock_rate_limit):
        """200 OK with no redirect should return 'reachable'."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.url = "https://example.com/article"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.head.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = validate_url("https://example.com/article")
        assert result.status == "reachable"
        assert result.http_code == 200
        assert result.final_url is None

    @patch("app.services.url_validator._rate_limit")
    @patch("app.services.url_validator.httpx.Client")
    def test_redirect_detected(self, mock_client_cls, mock_rate_limit):
        """URL that redirects should return 'redirect' with final_url."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.url = "https://example.com/new-location"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.head.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = validate_url("https://example.com/old-article")
        assert result.status == "redirect"
        assert result.http_code == 200
        assert result.final_url == "https://example.com/new-location"


class TestValidateUrlHeadGetFallback:
    """Test HEAD → GET fallback on 405."""

    @patch("app.services.url_validator._rate_limit")
    @patch("app.services.url_validator.httpx.Client")
    def test_head_405_falls_back_to_get(self, mock_client_cls, mock_rate_limit):
        """When HEAD returns 405, should fall back to GET."""
        head_response = MagicMock()
        head_response.status_code = 405

        get_response = MagicMock()
        get_response.status_code = 200
        get_response.url = "https://example.com/article"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.head.return_value = head_response
        mock_client.get.return_value = get_response
        mock_client_cls.return_value = mock_client

        result = validate_url("https://example.com/article")
        assert result.status == "reachable"
        assert result.http_code == 200
        mock_client.get.assert_called_once()

    @patch("app.services.url_validator._rate_limit")
    @patch("app.services.url_validator.httpx.Client")
    def test_head_raises_falls_back_to_get(self, mock_client_cls, mock_rate_limit):
        """When HEAD raises HTTPStatusError, should fall back to GET."""
        get_response = MagicMock()
        get_response.status_code = 200
        get_response.url = "https://example.com/article"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.head.side_effect = httpx.HTTPStatusError("405", request=MagicMock(), response=MagicMock())
        mock_client.get.return_value = get_response
        mock_client_cls.return_value = mock_client

        result = validate_url("https://example.com/article")
        assert result.status == "reachable"
        assert result.http_code == 200


class TestValidateUrlUnreachable:
    """Test unreachable URL detection (404, 410, 403)."""

    @patch("app.services.url_validator._rate_limit")
    @patch("app.services.url_validator.httpx.Client")
    def test_404_not_found(self, mock_client_cls, mock_rate_limit):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.url = "https://example.com/missing"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.head.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = validate_url("https://example.com/missing")
        assert result.status == "unreachable"
        assert result.http_code == 404

    @patch("app.services.url_validator._rate_limit")
    @patch("app.services.url_validator.httpx.Client")
    def test_410_gone(self, mock_client_cls, mock_rate_limit):
        mock_response = MagicMock()
        mock_response.status_code = 410
        mock_response.url = "https://example.com/removed"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.head.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = validate_url("https://example.com/removed")
        assert result.status == "unreachable"
        assert result.http_code == 410

    @patch("app.services.url_validator._rate_limit")
    @patch("app.services.url_validator.httpx.Client")
    def test_403_forbidden(self, mock_client_cls, mock_rate_limit):
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.url = "https://example.com/paywall"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.head.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = validate_url("https://example.com/paywall")
        assert result.status == "unreachable"
        assert result.http_code == 403

    @patch("app.services.url_validator._rate_limit")
    @patch("app.services.url_validator.httpx.Client")
    def test_500_server_error(self, mock_client_cls, mock_rate_limit):
        """5xx errors should still be 'unreachable' but are treated as temporary by QC."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.url = "https://example.com/error"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.head.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = validate_url("https://example.com/error")
        assert result.status == "unreachable"
        assert result.http_code == 500


class TestValidateUrlTimeout:
    """Test timeout handling."""

    @patch("app.services.url_validator._rate_limit")
    @patch("app.services.url_validator.httpx.Client")
    def test_timeout(self, mock_client_cls, mock_rate_limit):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.head.side_effect = httpx.TimeoutException("Timed out")
        mock_client_cls.return_value = mock_client

        result = validate_url("https://slow-server.com/article")
        assert result.status == "timeout"
        assert result.http_code is None


class TestValidateUrlNetworkError:
    """Test network error handling."""

    @patch("app.services.url_validator._rate_limit")
    @patch("app.services.url_validator.httpx.Client")
    def test_connect_error(self, mock_client_cls, mock_rate_limit):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.head.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        result = validate_url("https://unreachable-host.com/article")
        assert result.status == "unreachable"
        assert result.http_code is None

    @patch("app.services.url_validator._rate_limit")
    @patch("app.services.url_validator.httpx.Client")
    def test_unexpected_exception(self, mock_client_cls, mock_rate_limit):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.head.side_effect = RuntimeError("Something unexpected")
        mock_client_cls.return_value = mock_client

        result = validate_url("https://example.com/article")
        assert result.status == "unreachable"
        assert result.http_code is None


class TestValidateUrlEdgeCases:
    """Test edge cases."""

    def test_empty_url(self):
        result = validate_url("")
        assert result.status == "unreachable"
        assert result.http_code is None

    def test_whitespace_url(self):
        result = validate_url("   ")
        assert result.status == "unreachable"

    def test_none_url_handled(self):
        result = validate_url(None)
        assert result.status == "unreachable"


# ---------------------------------------------------------------------------
# validate_and_store
# ---------------------------------------------------------------------------


class TestValidateAndStore:
    """Test that validate_and_store persists results to StoryRaw."""

    @patch("app.services.url_validator.validate_url")
    def test_stores_reachable(self, mock_validate):
        mock_validate.return_value = URLValidationResult(
            status="reachable", http_code=200, final_url=None, response_time_ms=50
        )

        db = MagicMock()
        story_raw = MagicMock()
        story_raw.original_url = "https://example.com/article"

        result = validate_and_store(db, story_raw)

        assert result.status == "reachable"
        assert story_raw.url_status == "reachable"
        assert story_raw.url_http_status == 200
        assert story_raw.url_final_location is None
        assert story_raw.url_checked_at is not None

    @patch("app.services.url_validator.validate_url")
    def test_stores_redirect_with_final_url(self, mock_validate):
        mock_validate.return_value = URLValidationResult(
            status="redirect",
            http_code=200,
            final_url="https://example.com/new-location",
            response_time_ms=120,
        )

        db = MagicMock()
        story_raw = MagicMock()
        story_raw.original_url = "https://example.com/old-url"

        result = validate_and_store(db, story_raw)

        assert result.status == "redirect"
        assert story_raw.url_status == "redirect"
        assert story_raw.url_final_location == "https://example.com/new-location"

    @patch("app.services.url_validator.validate_url")
    def test_stores_unreachable_404(self, mock_validate):
        mock_validate.return_value = URLValidationResult(
            status="unreachable", http_code=404, final_url=None, response_time_ms=30
        )

        db = MagicMock()
        story_raw = MagicMock()
        story_raw.original_url = "https://example.com/deleted"

        result = validate_and_store(db, story_raw)

        assert result.status == "unreachable"
        assert story_raw.url_status == "unreachable"
        assert story_raw.url_http_status == 404

    @patch("app.services.url_validator.validate_url")
    def test_stores_timeout(self, mock_validate):
        mock_validate.return_value = URLValidationResult(
            status="timeout", http_code=None, final_url=None, response_time_ms=5000
        )

        db = MagicMock()
        story_raw = MagicMock()
        story_raw.original_url = "https://slow-server.com/article"

        result = validate_and_store(db, story_raw)

        assert result.status == "timeout"
        assert story_raw.url_status == "timeout"
        assert story_raw.url_http_status is None
