# app/schemas/grading.py
"""
Schemas for grading endpoints.
"""

from typing import Any

from pydantic import BaseModel, Field


class GradeRequest(BaseModel):
    """Request to grade neutralized text against canon rules."""

    original_text: str = Field(..., description="The original source article text")
    neutral_text: str = Field(..., description="The neutralized article text to grade")
    original_headline: str | None = Field(None, description="Optional original headline")
    neutral_headline: str | None = Field(None, description="Optional neutralized headline")


class RuleResult(BaseModel):
    """Result for a single grading rule."""

    rule_id: str
    passed: bool
    severity: str
    message: str = ""
    evidence: dict[str, Any] | None = None


class GradeResponse(BaseModel):
    """Response from grading endpoint."""

    overall_pass: bool = Field(..., description="True if all critical/major rules pass")
    results: list[RuleResult] = Field(..., description="Individual results for each canon rule")
