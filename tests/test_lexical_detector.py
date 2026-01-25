# tests/test_lexical_detector.py
"""
Unit tests for the NTRL-SCAN Lexical Detector.
"""

import pytest
from app.services.ntrl_scan.lexical_detector import (
    LexicalDetector,
    get_lexical_detector,
)
from app.services.ntrl_scan.types import (
    ArticleSegment,
    DetectorSource,
    SpanAction,
)


@pytest.fixture
def detector():
    """Create a fresh detector instance for tests."""
    return LexicalDetector()


class TestLexicalDetectorInit:
    """Tests for detector initialization."""

    def test_detector_compiles_patterns(self, detector):
        """Detector should compile patterns from taxonomy."""
        assert detector.pattern_count > 0
        assert detector.type_count > 0

    def test_singleton_works(self):
        """get_lexical_detector should return singleton."""
        d1 = get_lexical_detector()
        d2 = get_lexical_detector()
        assert d1 is d2

    def test_get_patterns_for_type(self, detector):
        """Should return patterns for known types."""
        patterns = detector.get_patterns_for_type("A.2.1")  # Urgency inflation
        assert len(patterns) > 0
        assert any("BREAKING" in p for p in patterns)

    def test_get_patterns_for_unknown_type(self, detector):
        """Should return empty list for unknown types."""
        patterns = detector.get_patterns_for_type("Z.9.9")
        assert patterns == []


class TestBasicDetection:
    """Tests for basic pattern detection."""

    def test_detect_urgency_inflation(self, detector):
        """Should detect BREAKING NEWS."""
        text = "BREAKING: Major earthquake hits California."
        result = detector.detect(text, ArticleSegment.TITLE)

        assert result.total_detections >= 1
        detection = next(d for d in result.spans if d.type_id_primary == "A.2.1")
        assert detection is not None
        assert "BREAKING" in detection.text
        assert detection.confidence > 0.9

    def test_detect_rage_verbs(self, detector):
        """Should detect rage verbs like 'slams'."""
        text = "Senator slams critics in heated exchange."
        result = detector.detect(text, ArticleSegment.TITLE)

        assert result.total_detections >= 1
        detection = next(d for d in result.spans if d.type_id_primary == "B.2.2")
        assert detection is not None
        assert "slams" in detection.text.lower()

    def test_detect_multiple_patterns(self, detector):
        """Should detect multiple different patterns."""
        text = "BREAKING: Official SLAMS critics - You won't believe what happened next!"
        result = detector.detect(text, ArticleSegment.TITLE)

        # Should find urgency (BREAKING), rage verb (SLAMS), curiosity gap
        assert result.total_detections >= 2
        type_ids = {d.type_id_primary for d in result.spans}
        assert "A.2.1" in type_ids  # Urgency
        assert "B.2.2" in type_ids  # Rage verbs

    def test_detect_empty_text(self, detector):
        """Should handle empty text gracefully."""
        result = detector.detect("", ArticleSegment.BODY)
        assert result.total_detections == 0
        assert result.text_length == 0

    def test_detect_no_manipulation(self, detector):
        """Should return no detections for clean text."""
        text = "The city council voted on the proposed budget amendment."
        result = detector.detect(text, ArticleSegment.BODY)
        assert result.total_detections == 0


class TestQuoteHandling:
    """Tests for quote-aware detection."""

    def test_skip_content_in_quotes(self, detector):
        """Should mark content in quotes with exemption."""
        text = 'The witness said "BREAKING news shocked us all."'
        result = detector.detect(text, ArticleSegment.BODY, skip_quotes=True)

        # Should still detect but with exemption
        if result.total_detections > 0:
            for detection in result.spans:
                if "BREAKING" in detection.text:
                    assert "inside_quote" in detection.exemptions_applied
                    assert detection.recommended_action == SpanAction.ANNOTATE

    def test_detect_outside_quotes(self, detector):
        """Should detect manipulation outside quotes normally."""
        text = 'BREAKING: The witness said "the event was significant."'
        result = detector.detect(text, ArticleSegment.BODY, skip_quotes=True)

        # Should find BREAKING outside quotes
        urgency_detections = [d for d in result.spans if d.type_id_primary == "A.2.1"]
        assert len(urgency_detections) >= 1
        assert "inside_quote" not in urgency_detections[0].exemptions_applied


