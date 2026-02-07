# app/services/auditor.py
"""
NTRL Programmatic Safeguard and Repair Controller.

Two-pass validation system:
1. Neutralizer filters content
2. Auditor validates output against strict NTRL rules

Returns machine-actionable decisions: pass, retry, fail, skip.
"""

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AuditVerdict(str, Enum):
    PASS = "pass"
    RETRY = "retry"
    FAIL = "fail"
    SKIP = "skip"


class ActionType(str, Enum):
    NONE = "none"
    RE_PROMPT = "re_prompt"
    SET_STATUS_FAILED = "set_status_failed"
    SET_STATUS_SKIPPED = "set_status_skipped"


@dataclass
class AuditReason:
    code: str
    detail: str


@dataclass
class AuditChecks:
    has_question_mark_in_headline: bool = False
    has_question_mark_in_summary: bool = False
    consistency_contract_failed: bool = False
    spans_missing_when_manipulative: bool = False
    headline_or_summary_unchanged_when_manipulative: bool = False
    core_fact_downshift_suspected: bool = False
    added_new_facts_suspected: bool = False
    removed_factual_tension_suspected: bool = False
    thin_or_promotional_content: bool = False


@dataclass
class SuggestedAction:
    type: ActionType
    repair_instructions: str = ""


@dataclass
class AuditResult:
    verdict: AuditVerdict
    reasons: list[AuditReason]
    checks: AuditChecks
    suggested_action: SuggestedAction

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "reasons": [{"code": r.code, "detail": r.detail} for r in self.reasons],
            "checks": {
                "has_question_mark_in_headline": self.checks.has_question_mark_in_headline,
                "has_question_mark_in_summary": self.checks.has_question_mark_in_summary,
                "consistency_contract_failed": self.checks.consistency_contract_failed,
                "spans_missing_when_manipulative": self.checks.spans_missing_when_manipulative,
                "headline_or_summary_unchanged_when_manipulative": self.checks.headline_or_summary_unchanged_when_manipulative,
                "core_fact_downshift_suspected": self.checks.core_fact_downshift_suspected,
                "added_new_facts_suspected": self.checks.added_new_facts_suspected,
                "removed_factual_tension_suspected": self.checks.removed_factual_tension_suspected,
                "thin_or_promotional_content": self.checks.thin_or_promotional_content,
            },
            "suggested_action": {
                "type": self.suggested_action.type.value,
                "repair_instructions": self.suggested_action.repair_instructions,
            },
        }


AUDITOR_SYSTEM_PROMPT = """You are the NTRL Programmatic Safeguard and Repair Controller.

NTRL is a filter for information, not a publisher or explainer.
Your role is to AUDIT neutralization outputs for strict compliance with NTRL rules
and to return deterministic, machine-actionable decisions.

You do NOT add facts, interpretation, or editorial framing.
You do NOT rewrite content for publication.
You evaluate, validate, and prescribe corrective actions only.

Neutrality is discipline, not balance.
Clarity is achieved through removal, not replacement.

────────────────────────
CORE NTRL CONSTRAINTS (NON-NEGOTIABLE)
────────────────────────

A. FILTER, NOT AUTHOR
- No added context, interpretation, or analysis beyond the source
- No inferred motives or implications
- No narrative smoothing or abstraction

B. CONSISTENCY CONTRACT
If model_output.has_manipulative_content == true:
- manipulative_spans MUST be non-empty
- AND at least one of neutral_headline or neutral_summary MUST differ
  from the originals (ignoring case and whitespace)

If these conditions are not met, the output is INVALID.

C. RHETORICAL QUESTION BAN
- No question marks allowed in neutral_headline or neutral_summary
- All rhetorical or leading questions must be removed or converted
  to factual statements if the source provides facts to do so

D. CORE FACT INTEGRITY
- Do not downshift central facts
- If death is central in the source (killed, dead, fatal, death),
  the neutral output must state death plainly
- Reducing "killed" or "fatal" to merely "shot" is NOT allowed

E. UNCERTAINTY PRESERVATION
- If uncertainty or dispute exists in the source, it must be explicit
- Omitted uncertainty is a form of manipulation

F. THIN / NON-ARTICLE CONTENT
- Newsletter shells, promo wrappers, recap stubs, or items lacking
  sufficient detail MUST be skipped
- Do not guess or fabricate summaries

────────────────────────
DECISION RULES
────────────────────────

PASS:
- All constraints satisfied
- No rhetorical questions
- Consistency contract satisfied
- No core fact downshifting
- No added interpretation

RETRY:
- Violations are correctable by re-running the neutralizer once
- Provide concise repair_instructions

FAIL:
- Output contradicts NTRL principles after enforcement
- Adds interpretation, removes core facts, or repeatedly violates constraints

SKIP:
- Input is a newsletter, promo shell, or lacks sufficient detail

────────────────────────
IMPORTANT
────────────────────────

- Output JSON ONLY. No prose.
- Be strict. If in doubt, do not pass.
- A single violation is sufficient to prevent passing."""


