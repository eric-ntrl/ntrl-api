# tests/test_classifier.py
"""
Unit tests for section classification.
"""

from app.models import Section
from app.services.classifier import SectionClassifier


class TestSectionClassifier:
    """Tests for the SectionClassifier service."""

    def setup_method(self):
        """Set up test fixtures."""
        self.classifier = SectionClassifier()

    def test_classify_world_news(self):
        """Test classification of world news."""
        # Explicit world keywords
        result = self.classifier.classify("China announces new trade deal with Europe")
        assert result == Section.WORLD

        result = self.classifier.classify("United Nations summit addresses climate change")
        assert result == Section.WORLD

        result = self.classifier.classify("Russia-Ukraine conflict continues")
        assert result == Section.WORLD

    def test_classify_us_news(self):
        """Test classification of US news."""
        result = self.classifier.classify("Congress passes new infrastructure bill")
        assert result == Section.US

        result = self.classifier.classify("Supreme Court rules on voting rights case")
        assert result == Section.US

        result = self.classifier.classify("White House announces new policy")
        assert result == Section.US

    def test_classify_business_news(self):
        """Test classification of business news."""
        result = self.classifier.classify("Stock market reaches new high")
        assert result == Section.BUSINESS

        result = self.classifier.classify("Federal Reserve raises interest rates")
        assert result == Section.BUSINESS

        result = self.classifier.classify("Tech company announces IPO")
        assert result == Section.BUSINESS

    def test_classify_technology_news(self):
        """Test classification of technology news."""
        result = self.classifier.classify("Apple announces new iPhone features")
        assert result == Section.TECHNOLOGY

        result = self.classifier.classify("OpenAI releases new AI model")
        assert result == Section.TECHNOLOGY

        result = self.classifier.classify("Major data breach affects millions")
        assert result == Section.TECHNOLOGY

    def test_classify_with_source_hint(self):
        """Test that source hints override keywords."""
        # Source hint should take precedence
        result = self.classifier.classify("Generic headline without keywords", source_slug="ap-technology")
        assert result == Section.TECHNOLOGY

        result = self.classifier.classify("Generic headline without keywords", source_slug="ap-business")
        assert result == Section.BUSINESS

    def test_classify_ambiguous_defaults_to_world(self):
        """Test that ambiguous content defaults to WORLD."""
        result = self.classifier.classify("Something happened somewhere")
        assert result == Section.WORLD

    def test_classify_batch(self):
        """Test batch classification."""
        stories = [
            {"title": "Congress votes on new bill"},
            {"title": "Apple releases new product"},
            {"title": "UN addresses global issue"},
        ]

        results = self.classifier.classify_batch(stories)

        assert results[0] == Section.US
        assert results[1] == Section.TECHNOLOGY
        assert results[2] == Section.WORLD