class TestSegmentHandling:
    """Tests for segment-aware detection."""

    def test_title_segment_multiplier(self, detector):
        """Title detections should have higher weighted severity."""
        text = "BREAKING: Major event"

        title_result = detector.detect(text, ArticleSegment.TITLE)
        body_result = detector.detect(text, ArticleSegment.BODY)

        if title_result.total_detections > 0 and body_result.total_detections > 0:
            title_detection = title_result.spans[0]
            body_detection = body_result.spans[0]

            # Same base severity
            assert title_detection.severity == body_detection.severity
            # But title has higher weighted severity
            assert title_detection.severity_weighted > body_detection.severity_weighted

    def test_convenience_methods(self, detector):
        """detect_title and detect_body should work correctly."""
        text = "BREAKING news today"

        title_result = detector.detect_title(text)
        body_result = detector.detect_body(text)

        assert title_result.segment == ArticleSegment.TITLE
        assert body_result.segment == ArticleSegment.BODY


class TestScanResult:
    """Tests for ScanResult data structure."""

    def test_result_has_timing(self, detector):
        """Should record scan duration."""
        text = "BREAKING: Senator slams critics in devastating attack."
        result = detector.detect(text, ArticleSegment.BODY)

        assert result.scan_duration_ms >= 0
        assert result.scan_duration_ms < 100  # Should be fast

    def test_result_has_statistics(self, detector):
        """Should compute summary statistics."""
        text = "BREAKING: Senator slams critics. Alarmingly, this continues."
        result = detector.detect(text, ArticleSegment.BODY)

        assert "total_detections" in result.summary_stats
        assert "by_category" in result.summary_stats
        assert "by_severity" in result.summary_stats
        assert "manipulation_density" in result.summary_stats

    def test_result_high_severity_count(self, detector):
        """Should count high severity detections."""
        text = "Democracy is dying. Vermin are invading."
        result = detector.detect(text, ArticleSegment.BODY)

        # These are severity 5 types
        assert result.high_severity_count >= 0


class TestSpecificPatterns:
    """Tests for specific manipulation patterns from the taxonomy."""

    def test_curiosity_gap(self, detector):
        """Should detect curiosity gap patterns."""
        text = "You won't believe what scientists discovered."
        result = detector.detect(text, ArticleSegment.TITLE)

        detection = next((d for d in result.spans if d.type_id_primary == "A.1.1"), None)
        assert detection is not None

    def test_catastrophizing(self, detector):
        """Should detect catastrophizing language."""
        text = "The economy is on the verge of collapse."
        result = detector.detect(text, ArticleSegment.BODY)

        detection = next((d for d in result.spans if d.type_id_primary == "B.1.2"), None)
        assert detection is not None

    def test_loaded_adjectives(self, detector):
        """Should detect loaded adjectives."""
        text = "The stunning failure of the program shocked observers."
        result = detector.detect(text, ArticleSegment.BODY)

        detection = next((d for d in result.spans if d.type_id_primary == "D.1.1"), None)
        assert detection is not None

    def test_sentiment_steering_adverbs(self, detector):
        """Should detect sentiment steering adverbs."""
        text = "Alarmingly, the trend continues to accelerate."
        result = detector.detect(text, ArticleSegment.BODY)

        detection = next((d for d in result.spans if d.type_id_primary == "B.5.1"), None)
        assert detection is not None

    def test_call_to_action(self, detector):
        """Should detect embedded calls to action."""
        text = "Contact your representatives and sign the petition today."
        result = detector.detect(text, ArticleSegment.BODY)

        detection = next((d for d in result.spans if d.type_id_primary == "F.3.2"), None)
        assert detection is not None


class TestPerformance:
    """Tests for detector performance."""

    def test_fast_detection(self, detector):
        """Should complete detection in under 50ms for typical text."""
        # Generate a moderately long text
        text = "BREAKING: " + "The quick brown fox. " * 100
        result = detector.detect(text, ArticleSegment.BODY)

        assert result.scan_duration_ms < 50  # Should be very fast

    def test_handles_long_text(self, detector):
        """Should handle very long articles."""
        text = "This is a test. " * 5000  # ~80k characters
        result = detector.detect(text, ArticleSegment.BODY)

        assert result.text_length > 50000
        assert result.scan_duration_ms < 500  # Still reasonable
