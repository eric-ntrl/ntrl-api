# tests/conftest.py
"""
Pytest configuration and fixtures.
"""

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

# Set test environment
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "llm: tests requiring LLM API calls (deselect with '-m \"not llm\"')")


# Metrics collection for highlight accuracy tests
_accuracy_test_results = {
    "total_tp": 0,
    "total_fp": 0,
    "total_fn": 0,
    "articles_tested": 0,
}


@pytest.fixture(scope="session")
def accuracy_metrics_collector():
    """Session-scoped fixture to collect accuracy metrics."""
    return _accuracy_test_results


def pytest_sessionfinish(session, exitstatus):
    """
    Called after all tests complete.
    Saves metrics to history file if accuracy tests were run.
    """
    results = _accuracy_test_results

    # Only save if accuracy tests were actually run
    if results["articles_tested"] == 0:
        return

    tp = results["total_tp"]
    fp = results["total_fp"]
    fn = results["total_fn"]

    # Calculate metrics
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # Save to history
    metrics_dir = Path(__file__).parent / "fixtures" / "metrics"
    history_path = metrics_dir / "metrics_history.json"

    if history_path.exists():
        with open(history_path) as f:
            data = json.load(f)
    else:
        data = {"history": [], "thresholds": {"precision_min": 0.75, "recall_min": 0.75, "f1_min": 0.75}}

    entry = {
        "date": datetime.now().isoformat(),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "articles_tested": results["articles_tested"],
        "test_passed": exitstatus == 0,
    }

    data["history"].append(entry)

    # Keep last 50 entries
    if len(data["history"]) > 50:
        data["history"] = data["history"][-50:]

    with open(history_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\n\nAccuracy Metrics Recorded: P={precision:.2%}, R={recall:.2%}, F1={f1:.2%}")
