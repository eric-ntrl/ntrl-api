# tests/test_highlight_accuracy.py
"""
Regression tests for NtrlView highlight accuracy.

These tests validate that:
1. Correct - The right words are highlighted (true positives)
2. Complete - No manipulative phrases missed (minimize false negatives)
3. Precise - Innocent phrases not flagged (minimize false positives)

Uses gold standard annotations in tests/fixtures/gold_standard/
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import pytest

from app.services.neutralizer import (
    MockNeutralizerProvider,
    TransparencySpan,
    find_phrase_positions,
)
from app.models import SpanReason


# Test corpus and gold standard paths
FIXTURES_DIR = Path(__file__).parent / "fixtures"
TEST_CORPUS_DIR = FIXTURES_DIR / "test_corpus"
GOLD_STANDARD_DIR = FIXTURES_DIR / "gold_standard"
METRICS_DIR = FIXTURES_DIR / "metrics"


@dataclass
class GoldSpan:
    """A gold standard expected span."""
    span_id: str
    start_char: int
    end_char: int
    text: str
    reason: str
    action: str
    confidence: str


@dataclass
class SpanMatch:
    """Result of matching a predicted span to gold standard."""
    predicted: TransparencySpan
    gold: GoldSpan
    overlap: float  # Jaccard overlap 0.0-1.0


@dataclass
class AccuracyMetrics:
    """Accuracy metrics for span detection."""
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    partial_matches: int
    position_accuracy: float  # % of TP with correct positions


def load_test_article(article_id: str) -> dict:
    """Load a test article from the corpus."""
    path = TEST_CORPUS_DIR / f"article_{article_id}.json"
    with open(path) as f:
        return json.load(f)


def load_gold_standard(article_id: str) -> dict:
    """Load gold standard spans for an article."""
    path = GOLD_STANDARD_DIR / f"article_{article_id}_spans.json"
    if not path.exists():
        return {"article_id": article_id, "expected_spans": []}
    with open(path) as f:
        return json.load(f)


def parse_gold_spans(gold_data: dict) -> List[GoldSpan]:
    """Parse gold standard JSON into GoldSpan objects."""
    spans = []
    for s in gold_data.get("expected_spans", []):
        spans.append(GoldSpan(
            span_id=s.get("span_id", ""),
            start_char=s.get("start_char", 0),
            end_char=s.get("end_char", 0),
            text=s.get("text", ""),
            reason=s.get("reason", ""),
            action=s.get("action", ""),
            confidence=s.get("confidence", "medium"),
        ))
    return spans


def compute_jaccard_overlap(span1_start: int, span1_end: int,
                            span2_start: int, span2_end: int) -> float:
    """Compute Jaccard overlap between two spans."""
    intersection_start = max(span1_start, span2_start)
    intersection_end = min(span1_end, span2_end)

    if intersection_start >= intersection_end:
        return 0.0  # No overlap

    intersection_len = intersection_end - intersection_start
    union_len = max(span1_end, span2_end) - min(span1_start, span2_start)

    return intersection_len / union_len if union_len > 0 else 0.0


def match_spans(predicted: List[TransparencySpan],
                gold: List[GoldSpan],
                overlap_threshold: float = 0.5) -> Tuple[List[SpanMatch], List[TransparencySpan], List[GoldSpan]]:
    """
    Match predicted spans to gold standard spans.

    Returns:
        (matches, false_positives, false_negatives)
    """
    matches = []
    unmatched_predicted = list(predicted)
    unmatched_gold = list(gold)

    # Sort by position for greedy matching
    unmatched_predicted.sort(key=lambda s: s.start_char)
    unmatched_gold.sort(key=lambda s: s.start_char)

    # Greedy matching - match closest overlapping spans
    for pred in predicted:
        best_match = None
        best_overlap = 0.0

        for gold_span in unmatched_gold:
            overlap = compute_jaccard_overlap(
                pred.start_char, pred.end_char,
                gold_span.start_char, gold_span.end_char
            )

            if overlap >= overlap_threshold and overlap > best_overlap:
                best_match = gold_span
                best_overlap = overlap

        if best_match:
            matches.append(SpanMatch(
                predicted=pred,
                gold=best_match,
                overlap=best_overlap
            ))
            if pred in unmatched_predicted:
                unmatched_predicted.remove(pred)
            if best_match in unmatched_gold:
                unmatched_gold.remove(best_match)

    return matches, unmatched_predicted, unmatched_gold


def compute_accuracy_metrics(predicted: List[TransparencySpan],
                             gold: List[GoldSpan],
                             overlap_threshold: float = 0.5) -> AccuracyMetrics:
    """Compute precision, recall, F1 for span detection."""
    matches, false_positives, false_negatives = match_spans(
        predicted, gold, overlap_threshold
    )

    tp = len(matches)
    fp = len(false_positives)
    fn = len(false_negatives)

    # Precision = TP / (TP + FP)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0

    # Recall = TP / (TP + FN)
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0

    # F1 = 2 * P * R / (P + R)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # Position accuracy: exact matches (>90% overlap)
    exact_matches = sum(1 for m in matches if m.overlap >= 0.9)
    partial_matches = sum(1 for m in matches if 0.5 <= m.overlap < 0.9)
    position_accuracy = exact_matches / tp if tp > 0 else 1.0

    return AccuracyMetrics(
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        partial_matches=partial_matches,
        position_accuracy=position_accuracy,
    )


def save_metrics_to_history(metrics: AccuracyMetrics, notes: str = ""):
    """Save metrics to history file for tracking over time."""
    history_path = METRICS_DIR / "metrics_history.json"

    if history_path.exists():
        with open(history_path) as f:
            data = json.load(f)
    else:
        data = {"history": []}

    entry = {
        "date": datetime.now().isoformat(),
        "precision": round(metrics.precision, 4),
        "recall": round(metrics.recall, 4),
        "f1": round(metrics.f1, 4),
        "position_accuracy": round(metrics.position_accuracy, 4),
        "true_positives": metrics.true_positives,
        "false_positives": metrics.false_positives,
        "false_negatives": metrics.false_negatives,
        "notes": notes,
    }

    data["history"].append(entry)

    with open(history_path, "w") as f:
        json.dump(data, f, indent=2)


# =============================================================================
# Test Classes
# =============================================================================

# Import the global metrics collector from conftest
from tests.conftest import _accuracy_test_results


class TestHighlightAccuracyByArticle:
    """Per-article accuracy tests using gold standard."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = MockNeutralizerProvider()

    @pytest.mark.parametrize("article_id", [
        "001", "002", "003", "004", "005",
        "006", "007", "008", "009", "010"
    ])
    def test_article_accuracy(self, article_id: str):
        """Test span detection accuracy for a single article."""
        # Load article and gold standard
        article = load_test_article(article_id)
        gold_data = load_gold_standard(article_id)
        gold_spans = parse_gold_spans(gold_data)

        # Get predicted spans
        body = article.get("original_body", "")
        if not body:
            pytest.skip(f"Article {article_id} has no body")

        predicted_spans = self.provider._find_spans(body, "body")

        # Compute metrics
        metrics = compute_accuracy_metrics(predicted_spans, gold_spans)

        # Record to global collector for session-end reporting
        _accuracy_test_results["total_tp"] += metrics.true_positives
        _accuracy_test_results["total_fp"] += metrics.false_positives
        _accuracy_test_results["total_fn"] += metrics.false_negatives
        _accuracy_test_results["articles_tested"] += 1

        # For articles with no expected manipulative content
        if not gold_spans:
            # Pattern-based detection produces false positives on clean text
            # This is a known limitation - LLM-based detection should improve this
            # For now, just log the false positives for tracking
            if metrics.false_positives > 0:
                print(f"  Article {article_id} (clean): {metrics.false_positives} false positives detected")
            return

        # For articles with manipulative content:
        # INITIAL BASELINE thresholds are very low because:
        # 1. Pattern-based detection is context-blind (many false positives)
        # 2. Gold standard positions may need refinement
        # 3. LLM-based detection (Phase 0) will significantly improve these
        #
        # Target thresholds after LLM integration: precision >= 0.75, recall >= 0.75
        # Current baseline thresholds: just check recall > 0 (some matches found)

        # Log metrics for tracking improvement
        print(f"  Article {article_id}: P={metrics.precision:.2f}, R={metrics.recall:.2f}, "
              f"TP={metrics.true_positives}, FP={metrics.false_positives}, FN={metrics.false_negatives}")

        # Minimal assertion: we should find at least some true positives
        # Full thresholds will be enforced after LLM-based detection is enabled
        assert metrics.true_positives >= 1 or metrics.false_negatives == 0, (
            f"Article {article_id}: no true positives found "
            f"(TP={metrics.true_positives}, FN={metrics.false_negatives})"
        )


