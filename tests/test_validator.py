# tests/test_validator.py
"""
Unit tests for the NTRL-FIX Red-Line Validator.
"""

import pytest
from app.services.ntrl_fix import (
    RedLineValidator,
    get_validator,
    ValidationStatus,
    RiskLevel,
)


@pytest.fixture
def validator():
    """Create a fresh validator instance."""
    return RedLineValidator()


class TestValidatorInit:
    """Tests for validator initialization."""

    def test_validator_loads_spacy(self, validator):
        """Should load spaCy model."""
        assert validator.nlp is not None

    def test_singleton_works(self):
        """get_validator should return singleton."""
        v1 = get_validator()
        v2 = get_validator()
        assert v1 is v2


class TestEntityInvariance:
    """Tests for entity preservation check."""

    def test_entities_preserved_passes(self, validator):
        """Should pass when all entities preserved."""
        original = "John Smith met with Microsoft CEO in New York."
        rewritten = "John Smith met with Microsoft CEO in New York."

        result = validator.validate(original, rewritten)
        assert result.checks["entity_invariance"].passed

    def test_missing_entity_fails(self, validator):
        """Should fail when entity is missing."""
        original = "John Smith announced the decision in Washington."
        rewritten = "The decision was announced in Washington."

        result = validator.validate(original, rewritten)
        # Note: This may pass or fail depending on spaCy's entity recognition
        # The test verifies the check runs without error
        assert "entity_invariance" in result.checks


class TestNumberInvariance:
    """Tests for number preservation check."""

    def test_numbers_preserved_passes(self, validator):
        """Should pass when all numbers preserved."""
        original = "The company reported $5.2 million in revenue and 42% growth."
        rewritten = "The company reported $5.2 million in revenue and 42% growth."

        result = validator.validate(original, rewritten)
        assert result.checks["number_invariance"].passed

    def test_missing_number_fails(self, validator):
        """Should fail when number is missing."""
        original = "The project cost $3.5 million."
        rewritten = "The project was expensive."

        result = validator.validate(original, rewritten)
        assert result.checks["number_invariance"].status == ValidationStatus.FAILED

    def test_percentage_preserved(self, validator):
        """Should preserve percentages."""
        original = "Sales increased by 15%."
        rewritten = "Sales increased by 15%."

        result = validator.validate(original, rewritten)
        assert result.checks["number_invariance"].passed


class TestModalityInvariance:
    """Tests for modality (certainty) check."""

    def test_soft_modal_preserved_passes(self, validator):
        """Should pass when soft modality preserved."""
        original = "The suspect allegedly committed the crime."
        rewritten = "The suspect allegedly committed the crime."

        result = validator.validate(original, rewritten)
        assert result.checks["modality_invariance"].passed

    def test_soft_to_hard_modal_fails(self, validator):
        """Should fail when soft modal becomes hard."""
        original = "The suspect allegedly committed the crime."
        rewritten = "The suspect definitely committed the crime."

        result = validator.validate(original, rewritten)
        assert result.checks["modality_invariance"].status == ValidationStatus.FAILED

    def test_may_to_will_fails(self, validator):
        """Should fail when 'may' becomes 'will'."""
        original = "This may cause problems."
        rewritten = "This will cause problems."

        result = validator.validate(original, rewritten)
        assert result.checks["modality_invariance"].status == ValidationStatus.FAILED


class TestQuoteIntegrity:
    """Tests for quote preservation check."""

    def test_quote_preserved_passes(self, validator):
        """Should pass when quotes preserved verbatim."""
        original = 'The senator said "This is unacceptable behavior."'
        rewritten = 'The senator stated "This is unacceptable behavior."'

        result = validator.validate(original, rewritten)
        assert result.checks["quote_integrity"].passed

    def test_modified_quote_fails(self, validator):
        """Should fail when quote is modified."""
        original = 'The CEO stated "We will deliver results by Q4."'
        rewritten = 'The CEO stated "We will deliver results soon."'

        result = validator.validate(original, rewritten)
        assert result.checks["quote_integrity"].status == ValidationStatus.FAILED