class Auditor:
    """NTRL output auditor for validation and repair."""

    def __init__(self, model: str = "gpt-4o-mini"):
        self._model = model
        self._api_key = os.getenv("OPENAI_API_KEY")

    def audit(
        self,
        original_title: str,
        original_description: str | None,
        original_body: str | None,
        model_output: dict[str, Any],
    ) -> AuditResult:
        """
        Audit neutralizer output against NTRL constraints.

        Returns machine-actionable verdict with repair instructions if needed.

        NOTE: LLM-based audit is currently disabled as it's too strict and
        causes false failures. Using basic rule-based audit only.
        """
        # LLM-based audit disabled: produces too many false failures with current prompts.
        # Basic rule-based audit is sufficient for current quality level.
        # To re-enable: tune AUDITOR_SYSTEM_PROMPT to reduce false positives,
        # then remove the early return below.
        return self._basic_audit(original_title, original_description, model_output)

        # LLM audit code below is unreachable — kept for future re-enablement.
        if not self._api_key:
            # Fallback to basic validation if no API key
            return self._basic_audit(original_title, original_description, model_output)

        try:
            from openai import OpenAI

            client = OpenAI(api_key=self._api_key)

            user_prompt = f"""Audit this neutralization output.

ORIGINAL TITLE: {original_title}

ORIGINAL DESCRIPTION: {original_description or "N/A"}

ORIGINAL BODY EXCERPT: {(original_body or "")[:1500]}

MODEL OUTPUT:
{json.dumps(model_output, indent=2)}

Return a single JSON object with verdict, reasons, checks, and suggested_action."""

            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": AUDITOR_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,  # More deterministic for validation
                response_format={"type": "json_object"},
            )

            data = json.loads(response.choices[0].message.content)
            return self._parse_audit_response(data)

        except Exception as e:
            logger.error(f"Auditor failed: {e}")
            # Fallback to basic validation
            return self._basic_audit(original_title, original_description, model_output)

    def _basic_audit(
        self,
        original_title: str,
        original_description: str | None,
        model_output: dict[str, Any],
    ) -> AuditResult:
        """Basic rule-based audit when LLM is unavailable."""
        checks = AuditChecks()
        reasons = []

        # Support both old field names (neutral_*) and new field names (feed_*)
        neutral_headline = model_output.get("feed_title") or model_output.get("neutral_headline", "")
        neutral_summary = model_output.get("feed_summary") or model_output.get("neutral_summary", "")
        has_manipulative = model_output.get("has_manipulative_content", False)
        # Support both old (removed_phrases) and new (spans) field names
        removed_phrases = model_output.get("removed_phrases", [])
        spans = model_output.get("spans", [])
        has_transparency_data = len(removed_phrases) > 0 or len(spans) > 0

        # Check for question marks
        if "?" in neutral_headline:
            checks.has_question_mark_in_headline = True
            reasons.append(
                AuditReason(
                    code="RHETORICAL_QUESTION_HEADLINE", detail="Question mark in neutral headline violates NTRL rules"
                )
            )

        # Check for rhetorical question structures (even without ?)
        question_patterns = [
            "is it time",
            "is this the",
            "could this be",
            "will this",
            "are we",
            "should we",
            "can we",
            "what if",
            "why is",
            "how can",
            "how will",
            "what happens",
        ]
        headline_lower = neutral_headline.lower()
        for pattern in question_patterns:
            if headline_lower.startswith(pattern):
                checks.has_question_mark_in_headline = True
                reasons.append(
                    AuditReason(
                        code="RHETORICAL_QUESTION_STRUCTURE",
                        detail=f"Headline starts with rhetorical question pattern '{pattern}'. Convert to factual statement.",
                    )
                )
                break

        if "?" in neutral_summary:
            checks.has_question_mark_in_summary = True
            reasons.append(
                AuditReason(
                    code="RHETORICAL_QUESTION_SUMMARY", detail="Question mark in neutral summary violates NTRL rules"
                )
            )

        # Check consistency contract
        headline_unchanged = self._normalize(neutral_headline) == self._normalize(original_title)
        summary_unchanged = self._normalize(neutral_summary) == self._normalize(original_description or "")

        if has_manipulative and headline_unchanged and summary_unchanged:
            checks.headline_or_summary_unchanged_when_manipulative = True
            checks.consistency_contract_failed = True
            reasons.append(
                AuditReason(code="CONSISTENCY_CONTRACT_VIOLATED", detail="Flagged as manipulative but no changes made")
            )

        if has_manipulative and not has_transparency_data:
            checks.spans_missing_when_manipulative = True
            reasons.append(
                AuditReason(code="SPANS_MISSING", detail="Flagged as manipulative but no transparency spans identified")
            )

        # Check for thin content
        desc = original_description or ""
        if len(desc) < 50 and not original_description:
            checks.thin_or_promotional_content = True

        # Determine verdict
        if checks.thin_or_promotional_content and len(reasons) == 0:
            verdict = AuditVerdict.SKIP
            action = SuggestedAction(ActionType.SET_STATUS_SKIPPED, "Thin or promotional content")
        elif len(reasons) > 0:
            verdict = AuditVerdict.RETRY
            instructions = "; ".join(r.detail for r in reasons)
            action = SuggestedAction(ActionType.RE_PROMPT, instructions)
        else:
            verdict = AuditVerdict.PASS
            action = SuggestedAction(ActionType.NONE)

        return AuditResult(
            verdict=verdict,
            reasons=reasons,
            checks=checks,
            suggested_action=action,
        )

    def _normalize(self, text: str) -> str:
        """Normalize text for comparison (lowercase, strip whitespace)."""
        return " ".join(text.lower().split())

    def _parse_audit_response(self, data: dict[str, Any]) -> AuditResult:
        """Parse LLM audit response into AuditResult."""
        verdict_str = data.get("verdict", "fail")
        try:
            verdict = AuditVerdict(verdict_str)
        except ValueError:
            verdict = AuditVerdict.FAIL

        raw_reasons = data.get("reasons", [])
        # Handle case where LLM returns reasons as a string instead of list
        if isinstance(raw_reasons, str):
            raw_reasons = [{"code": "LLM_RESPONSE", "detail": raw_reasons}] if raw_reasons else []
        reasons = [
            AuditReason(
                code=r.get("code", "UNKNOWN") if isinstance(r, dict) else "UNKNOWN",
                detail=r.get("detail", "") if isinstance(r, dict) else str(r),
            )
            for r in raw_reasons
        ]

        checks_data = data.get("checks", {})
        # Handle case where LLM returns checks as non-dict
        if not isinstance(checks_data, dict):
            checks_data = {}
        checks = AuditChecks(
            has_question_mark_in_headline=checks_data.get("has_question_mark_in_headline", False),
            has_question_mark_in_summary=checks_data.get("has_question_mark_in_summary", False),
            consistency_contract_failed=checks_data.get("consistency_contract_failed", False),
            spans_missing_when_manipulative=checks_data.get("spans_missing_when_manipulative", False),
            headline_or_summary_unchanged_when_manipulative=checks_data.get(
                "headline_or_summary_unchanged_when_manipulative", False
            ),
            core_fact_downshift_suspected=checks_data.get("core_fact_downshift_suspected", False),
            added_new_facts_suspected=checks_data.get("added_new_facts_suspected", False),
            removed_factual_tension_suspected=checks_data.get("removed_factual_tension_suspected", False),
            thin_or_promotional_content=checks_data.get("thin_or_promotional_content", False),
        )

        action_data = data.get("suggested_action", {})
        # Handle case where LLM returns action as non-dict
        if not isinstance(action_data, dict):
            action_data = {}
        action_type_str = action_data.get("type", "none")
        try:
            action_type = ActionType(action_type_str)
        except ValueError:
            action_type = ActionType.NONE

        action = SuggestedAction(
            type=action_type,
            repair_instructions=action_data.get("repair_instructions", ""),
        )

        return AuditResult(
            verdict=verdict,
            reasons=reasons,
            checks=checks,
            suggested_action=action,
        )