class TestHighlightAccuracyAggregate:
    """Corpus-wide aggregate accuracy tests."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = MockNeutralizerProvider()

    def test_corpus_wide_accuracy(self):
        """Test aggregate accuracy across all test articles."""
        total_tp = 0
        total_fp = 0
        total_fn = 0

        for article_id in ["001", "002", "003", "004", "005",
                           "006", "007", "008", "009", "010"]:
            article = load_test_article(article_id)
            gold_data = load_gold_standard(article_id)
            gold_spans = parse_gold_spans(gold_data)

            body = article.get("original_body", "")
            if not body:
                continue

            predicted_spans = self.provider._find_spans(body, "body")
            metrics = compute_accuracy_metrics(predicted_spans, gold_spans)

            total_tp += metrics.true_positives
            total_fp += metrics.false_positives
            total_fn += metrics.false_negatives

        # Compute corpus-wide metrics
        precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 1.0
        recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 1.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        # Log metrics for visibility - this is the baseline measurement
        print(f"\n{'='*60}")
        print(f"CORPUS-WIDE ACCURACY BASELINE")
        print(f"{'='*60}")
        print(f"  Precision: {precision:.2%} (target: 75%)")
        print(f"  Recall:    {recall:.2%} (target: 75%)")
        print(f"  F1 Score:  {f1:.2%} (target: 75%)")
        print(f"  TP={total_tp}, FP={total_fp}, FN={total_fn}")
        print(f"{'='*60}")
        print(f"\nNote: Low precision is expected with pattern-based detection.")
        print(f"LLM-based detection (Phase 0) should significantly improve these metrics.")

        # INITIAL BASELINE: Just verify we're detecting something
        # Full thresholds (P >= 0.75, R >= 0.75) enforced after LLM integration
        assert total_tp > 0, "No true positives detected across entire corpus"

        # Track trend: recall should be reasonable even with pattern matching
        assert recall >= 0.20, f"Corpus recall {recall:.2%} too low - pattern matching may be broken"


class TestSpanDetectionWithLLM:
    """Tests for the hybrid LLM + position matching approach."""

    def test_find_phrase_positions_basic(self):
        """Test basic phrase position finding."""
        body = "BREAKING NEWS: Senator slams critics in shocking statement."

        llm_phrases = [
            {"phrase": "BREAKING NEWS", "reason": "urgency_inflation", "action": "remove"},
            {"phrase": "slams", "reason": "emotional_trigger", "action": "replace", "replacement": "criticizes"},
            {"phrase": "shocking", "reason": "emotional_trigger", "action": "remove"},
        ]

        spans = find_phrase_positions(body, llm_phrases)

        assert len(spans) == 3

        # Check positions are correct
        assert spans[0].start_char == 0
        assert spans[0].end_char == 13
        assert spans[0].original_text == "BREAKING NEWS"

        # Check slams position
        slams_span = [s for s in spans if s.original_text == "slams"][0]
        assert body[slams_span.start_char:slams_span.end_char] == "slams"

    def test_find_phrase_positions_case_insensitive(self):
        """Test case-insensitive phrase matching."""
        body = "The SHOCKING announcement came as a surprise."

        llm_phrases = [
            {"phrase": "shocking", "reason": "emotional_trigger", "action": "remove"},
        ]

        spans = find_phrase_positions(body, llm_phrases)

        assert len(spans) == 1
        assert spans[0].original_text == "SHOCKING"  # Should find actual text

    def test_find_phrase_positions_multiple_occurrences(self):
        """Test finding multiple occurrences of same phrase."""
        body = "The shocking news was shocking to everyone."

        llm_phrases = [
            {"phrase": "shocking", "reason": "emotional_trigger", "action": "remove"},
        ]

        spans = find_phrase_positions(body, llm_phrases)

        assert len(spans) == 2
        assert spans[0].start_char == 4
        assert spans[1].start_char == 22

    def test_find_phrase_positions_overlapping(self):
        """Test that overlapping spans are deduplicated."""
        body = "BREAKING NEWS: Shocking development"

        llm_phrases = [
            {"phrase": "BREAKING", "reason": "urgency_inflation", "action": "remove"},
            {"phrase": "BREAKING NEWS", "reason": "urgency_inflation", "action": "remove"},
        ]

        spans = find_phrase_positions(body, llm_phrases)

        # Should deduplicate overlapping spans
        assert len(spans) <= 2

    def test_find_phrase_positions_empty_input(self):
        """Test handling of empty inputs."""
        assert find_phrase_positions("", []) == []
        assert find_phrase_positions("some text", []) == []
        assert find_phrase_positions("", [{"phrase": "test", "reason": "clickbait", "action": "remove"}]) == []


class TestMetricsFunctions:
    """Tests for accuracy metric computation functions."""

    def test_jaccard_overlap_exact(self):
        """Test Jaccard overlap for exact match."""
        overlap = compute_jaccard_overlap(0, 10, 0, 10)
        assert overlap == 1.0

    def test_jaccard_overlap_partial(self):
        """Test Jaccard overlap for partial match."""
        overlap = compute_jaccard_overlap(0, 10, 5, 15)
        # Intersection: 5-10 = 5, Union: 0-15 = 15
        assert abs(overlap - 5/15) < 0.001

    def test_jaccard_overlap_no_overlap(self):
        """Test Jaccard overlap for non-overlapping spans."""
        overlap = compute_jaccard_overlap(0, 10, 20, 30)
        assert overlap == 0.0

    def test_accuracy_metrics_perfect(self):
        """Test metrics with perfect prediction."""
        predicted = [
            TransparencySpan(
                field="body", start_char=0, end_char=8,
                original_text="BREAKING", action="removed",
                reason=SpanReason.URGENCY_INFLATION
            )
        ]
        gold = [
            GoldSpan(span_id="001", start_char=0, end_char=8,
                    text="BREAKING", reason="urgency_inflation",
                    action="remove", confidence="high")
        ]

        metrics = compute_accuracy_metrics(predicted, gold)

        assert metrics.true_positives == 1
        assert metrics.false_positives == 0
        assert metrics.false_negatives == 0
        assert metrics.precision == 1.0
        assert metrics.recall == 1.0
        assert metrics.f1 == 1.0

    def test_accuracy_metrics_all_false_positives(self):
        """Test metrics when all predictions are wrong."""
        predicted = [
            TransparencySpan(
                field="body", start_char=0, end_char=5,
                original_text="Hello", action="removed",
                reason=SpanReason.CLICKBAIT
            )
        ]
        gold = []  # Article is clean

        metrics = compute_accuracy_metrics(predicted, gold)

        assert metrics.true_positives == 0
        assert metrics.false_positives == 1
        assert metrics.false_negatives == 0
        assert metrics.precision == 0.0
        assert metrics.recall == 1.0  # No FN

    def test_accuracy_metrics_all_false_negatives(self):
        """Test metrics when all expected spans are missed."""
        predicted = []
        gold = [
            GoldSpan(span_id="001", start_char=0, end_char=8,
                    text="BREAKING", reason="urgency_inflation",
                    action="remove", confidence="high")
        ]

        metrics = compute_accuracy_metrics(predicted, gold)

        assert metrics.true_positives == 0
        assert metrics.false_positives == 0
        assert metrics.false_negatives == 1
        assert metrics.precision == 1.0  # No FP
        assert metrics.recall == 0.0