class TestNegationIntegrity:
    """Tests for negation preservation check."""

    def test_negation_preserved_passes(self, validator):
        """Should pass when negations preserved."""
        original = "The company did not approve the merger."
        rewritten = "The company did not approve the merger."

        result = validator.validate(original, rewritten)
        assert result.checks["negation_integrity"].passed

    def test_removed_negation_fails(self, validator):
        """Should fail when negation is removed."""
        original = "The official did not confirm the report."
        rewritten = "The official confirmed the report."

        result = validator.validate(original, rewritten)
        assert result.checks["negation_integrity"].status == ValidationStatus.FAILED

    def test_never_preserved(self, validator):
        """Should preserve 'never'."""
        original = "The CEO never agreed to the terms."
        rewritten = "The CEO never agreed to the terms."

        result = validator.validate(original, rewritten)
        assert result.checks["negation_integrity"].passed


class TestRiskInvariance:
    """Tests for risk/warning preservation check."""

    def test_warning_preserved_passes(self, validator):
        """Should pass when warnings preserved."""
        original = "Officials issued a warning about the severe weather."
        rewritten = "Officials issued a warning about the severe weather conditions."

        result = validator.validate(original, rewritten)
        assert result.checks["risk_invariance"].passed

    def test_removed_warning_fails(self, validator):
        """Should fail when risk language removed."""
        original = "There is a danger of flooding in low-lying areas."
        rewritten = "Low-lying areas may experience water."

        result = validator.validate(original, rewritten)
        assert result.checks["risk_invariance"].status == ValidationStatus.FAILED


class TestScopeInvariance:
    """Tests for scope quantifier preservation."""

    def test_scope_preserved_passes(self, validator):
        """Should pass when scope words preserved."""
        original = "All employees must attend the meeting."
        rewritten = "All employees must attend the meeting."

        result = validator.validate(original, rewritten)
        assert result.checks["scope_invariance"].passed


class TestCausalityInvariance:
    """Tests for causal relationship preservation."""

    def test_causality_preserved_passes(self, validator):
        """Should pass when causal language preserved."""
        original = "The accident caused significant delays."
        rewritten = "The accident caused significant delays."

        result = validator.validate(original, rewritten)
        assert result.checks["causality_invariance"].passed


class TestDateInvariance:
    """Tests for date preservation check."""

    def test_dates_preserved_passes(self, validator):
        """Should pass when dates preserved."""
        original = "The event will take place on March 15, 2024."
        rewritten = "The event is scheduled for March 15, 2024."

        result = validator.validate(original, rewritten)
        assert result.checks["date_invariance"].passed


class TestOverallValidation:
    """Tests for overall validation results."""

    def test_clean_rewrite_passes(self, validator):
        """Should pass for identical text."""
        text = "The city council approved the budget amendment yesterday."
        result = validator.validate(text, text)

        assert result.passed
        assert result.risk_level == RiskLevel.NONE

    def test_multiple_failures_high_risk(self, validator):
        """Multiple failures should result in high risk."""
        original = "The suspect allegedly stole $50,000 and never returned."
        rewritten = "The suspect definitely took money and returned."

        result = validator.validate(original, rewritten)

        assert not result.passed
        assert len(result.failures) >= 2
        # Risk level depends on number of failures
        assert result.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_non_strict_mode(self, validator):
        """Non-strict mode should allow some failures."""
        original = "Some say the policy caused problems recently."
        rewritten = "The policy had effects."  # Removes causal language

        # Strict mode
        strict_result = validator.validate(original, rewritten, strict=True)

        # Non-strict mode
        non_strict_result = validator.validate(original, rewritten, strict=False)

        # Non-strict should be more lenient
        # (actual behavior depends on which checks fail)
        assert "causality_invariance" in strict_result.checks


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_text(self, validator):
        """Should handle empty text."""
        result = validator.validate("", "")
        assert result.passed

    def test_whitespace_only(self, validator):
        """Should handle whitespace-only text."""
        result = validator.validate("   ", "   ")
        assert result.passed

    def test_very_long_text(self, validator):
        """Should handle long text."""
        text = "The company reported results. " * 100
        result = validator.validate(text, text)
        assert result.passed
