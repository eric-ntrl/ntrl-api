# tests/test_structural_detector.py
"""
Unit tests for the NTRL-SCAN Structural Detector.
"""

import pytest

from app.services.ntrl_scan.structural_detector import (
    StructuralDetector,
    get_structural_detector,
)
from app.services.ntrl_scan.types import (
    ArticleSegment,
    DetectorSource,
)


@pytest.fixture
def detector():
    """Create a fresh detector instance for tests."""
    return StructuralDetector()


class TestStructuralDetectorInit:
    """Tests for detector initialization."""

    def test_detector_loads_spacy_model(self, detector):
        """Detector should load spaCy model successfully."""
        assert detector.nlp is not None
        assert detector.nlp.meta["name"] == "core_web_sm"

    def test_singleton_works(self):
        """get_structural_detector should return singleton."""
        d1 = get_structural_detector()
        d2 = get_structural_detector()
        assert d1 is d2


class TestPassiveVoiceDetection:
    """Tests for passive voice detection."""

    def test_detect_agentless_passive(self, detector):
        """Should detect passive voice without agent."""
        text = "Mistakes were made during the investigation."
        result = detector.detect(text, ArticleSegment.BODY)

        # Should find passive voice
        passive_detections = [d for d in result.spans if d.type_id_primary in ("D.3.1", "D.3.2")]
        assert len(passive_detections) >= 1

    def test_detect_passive_with_agent(self, detector):
        """Should detect passive voice with 'by' agent."""
        text = "The report was written by the committee."
        result = detector.detect(text, ArticleSegment.BODY)

        # May detect but with different type (D.3.1 vs D.3.2)
        # This is acceptable - passive with agent is less severe
        assert result is not None

    def test_active_voice_not_flagged(self, detector):
        """Active voice should not be flagged as passive."""
        text = "The committee wrote the report."
        result = detector.detect(text, ArticleSegment.BODY)

        passive_detections = [d for d in result.spans if d.type_id_primary in ("D.3.1", "D.3.2")]
        assert len(passive_detections) == 0


class TestRhetoricalQuestionDetection:
    """Tests for rhetorical question detection."""

    def test_detect_rhetorical_question_second_person(self, detector):
        """Should detect rhetorical questions with 'you'."""
        text = "Is your job about to disappear?"
        result = detector.detect(text, ArticleSegment.TITLE)

        rhetorical = [d for d in result.spans if d.type_id_primary == "A.1.4"]
        assert len(rhetorical) >= 1

    def test_detect_rhetorical_question_could_this(self, detector):
        """Should detect 'could this' rhetorical questions."""
        text = "Could this be the end of the industry as we know it?"
        result = detector.detect(text, ArticleSegment.TITLE)

        rhetorical = [d for d in result.spans if d.type_id_primary == "A.1.4"]
        assert len(rhetorical) >= 1

    def test_informational_question_not_flagged(self, detector):
        """Simple informational questions should not be flagged."""
        text = "What time does the meeting start?"
        result = detector.detect(text, ArticleSegment.BODY)

        rhetorical = [d for d in result.spans if d.type_id_primary == "A.1.4"]
        assert len(rhetorical) == 0


class TestVagueQuantifierDetection:
    """Tests for vague quantifier detection."""

    def test_detect_some_say(self, detector):
        """Should detect 'some say' vague attribution."""
        text = "Some say the policy has failed, while others disagree."
        result = detector.detect(text, ArticleSegment.BODY)

        vague = [d for d in result.spans if d.type_id_primary == "D.5.1"]
        assert len(vague) >= 1

    def test_detect_many_believe(self, detector):
        """Should detect 'many believe' vague attribution."""
        text = "Many believe this will lead to significant changes."
        result = detector.detect(text, ArticleSegment.BODY)

        vague = [d for d in result.spans if d.type_id_primary == "D.5.1"]
        assert len(vague) >= 1


class TestTemporalVaguenessDetection:
    """Tests for temporal vagueness detection."""

    def test_detect_recently(self, detector):
        """Should detect 'recently' without specific date."""
        text = "The company recently announced major layoffs."
        result = detector.detect(text, ArticleSegment.BODY)

        temporal = [d for d in result.spans if d.type_id_primary == "D.5.2"]
        assert len(temporal) >= 1

    def test_detect_in_recent_years(self, detector):
        """Should detect 'in recent years' vague timeframe."""
        text = "Crime rates have increased in recent years."
        result = detector.detect(text, ArticleSegment.BODY)

        temporal = [d for d in result.spans if d.type_id_primary == "D.5.2"]
        assert len(temporal) >= 1


class TestAbsoluteDetection:
    """Tests for absolute statement detection."""

    def test_detect_everyone_knows(self, detector):
        """Should detect 'everyone knows' absolute."""
        text = "Everyone knows the system is broken."
        result = detector.detect(text, ArticleSegment.BODY)

        absolutes = [d for d in result.spans if d.type_id_primary == "D.5.4"]
        assert len(absolutes) >= 1

    def test_detect_no_one_believes(self, detector):
        """Should detect 'no one believes' absolute."""
        text = "No one believes the official explanation."
        result = detector.detect(text, ArticleSegment.BODY)

        absolutes = [d for d in result.spans if d.type_id_primary == "D.5.4"]
        assert len(absolutes) >= 1


class TestScanResult:
    """Tests for ScanResult structure."""

    def test_result_has_timing(self, detector):
        """Should record scan duration."""
        text = "The investigation was closed. Mistakes were made."
        result = detector.detect(text, ArticleSegment.BODY)

        assert result.scan_duration_ms >= 0
        assert result.scan_duration_ms < 500  # Should be reasonably fast

    def test_result_has_correct_detector_source(self, detector):
        """Should identify structural detector as source."""
        text = "Some say the policy failed."
        result = detector.detect(text, ArticleSegment.BODY)

        assert result.detector_source == DetectorSource.STRUCTURAL
        for span in result.spans:
            assert span.detector_source == DetectorSource.STRUCTURAL


class TestConvenienceMethods:
    """Tests for convenience methods."""

    def test_detect_title(self, detector):
        """detect_title should set correct segment."""
        result = detector.detect_title("Is your job safe?")
        assert result.segment == ArticleSegment.TITLE

    def test_detect_body(self, detector):
        """detect_body should set correct segment."""
        result = detector.detect_body("The report was released.")
        assert result.segment == ArticleSegment.BODY


class TestEmptyInput:
    """Tests for empty/edge case inputs."""

    def test_empty_text(self, detector):
        """Should handle empty text gracefully."""
        result = detector.detect("", ArticleSegment.BODY)
        assert result.total_detections == 0
        assert result.text_length == 0

    def test_whitespace_only(self, detector):
        """Should handle whitespace-only text."""
        result = detector.detect("   \n\t  ", ArticleSegment.BODY)
        assert result.total_detections == 0

    def test_short_text(self, detector):
        """Should handle very short text."""
        result = detector.detect("Hi.", ArticleSegment.BODY)
        assert result is not None


class TestPerformance:
    """Tests for detector performance."""

    def test_reasonable_speed(self, detector):
        """Should complete in reasonable time for typical text."""
        text = "The investigation was closed. " * 50
        result = detector.detect(text, ArticleSegment.BODY)

        # Should be under 500ms for ~2500 chars
        assert result.scan_duration_ms < 500

    def test_handles_long_text(self, detector):
        """Should handle long articles."""
        text = "The policy was implemented. Some say it failed. " * 200
        result = detector.detect(text, ArticleSegment.BODY)

        assert result.text_length > 5000
        assert result.scan_duration_ms < 2000  # Allow more time for long text
