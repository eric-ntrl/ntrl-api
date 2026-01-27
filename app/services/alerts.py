"""
Pipeline alert system for detecting and flagging degraded health.

Alerts are checked after each pipeline run and stored in the PipelineRunSummary.
Currently visible via GET /v1/status endpoint.
"""

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import PipelineRunSummary


class AlertCode(str, Enum):
    """Alert codes for pipeline health issues."""

    BODY_DOWNLOAD_RATE_LOW = "body_download_rate_low"
    NEUTRALIZATION_RATE_LOW = "neutralization_rate_low"
    BRIEF_STORY_COUNT_LOW = "brief_story_count_low"
    PIPELINE_FAILED = "pipeline_failed"
    INGESTION_ZERO = "ingestion_zero"
    CLASSIFY_FALLBACK_RATE_HIGH = "classify_fallback_rate_high"


# Alert thresholds (can be made configurable via env vars in the future)
ALERT_THRESHOLDS = {
    AlertCode.BODY_DOWNLOAD_RATE_LOW: 70,  # Alert if <70% body download success
    AlertCode.NEUTRALIZATION_RATE_LOW: 90,  # Alert if <90% neutralization success
    AlertCode.BRIEF_STORY_COUNT_LOW: 10,  # Alert if brief has <10 stories
}


def check_alerts(summary: "PipelineRunSummary") -> list[str]:
    """
    Check pipeline run summary against thresholds and return triggered alert codes.

    Args:
        summary: The PipelineRunSummary to check

    Returns:
        List of alert code strings that were triggered
    """
    alerts = []

    # Check body download rate
    if summary.ingest_total > 0:
        rate = summary.ingest_body_downloaded / summary.ingest_total * 100
        if rate < ALERT_THRESHOLDS[AlertCode.BODY_DOWNLOAD_RATE_LOW]:
            alerts.append(AlertCode.BODY_DOWNLOAD_RATE_LOW.value)

    # Check neutralization rate
    if summary.neutralize_total > 0:
        rate = summary.neutralize_success / summary.neutralize_total * 100
        if rate < ALERT_THRESHOLDS[AlertCode.NEUTRALIZATION_RATE_LOW]:
            alerts.append(AlertCode.NEUTRALIZATION_RATE_LOW.value)

    # Check brief story count
    if summary.brief_story_count < ALERT_THRESHOLDS[AlertCode.BRIEF_STORY_COUNT_LOW]:
        alerts.append(AlertCode.BRIEF_STORY_COUNT_LOW.value)

    # Check classification keyword fallback rate
    if hasattr(summary, 'classify_total') and summary.classify_total > 0:
        fallback_rate = summary.classify_keyword_fallback / summary.classify_total
        if fallback_rate > 0.01:  # >1% keyword fallback
            alerts.append(AlertCode.CLASSIFY_FALLBACK_RATE_HIGH.value)

    # Check for zero ingestion
    if summary.ingest_total == 0:
        alerts.append(AlertCode.INGESTION_ZERO.value)

    # Check for overall pipeline failure
    if summary.status == "failed":
        alerts.append(AlertCode.PIPELINE_FAILED.value)

    return alerts


def get_alert_description(alert_code: str) -> str:
    """Get human-readable description for an alert code."""
    descriptions = {
        AlertCode.BODY_DOWNLOAD_RATE_LOW.value: (
            f"Body download success rate is below {ALERT_THRESHOLDS[AlertCode.BODY_DOWNLOAD_RATE_LOW]}%"
        ),
        AlertCode.NEUTRALIZATION_RATE_LOW.value: (
            f"Neutralization success rate is below {ALERT_THRESHOLDS[AlertCode.NEUTRALIZATION_RATE_LOW]}%"
        ),
        AlertCode.BRIEF_STORY_COUNT_LOW.value: (
            f"Brief contains fewer than {ALERT_THRESHOLDS[AlertCode.BRIEF_STORY_COUNT_LOW]} stories"
        ),
        AlertCode.PIPELINE_FAILED.value: "Pipeline run failed",
        AlertCode.INGESTION_ZERO.value: "No articles were ingested",
        AlertCode.CLASSIFY_FALLBACK_RATE_HIGH.value: "LLM classification fallback rate exceeded 1%",
    }
    return descriptions.get(alert_code, f"Unknown alert: {alert_code}")
