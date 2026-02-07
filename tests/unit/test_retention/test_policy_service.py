# tests/unit/test_retention/test_policy_service.py
"""Unit tests for retention policy service."""

from unittest.mock import MagicMock, patch

import pytest


class TestGetActivePolicy:
    """Tests for get_active_policy()."""

    def test_returns_active_policy(self):
        """Should return the currently active policy."""
        from app.models import RetentionPolicy
        from app.services.retention.policy_service import get_active_policy

        # Create mock policy
        mock_policy = MagicMock(spec=RetentionPolicy)
        mock_policy.name = "production"
        mock_policy.is_active = True

        # Create mock query
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_policy

        result = get_active_policy(mock_db)

        assert result == mock_policy
        mock_db.query.assert_called_once()

    def test_returns_none_when_no_active_policy(self):
        """Should return None when no policy is active."""
        from app.services.retention.policy_service import get_active_policy

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = get_active_policy(mock_db)

        assert result is None


class TestSetPolicy:
    """Tests for set_policy()."""

    def test_activates_named_policy(self):
        """Should deactivate all policies and activate the named one."""
        from app.models import RetentionPolicy
        from app.services.retention.policy_service import set_policy

        mock_policy = MagicMock(spec=RetentionPolicy)
        mock_policy.name = "production"
        mock_policy.is_active = False

        mock_db = MagicMock()
        # get_policy_by_name query
        mock_db.query.return_value.filter.return_value.first.return_value = mock_policy

        result = set_policy(mock_db, "production")

        assert mock_policy.is_active == True
        mock_db.commit.assert_called_once()

    def test_raises_error_for_unknown_policy(self):
        """Should raise ValueError for unknown policy name."""
        from app.services.retention.policy_service import set_policy

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(ValueError, match="not found"):
            set_policy(mock_db, "nonexistent")


class TestCreatePolicy:
    """Tests for create_policy()."""

    def test_creates_new_policy(self):
        """Should create a new policy with given parameters."""
        from app.services.retention.policy_service import create_policy

        mock_db = MagicMock()
        # get_policy_by_name returns None (doesn't exist)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = create_policy(
            mock_db,
            name="custom",
            active_days=14,
            compliance_days=180,
            auto_archive=True,
            hard_delete_mode=False,
            activate=False,
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_raises_error_if_policy_exists(self):
        """Should raise ValueError if policy already exists."""
        from app.models import RetentionPolicy
        from app.services.retention.policy_service import create_policy

        mock_policy = MagicMock(spec=RetentionPolicy)
        mock_policy.name = "custom"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_policy

        with pytest.raises(ValueError, match="already exists"):
            create_policy(mock_db, name="custom")


class TestEnsureDefaultPolicies:
    """Tests for ensure_default_policies()."""

    @patch.dict("os.environ", {"ENVIRONMENT": "development"})
    def test_creates_default_policies_if_missing(self):
        """Should create development and production policies if they don't exist."""
        from app.services.retention.policy_service import ensure_default_policies

        mock_db = MagicMock()
        # First two calls for get_policy_by_name (dev, prod) return None
        # Then get_active_policy returns None
        # Then set_policy works
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            None,  # development doesn't exist
            None,  # production doesn't exist
            None,  # no active policy
            MagicMock(name="development", is_active=False),  # set_policy lookup
        ]

        with patch("app.services.retention.policy_service.create_policy") as mock_create:
            with patch("app.services.retention.policy_service.set_policy") as mock_set:
                mock_set.return_value = MagicMock(name="development")
                result = ensure_default_policies(mock_db)

        # Should have tried to create both default policies
        assert mock_create.call_count == 2

    @patch.dict("os.environ", {"ENVIRONMENT": "production"})
    def test_activates_production_in_production_env(self):
        """Should activate production policy when ENVIRONMENT=production."""
        from app.services.retention.policy_service import ensure_default_policies

        mock_policy = MagicMock(name="production")

        mock_db = MagicMock()
        # Policies exist, no active policy
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            MagicMock(name="development"),  # development exists
            MagicMock(name="production"),  # production exists
            None,  # no active policy
            mock_policy,  # set_policy lookup
        ]

        with patch("app.services.retention.policy_service.set_policy") as mock_set:
            mock_set.return_value = mock_policy
            result = ensure_default_policies(mock_db)

        mock_set.assert_called_with(mock_db, "production")


class TestRetentionConfig:
    """Tests for get_retention_config()."""

    def test_returns_default_config_when_no_policy(self):
        """Should return default config when no active policy."""
        from app.services.retention.policy_service import get_retention_config

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = get_retention_config(mock_db)

        assert result["active_policy"] is None
        assert result["active_days"] == 7
        assert result["compliance_days"] == 365

    def test_returns_policy_config(self):
        """Should return active policy configuration."""
        from app.models import RetentionPolicy
        from app.services.retention.policy_service import get_retention_config

        mock_policy = MagicMock(spec=RetentionPolicy)
        mock_policy.name = "production"
        mock_policy.active_days = 7
        mock_policy.compliance_days = 365
        mock_policy.auto_archive = True
        mock_policy.hard_delete_mode = False

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_policy

        result = get_retention_config(mock_db)

        assert result["active_policy"] == "production"
        assert result["active_days"] == 7
        assert result["compliance_days"] == 365
        assert result["auto_archive"] == True
        assert result["hard_delete_mode"] == False
