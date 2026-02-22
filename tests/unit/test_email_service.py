"""
Unit tests for EmailService.

Tests email sending, subject line generation, HTML rendering,
chart URL generation, and email data building logic.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest


class TestEmailServiceSendGuards:
    """Tests for early-exit guards in send_evaluation_results."""

    @pytest.fixture
    def mock_settings(self):
        """Create a mock settings object with email enabled."""
        settings = MagicMock()
        settings.EMAIL_ENABLED = True
        settings.RESEND_API_KEY = "re_test_key"
        settings.EMAIL_RECIPIENT = "test@ntrl.news"
        settings.EMAIL_FROM = "NTRL <noreply@ntrl.news>"
        return settings

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return MagicMock()

    def test_email_disabled(self, mock_settings, mock_db):
        """When EMAIL_ENABLED is False, returns skipped with reason."""
        mock_settings.EMAIL_ENABLED = False

        with patch("app.services.email_service.get_settings", return_value=mock_settings):
            from app.services.email_service import EmailService

            service = EmailService()
            result = service.send_evaluation_results(mock_db, "some-run-id")

        assert result["status"] == "skipped"
        assert result["reason"] == "EMAIL_ENABLED=false"

    def test_no_resend_key(self, mock_settings, mock_db):
        """When RESEND_API_KEY is None, returns skipped with reason."""
        mock_settings.RESEND_API_KEY = None

        with patch("app.services.email_service.get_settings", return_value=mock_settings):
            from app.services.email_service import EmailService

            service = EmailService()
            result = service.send_evaluation_results(mock_db, "some-run-id")

        assert result["status"] == "skipped"
        assert result["reason"] == "RESEND_API_KEY not set"

    def test_build_email_data_not_found(self, mock_settings, mock_db):
        """When eval run not found, _build_email_data returns None and send returns failed."""
        with patch("app.services.email_service.get_settings", return_value=mock_settings):
            from app.services.email_service import EmailService

            service = EmailService()

            with patch.object(service, "_build_email_data", return_value=None):
                result = service.send_evaluation_results(mock_db, "nonexistent-run-id")

        assert result["status"] == "failed"
        assert "error" in result


class TestEmailServiceSend:
    """Tests for the email send flow."""

    @pytest.fixture
    def mock_settings(self):
        """Create a mock settings object with email enabled."""
        settings = MagicMock()
        settings.EMAIL_ENABLED = True
        settings.RESEND_API_KEY = "re_test_key"
        settings.EMAIL_RECIPIENT = "test@ntrl.news"
        settings.EMAIL_FROM = "NTRL <noreply@ntrl.news>"
        return settings

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return MagicMock()

    @pytest.fixture
    def sample_email_data(self):
        """Sample email data dict as returned by _build_email_data."""
        return {
            "evaluation_run_id": "abc12345-1234-1234-1234-123456789012",
            "finished_at": datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC),
            "overall_quality_score": 7.8,
            "quality_delta": 0.3,
            "classification_accuracy": 0.86,
            "classification_delta": 0.02,
            "avg_neutralization_score": 8.1,
            "neutralization_delta": -0.1,
            "avg_span_precision": 0.72,
            "precision_delta": 0.05,
            "avg_span_recall": 0.65,
            "recall_delta": -0.03,
            "estimated_cost_usd": 1.37,
            "trend_data": {
                "labels": ["02/19 08:00", "02/19 12:00", "02/20 08:00"],
                "quality_scores": [7.5, 7.6, 7.8],
                "classification_accuracy": [84, 85, 86],
                "neutralization_scores": [8.0, 8.2, 8.1],
            },
            "prompt_changes": [],
            "action_items": [],
            "missed_by_category": {},
        }

    def test_send_success(self, mock_settings, mock_db, sample_email_data):
        """Successful send returns status sent with message_id."""
        with patch("app.services.email_service.get_settings", return_value=mock_settings):
            from app.services.email_service import EmailService

            service = EmailService()

            mock_resend = MagicMock()
            mock_resend.Emails.send.return_value = {"id": "msg_123"}
            service._resend_client = mock_resend

            with (
                patch.object(service, "_build_email_data", return_value=sample_email_data),
                patch.object(service, "_render_email_html", return_value="<html>test</html>"),
            ):
                result = service.send_evaluation_results(mock_db, "test-run-id")

        assert result["status"] == "sent"
        assert result["message_id"] == "msg_123"

    def test_send_failure(self, mock_settings, mock_db, sample_email_data):
        """When resend raises an exception, returns failed with error."""
        with patch("app.services.email_service.get_settings", return_value=mock_settings):
            from app.services.email_service import EmailService

            service = EmailService()

            mock_resend = MagicMock()
            mock_resend.Emails.send.side_effect = Exception("API rate limit exceeded")
            service._resend_client = mock_resend

            with (
                patch.object(service, "_build_email_data", return_value=sample_email_data),
                patch.object(service, "_render_email_html", return_value="<html>test</html>"),
            ):
                result = service.send_evaluation_results(mock_db, "test-run-id")

        assert result["status"] == "failed"
        assert "API rate limit exceeded" in result["error"]


class TestEmailServiceSubjectLine:
    """Tests for email subject line generation based on quality delta."""

    @pytest.fixture
    def mock_settings(self):
        """Create a mock settings object with email enabled."""
        settings = MagicMock()
        settings.EMAIL_ENABLED = True
        settings.RESEND_API_KEY = "re_test_key"
        settings.EMAIL_RECIPIENT = "test@ntrl.news"
        settings.EMAIL_FROM = "NTRL <noreply@ntrl.news>"
        return settings

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return MagicMock()

    def _make_email_data(self, quality_delta, quality_score=7.8):
        """Helper to create email data with a specific quality delta."""
        return {
            "evaluation_run_id": "abc12345",
            "finished_at": datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC),
            "overall_quality_score": quality_score,
            "quality_delta": quality_delta,
            "classification_accuracy": 0.86,
            "classification_delta": None,
            "avg_neutralization_score": 8.0,
            "neutralization_delta": None,
            "avg_span_precision": 0.70,
            "precision_delta": None,
            "avg_span_recall": 0.60,
            "recall_delta": None,
            "estimated_cost_usd": 1.0,
            "trend_data": {
                "labels": [],
                "quality_scores": [],
                "classification_accuracy": [],
                "neutralization_scores": [],
            },
            "prompt_changes": [],
            "action_items": [],
            "missed_by_category": {},
        }

    def test_subject_improved(self, mock_settings, mock_db):
        """When quality_delta > 0, subject contains 'improved'."""
        with patch("app.services.email_service.get_settings", return_value=mock_settings):
            from app.services.email_service import EmailService

            service = EmailService()

            mock_resend = MagicMock()
            mock_resend.Emails.send.return_value = {"id": "msg_456"}
            service._resend_client = mock_resend

            email_data = self._make_email_data(quality_delta=0.5)

            with (
                patch.object(service, "_build_email_data", return_value=email_data),
                patch.object(service, "_render_email_html", return_value="<html></html>"),
            ):
                service.send_evaluation_results(mock_db, "run-id")

            call_args = mock_resend.Emails.send.call_args[0][0]
            assert "improved" in call_args["subject"].lower()

    def test_subject_declined(self, mock_settings, mock_db):
        """When quality_delta < 0, subject contains 'declined'."""
        with patch("app.services.email_service.get_settings", return_value=mock_settings):
            from app.services.email_service import EmailService

            service = EmailService()

            mock_resend = MagicMock()
            mock_resend.Emails.send.return_value = {"id": "msg_789"}
            service._resend_client = mock_resend

            email_data = self._make_email_data(quality_delta=-0.3)

            with (
                patch.object(service, "_build_email_data", return_value=email_data),
                patch.object(service, "_render_email_html", return_value="<html></html>"),
            ):
                service.send_evaluation_results(mock_db, "run-id")

            call_args = mock_resend.Emails.send.call_args[0][0]
            assert "declined" in call_args["subject"].lower()

    def test_subject_neutral(self, mock_settings, mock_db):
        """When quality_delta is None, subject contains 'complete' (not improved/declined)."""
        with patch("app.services.email_service.get_settings", return_value=mock_settings):
            from app.services.email_service import EmailService

            service = EmailService()

            mock_resend = MagicMock()
            mock_resend.Emails.send.return_value = {"id": "msg_000"}
            service._resend_client = mock_resend

            email_data = self._make_email_data(quality_delta=None)

            with (
                patch.object(service, "_build_email_data", return_value=email_data),
                patch.object(service, "_render_email_html", return_value="<html></html>"),
            ):
                service.send_evaluation_results(mock_db, "run-id")

            call_args = mock_resend.Emails.send.call_args[0][0]
            assert "complete" in call_args["subject"].lower()
            assert "improved" not in call_args["subject"].lower()
            assert "declined" not in call_args["subject"].lower()


class TestEmailServiceRendering:
    """Tests for HTML rendering and chart URL generation."""

    @pytest.fixture
    def service(self):
        """Create an EmailService instance with mocked settings."""
        with patch("app.services.email_service.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.RESEND_API_KEY = "re_test_key"
            mock_get_settings.return_value = mock_settings

            from app.services.email_service import EmailService

            return EmailService()

    def test_render_email_html(self, service):
        """Rendered HTML contains score, run_id, and chart image."""
        data = {
            "evaluation_run_id": "abc12345-dead-beef-cafe-123456789012",
            "finished_at": datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC),
            "overall_quality_score": 7.8,
            "quality_delta": 0.3,
            "classification_accuracy": 0.86,
            "classification_delta": 0.02,
            "avg_neutralization_score": 8.1,
            "neutralization_delta": -0.1,
            "avg_span_precision": 0.72,
            "precision_delta": 0.05,
            "avg_span_recall": 0.65,
            "recall_delta": -0.03,
            "estimated_cost_usd": 1.37,
            "trend_data": {
                "labels": ["02/19 08:00"],
                "quality_scores": [7.8],
                "classification_accuracy": [86],
                "neutralization_scores": [8.1],
            },
            "prompt_changes": [],
            "action_items": [],
            "missed_by_category": {},
        }

        html = service._render_email_html(data)

        assert "7.8" in html
        assert "abc12345" in html
        assert "quickchart.io" in html
        assert "<img" in html

    def test_generate_trend_chart_url(self, service):
        """Trend chart URL points to quickchart.io with encoded config."""
        trend_data = {
            "labels": ["02/19", "02/20"],
            "quality_scores": [7.5, 7.8],
            "neutralization_scores": [8.0, 8.1],
        }

        url = service._generate_trend_chart_url(trend_data)

        assert url.startswith("https://quickchart.io/chart?c=")
        assert "w=600" in url
        assert "h=300" in url


class TestEmailServiceBuildData:
    """Tests for _build_email_data with database mocks."""

    @pytest.fixture
    def mock_settings(self):
        """Create a mock settings object."""
        settings = MagicMock()
        settings.RESEND_API_KEY = "re_test_key"
        return settings

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return MagicMock()

    def test_build_email_data_with_deltas(self, mock_settings, mock_db):
        """When previous run exists, deltas are calculated correctly."""
        with patch("app.services.email_service.get_settings", return_value=mock_settings):
            from app.services.email_service import EmailService

            service = EmailService()

        import uuid as uuid_module

        run_id = uuid_module.uuid4()
        prev_id = uuid_module.uuid4()

        # Current run
        current_run = MagicMock()
        current_run.id = run_id
        current_run.overall_quality_score = 8.0
        current_run.classification_accuracy = 0.90
        current_run.avg_neutralization_score = 8.5
        current_run.avg_span_precision = 0.75
        current_run.avg_span_recall = 0.70
        current_run.estimated_cost_usd = 1.50
        current_run.finished_at = datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC)
        current_run.prompts_updated = None
        current_run.article_evaluations = None

        # Previous run
        prev_run = MagicMock()
        prev_run.id = prev_id
        prev_run.status = "completed"
        prev_run.overall_quality_score = 7.5
        prev_run.classification_accuracy = 0.85
        prev_run.avg_neutralization_score = 8.0
        prev_run.avg_span_precision = 0.70
        prev_run.avg_span_recall = 0.65
        prev_run.finished_at = datetime(2026, 2, 19, 12, 0, 0, tzinfo=UTC)

        # Mock DB queries
        mock_db.query.return_value.filter.return_value.first.return_value = current_run
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            current_run,
            prev_run,
        ]

        result = service._build_email_data(mock_db, str(run_id))

        assert result is not None
        assert result["overall_quality_score"] == 8.0
        assert result["quality_delta"] == 0.5
        assert result["classification_delta"] == 0.05
        assert result["neutralization_delta"] == 0.5
        assert result["precision_delta"] == 0.05
        assert result["recall_delta"] == 0.05

    def test_build_email_data_action_items(self, mock_settings, mock_db):
        """Action items are generated for low neutralization scores and span recall."""
        with patch("app.services.email_service.get_settings", return_value=mock_settings):
            from app.services.email_service import EmailService

            service = EmailService()

        import uuid as uuid_module

        run_id = uuid_module.uuid4()

        # Article evaluation with low neutralization score
        low_eval = MagicMock()
        low_eval.neutralization_score = 5.5
        low_eval.missed_manipulations = [{"category": "clickbait"}]

        good_eval = MagicMock()
        good_eval.neutralization_score = 8.5
        good_eval.missed_manipulations = None

        # Current run with low span recall
        current_run = MagicMock()
        current_run.id = run_id
        current_run.overall_quality_score = 6.5
        current_run.classification_accuracy = 0.80
        current_run.avg_neutralization_score = 7.0
        current_run.avg_span_precision = 0.60
        current_run.avg_span_recall = 0.55
        current_run.estimated_cost_usd = 1.20
        current_run.finished_at = datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC)
        current_run.prompts_updated = None
        current_run.article_evaluations = [low_eval, good_eval]

        # No previous run
        mock_db.query.return_value.filter.return_value.first.return_value = current_run
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            current_run,
        ]

        result = service._build_email_data(mock_db, str(run_id))

        assert result is not None
        assert len(result["action_items"]) >= 2

        categories = [item["category"] for item in result["action_items"]]
        assert "NEUTRALIZATION" in categories
        assert "SPAN_RECALL" in categories

        assert result["missed_by_category"]["clickbait"] == 1
