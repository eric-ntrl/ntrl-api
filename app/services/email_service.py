# app/services/email_service.py
"""
Email notification service for evaluation results.

Uses Resend API to send HTML emails with evaluation metrics,
trend charts, and prompt change summaries.
"""

import logging
import urllib.parse
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings

logger = logging.getLogger(__name__)


class EmailService:
    """
    Service for sending evaluation result emails.

    Uses Resend API for delivery and QuickChart.io for chart generation.
    """

    def __init__(self):
        """Initialize email service with settings."""
        self.settings = get_settings()
        self._resend_client = None

    @property
    def resend_client(self):
        """Lazy-load Resend client."""
        if self._resend_client is None and self.settings.RESEND_API_KEY:
            import resend

            resend.api_key = self.settings.RESEND_API_KEY
            self._resend_client = resend
        return self._resend_client

    def send_evaluation_results(
        self,
        db: Session,
        evaluation_run_id: str,
        recipient: str | None = None,
    ) -> dict[str, Any]:
        """
        Send evaluation results email.

        Args:
            db: Database session
            evaluation_run_id: UUID of the evaluation run
            recipient: Optional override for recipient email

        Returns:
            Dict with status, message_id, and any errors
        """
        if not self.settings.EMAIL_ENABLED:
            logger.info("[EMAIL] Email notifications disabled")
            return {"status": "skipped", "reason": "EMAIL_ENABLED=false"}

        if not self.settings.RESEND_API_KEY:
            logger.warning("[EMAIL] RESEND_API_KEY not configured")
            return {"status": "skipped", "reason": "RESEND_API_KEY not set"}

        try:
            # Build email data from database
            email_data = self._build_email_data(db, evaluation_run_id)
            if not email_data:
                return {"status": "failed", "error": "Could not build email data"}

            # Generate HTML content
            html_content = self._render_email_html(email_data)

            # Determine subject line
            quality_score = email_data.get("overall_quality_score", 0) or 0
            delta = email_data.get("quality_delta")
            if delta is not None and delta > 0:
                subject = f"[NTRL] Evaluation improved: {quality_score:.1f}/10 quality score"
            elif delta is not None and delta < 0:
                subject = f"[NTRL] Evaluation declined: {quality_score:.1f}/10 quality score"
            else:
                subject = f"[NTRL] Evaluation complete: {quality_score:.1f}/10 quality score"

            # Send email via Resend
            to_email = recipient or self.settings.EMAIL_RECIPIENT
            response = self.resend_client.Emails.send(
                {
                    "from": self.settings.EMAIL_FROM,
                    "to": [to_email],
                    "subject": subject,
                    "html": html_content,
                }
            )

            logger.info(f"[EMAIL] Sent evaluation email to {to_email}, id={response.get('id')}")
            return {
                "status": "sent",
                "message_id": response.get("id"),
                "recipient": to_email,
            }

        except Exception as e:
            logger.error(f"[EMAIL] Failed to send evaluation email: {e}")
            return {"status": "failed", "error": str(e)}

    def _build_email_data(
        self,
        db: Session,
        evaluation_run_id: str,
    ) -> dict[str, Any] | None:
        """
        Query database for evaluation data needed for email.

        Returns dict with current metrics, deltas, historical data, and prompt changes.
        """
        import uuid as uuid_module

        from app import models

        # Get current evaluation run
        eval_run = (
            db.query(models.EvaluationRun)
            .filter(models.EvaluationRun.id == uuid_module.UUID(evaluation_run_id))
            .first()
        )

        if not eval_run:
            logger.error(f"[EMAIL] Evaluation run {evaluation_run_id} not found")
            return None

        # Get last 10 evaluation runs for trend data
        historical_runs = (
            db.query(models.EvaluationRun)
            .filter(models.EvaluationRun.status == "completed")
            .order_by(models.EvaluationRun.finished_at.desc())
            .limit(10)
            .all()
        )

        # Get previous run for deltas
        prev_run = None
        for run in historical_runs:
            if run.id != eval_run.id:
                prev_run = run
                break

        # Calculate deltas
        def safe_delta(current, prev):
            if current is not None and prev is not None:
                return round(current - prev, 2)
            return None

        classification_delta = None
        neutralization_delta = None
        precision_delta = None
        recall_delta = None
        quality_delta = None

        if prev_run:
            classification_delta = safe_delta(eval_run.classification_accuracy, prev_run.classification_accuracy)
            neutralization_delta = safe_delta(eval_run.avg_neutralization_score, prev_run.avg_neutralization_score)
            precision_delta = safe_delta(eval_run.avg_span_precision, prev_run.avg_span_precision)
            recall_delta = safe_delta(eval_run.avg_span_recall, prev_run.avg_span_recall)
            quality_delta = safe_delta(eval_run.overall_quality_score, prev_run.overall_quality_score)

        # Build trend data (reversed to show oldest first)
        trend_data = {
            "labels": [],
            "quality_scores": [],
            "classification_accuracy": [],
            "neutralization_scores": [],
        }

        for run in reversed(historical_runs):
            if run.finished_at:
                trend_data["labels"].append(run.finished_at.strftime("%m/%d %H:%M"))
            else:
                trend_data["labels"].append("--")
            trend_data["quality_scores"].append(run.overall_quality_score or 0)
            trend_data["classification_accuracy"].append((run.classification_accuracy or 0) * 100)
            trend_data["neutralization_scores"].append(run.avg_neutralization_score or 0)

        # Get prompt changes from this run
        prompt_changes = []
        if eval_run.prompts_updated:
            for change in eval_run.prompts_updated:
                if change.get("applied", True):
                    prompt_changes.append(
                        {
                            "prompt_name": change.get("prompt_name", ""),
                            "old_version": change.get("old_version", 0),
                            "new_version": change.get("new_version", 0),
                            "change_reason": change.get("change_reason", ""),
                            "changes_made": change.get("changes_made", []),
                        }
                    )

        # Aggregate missed items from article evaluations
        action_items = []
        missed_by_category = {}

        if eval_run.article_evaluations:
            low_neutralization_count = 0
            for ae in eval_run.article_evaluations:
                if ae.neutralization_score and ae.neutralization_score < 7.0:
                    low_neutralization_count += 1
                if ae.missed_manipulations:
                    for item in ae.missed_manipulations:
                        cat = item.get("category", "other")
                        missed_by_category[cat] = missed_by_category.get(cat, 0) + 1

            if low_neutralization_count > 0:
                action_items.append(
                    {
                        "category": "NEUTRALIZATION",
                        "message": f"{low_neutralization_count} articles scored <7.0",
                    }
                )

            # Check span recall target
            if eval_run.avg_span_recall and eval_run.avg_span_recall < 0.99:
                action_items.append(
                    {
                        "category": "SPAN_RECALL",
                        "message": f"Targeting 99%, at {eval_run.avg_span_recall * 100:.0f}%",
                    }
                )

        return {
            "evaluation_run_id": str(eval_run.id),
            "finished_at": eval_run.finished_at or datetime.now(UTC),
            "overall_quality_score": eval_run.overall_quality_score,
            "quality_delta": quality_delta,
            "classification_accuracy": eval_run.classification_accuracy,
            "classification_delta": classification_delta,
            "avg_neutralization_score": eval_run.avg_neutralization_score,
            "neutralization_delta": neutralization_delta,
            "avg_span_precision": eval_run.avg_span_precision,
            "precision_delta": precision_delta,
            "avg_span_recall": eval_run.avg_span_recall,
            "recall_delta": recall_delta,
            "estimated_cost_usd": eval_run.estimated_cost_usd,
            "trend_data": trend_data,
            "prompt_changes": prompt_changes,
            "action_items": action_items,
            "missed_by_category": missed_by_category,
        }

    def _generate_trend_chart_url(self, trend_data: dict) -> str:
        """
        Generate QuickChart.io URL for trend visualization.

        Args:
            trend_data: Dict with labels and score arrays

        Returns:
            URL to rendered PNG chart
        """
        chart_config = {
            "type": "line",
            "data": {
                "labels": trend_data.get("labels", []),
                "datasets": [
                    {
                        "label": "Quality Score",
                        "data": trend_data.get("quality_scores", []),
                        "borderColor": "#10B981",
                        "backgroundColor": "rgba(16, 185, 129, 0.1)",
                        "fill": True,
                        "tension": 0.3,
                    },
                    {
                        "label": "Neutralization",
                        "data": trend_data.get("neutralization_scores", []),
                        "borderColor": "#6366F1",
                        "backgroundColor": "transparent",
                        "borderDash": [5, 5],
                        "tension": 0.3,
                    },
                ],
            },
            "options": {
                "scales": {
                    "y": {
                        "min": 0,
                        "max": 10,
                        "title": {"display": True, "text": "Score"},
                    },
                },
                "plugins": {
                    "title": {
                        "display": True,
                        "text": "Evaluation Trends (Last 10 Runs)",
                    },
                    "legend": {"position": "bottom"},
                },
            },
        }

        import json

        chart_json = json.dumps(chart_config)
        encoded = urllib.parse.quote(chart_json)
        return f"https://quickchart.io/chart?c={encoded}&w=600&h=300&bkg=white"

    def _render_email_html(self, data: dict[str, Any]) -> str:
        """
        Render HTML email template with evaluation data.

        Args:
            data: Email data dict from _build_email_data

        Returns:
            HTML string for email body
        """
        # Generate chart URL
        chart_url = self._generate_trend_chart_url(data.get("trend_data", {}))

        # Format values
        quality_score = data.get("overall_quality_score") or 0
        quality_delta = data.get("quality_delta")
        classification = data.get("classification_accuracy") or 0
        classification_delta = data.get("classification_delta")
        neutralization = data.get("avg_neutralization_score") or 0
        neutralization_delta = data.get("neutralization_delta")
        precision = data.get("avg_span_precision") or 0
        precision_delta = data.get("precision_delta")
        recall = data.get("avg_span_recall") or 0
        recall_delta = data.get("recall_delta")
        cost = data.get("estimated_cost_usd") or 0
        run_id = data.get("evaluation_run_id", "")[:8]
        finished_at = data.get("finished_at", datetime.now(UTC))

        def format_delta(val, is_percentage=False):
            if val is None:
                return ""
            if is_percentage:
                val = val * 100
            sign = "+" if val > 0 else ""
            if is_percentage:
                return f'<span style="color: {"#10B981" if val >= 0 else "#EF4444"}; font-size: 12px;">({sign}{val:.0f}%)</span>'
            return f'<span style="color: {"#10B981" if val >= 0 else "#EF4444"}; font-size: 12px;">({sign}{val:.1f})</span>'

        def format_delta_pct(val):
            """Format a delta that's already a percentage (0-1 scale)."""
            if val is None:
                return ""
            pct = val * 100
            sign = "+" if pct > 0 else ""
            return f'<span style="color: {"#10B981" if pct >= 0 else "#EF4444"}; font-size: 12px;">({sign}{pct:.0f}%)</span>'

        # Build prompt changes HTML
        prompt_changes_html = ""
        if data.get("prompt_changes"):
            changes_items = ""
            for change in data["prompt_changes"]:
                name = change.get("prompt_name", "")
                old_v = change.get("old_version", 0)
                new_v = change.get("new_version", 0)
                reason = change.get("change_reason", "")
                changes_items += f"""
                <li style="margin-bottom: 8px;">
                    <strong>{name}</strong>: v{old_v} -> v{new_v}
                    <br><span style="color: #6B7280; font-size: 12px;">{reason}</span>
                </li>
                """
            prompt_changes_html = f"""
            <div style="background: #ECFDF5; border-left: 4px solid #10B981; padding: 16px; margin-top: 20px;">
                <h3 style="margin: 0 0 12px 0; color: #065F46; font-size: 14px;">PROMPT CHANGES MADE</h3>
                <ul style="margin: 0; padding-left: 20px; color: #1F2937;">
                    {changes_items}
                </ul>
            </div>
            """

        # Build action items HTML
        action_items_html = ""
        if data.get("action_items"):
            items = ""
            for item in data["action_items"]:
                items += f"""
                <li style="margin-bottom: 4px;">
                    <strong>{item.get("category", "")}</strong>: {item.get("message", "")}
                </li>
                """
            action_items_html = f"""
            <div style="background: #FFFBEB; border-left: 4px solid #F59E0B; padding: 16px; margin-top: 20px;">
                <h3 style="margin: 0 0 12px 0; color: #92400E; font-size: 14px;">ACTION ITEMS ({len(data["action_items"])})</h3>
                <ul style="margin: 0; padding-left: 20px; color: #1F2937;">
                    {items}
                </ul>
            </div>
            """

        # Build missed items HTML
        missed_items_html = ""
        if data.get("missed_by_category"):
            items = ""
            for cat, count in sorted(data["missed_by_category"].items(), key=lambda x: -x[1]):
                items += f"<li>{cat}: {count} missed</li>"
            missed_items_html = f"""
            <div style="background: #FEF2F2; border-left: 4px solid #EF4444; padding: 16px; margin-top: 20px;">
                <h3 style="margin: 0 0 12px 0; color: #991B1B; font-size: 14px;">MISSED MANIPULATIONS BY CATEGORY</h3>
                <ul style="margin: 0; padding-left: 20px; color: #1F2937;">
                    {items}
                </ul>
            </div>
            """

        # Determine score color
        if quality_score >= 8:
            score_color = "#10B981"  # Green
        elif quality_score >= 6:
            score_color = "#F59E0B"  # Amber
        else:
            score_color = "#EF4444"  # Red

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #F3F4F6;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <!-- Header -->
        <div style="background: linear-gradient(135deg, #1F2937 0%, #374151 100%); color: white; padding: 24px; border-radius: 12px 12px 0 0; text-align: center;">
            <h1 style="margin: 0; font-size: 24px; font-weight: 600;">NTRL Evaluation Report</h1>
            <p style="margin: 8px 0 0 0; opacity: 0.8; font-size: 14px;">{finished_at.strftime("%B %d, %Y at %I:%M %p")} UTC</p>
        </div>

        <!-- Main Content -->
        <div style="background: white; padding: 24px; border-radius: 0 0 12px 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">

            <!-- Overall Score -->
            <div style="text-align: center; padding: 20px; background: #F9FAFB; border-radius: 12px; margin-bottom: 20px;">
                <div style="font-size: 48px; font-weight: 700; color: {score_color};">{quality_score:.1f}<span style="font-size: 24px; color: #9CA3AF;">/10</span></div>
                <div style="font-size: 14px; color: #6B7280;">Overall Quality Score {format_delta(quality_delta)}</div>
            </div>

            <!-- Metrics Grid -->
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 20px;">
                <div style="background: #F9FAFB; padding: 16px; border-radius: 8px; text-align: center;">
                    <div style="font-size: 28px; font-weight: 600; color: #1F2937;">{classification * 100:.0f}%</div>
                    <div style="font-size: 12px; color: #6B7280;">Classification {format_delta_pct(classification_delta)}</div>
                </div>
                <div style="background: #F9FAFB; padding: 16px; border-radius: 8px; text-align: center;">
                    <div style="font-size: 28px; font-weight: 600; color: #1F2937;">{neutralization:.1f}</div>
                    <div style="font-size: 12px; color: #6B7280;">Neutralization {format_delta(neutralization_delta)}</div>
                </div>
                <div style="background: #F9FAFB; padding: 16px; border-radius: 8px; text-align: center;">
                    <div style="font-size: 28px; font-weight: 600; color: #1F2937;">{precision * 100:.0f}%</div>
                    <div style="font-size: 12px; color: #6B7280;">Span Precision {format_delta_pct(precision_delta)}</div>
                </div>
                <div style="background: #F9FAFB; padding: 16px; border-radius: 8px; text-align: center;">
                    <div style="font-size: 28px; font-weight: 600; color: #1F2937;">{recall * 100:.0f}%</div>
                    <div style="font-size: 12px; color: #6B7280;">Span Recall {format_delta_pct(recall_delta)}</div>
                </div>
            </div>

            <!-- Trend Chart -->
            <div style="margin-bottom: 20px;">
                <img src="{chart_url}" alt="Evaluation Trends" style="width: 100%; border-radius: 8px; border: 1px solid #E5E7EB;">
            </div>

            {prompt_changes_html}

            {action_items_html}

            {missed_items_html}

            <!-- Footer -->
            <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid #E5E7EB; text-align: center; color: #9CA3AF; font-size: 12px;">
                Cost: ${cost:.2f} | Run ID: {run_id}...
            </div>
        </div>
    </div>
</body>
</html>
        """

        return html
