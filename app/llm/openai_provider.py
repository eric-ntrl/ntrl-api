# app/llm/openai_provider.py
"""
OpenAI LLM provider implementation.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from app.llm.base import (
    BiasSpan,
    LLMProvider,
    NeutralityAnalysisResult,
    NeutralSummaryResult,
)
from app.llm.prompts import (
    NEUTRAL_SUMMARY_SYSTEM_PROMPT,
    NEUTRAL_SUMMARY_USER_TEMPLATE,
    NEUTRALITY_ANALYSIS_SYSTEM_PROMPT,
    NEUTRALITY_ANALYSIS_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> Dict[str, Any]:
    """Extract JSON from LLM response, handling markdown code blocks."""
    # Try to find JSON in code blocks first
    code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if code_block_match:
        text = code_block_match.group(1).strip()

    # Try to parse as JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            return json.loads(json_match.group())
        raise ValueError(f"Could not extract JSON from response: {text[:200]}")


def _find_term_spans(
    text: str,
    terms: List[str],
    field: str,
) -> List[BiasSpan]:
    """Find character positions of bias terms in text."""
    if not text or not terms:
        return []

    spans: List[BiasSpan] = []
    text_lower = text.lower()

    for term in terms:
        term_lower = term.lower().strip()
        if not term_lower:
            continue

        # Find all occurrences
        start = 0
        while True:
            idx = text_lower.find(term_lower, start)
            if idx == -1:
                break

            spans.append(
                BiasSpan(
                    start=idx,
                    end=idx + len(term),
                    text=text[idx : idx + len(term)],
                    label="non_neutral",
                    severity=0.6,  # Default severity
                    term=term,
                    field=field,
                )
            )
            start = idx + 1

    # Sort by position and remove overlaps
    spans.sort(key=lambda s: (s.start, -(s.end - s.start)))

    result: List[BiasSpan] = []
    occupied_until = -1
    for span in spans:
        if span.start >= occupied_until:
            result.append(span)
            occupied_until = span.end

    return result


class OpenAIProvider(LLMProvider):
    """OpenAI-based LLM provider."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        """
        Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key. If not provided, uses OPENAI_API_KEY env var.
            model: Model to use. If not provided, uses OPENAI_MODEL env var
                   or defaults to gpt-4o-mini for cost efficiency.
        """
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY env var or pass api_key."
            )

        self._model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self._client = OpenAI(api_key=self._api_key)

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    def _chat_completion(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
    ) -> str:
        """Make a chat completion request."""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""

    def generate_neutral_summary(
        self,
        title: str,
        description: Optional[str],
        body: Optional[str],
    ) -> NeutralSummaryResult:
        """Generate a neutral summary using OpenAI."""
        user_message = NEUTRAL_SUMMARY_USER_TEMPLATE.format(
            title=title or "No title",
            description=description or "No description",
            body=body or "No body content",
        )

        try:
            response_text = self._chat_completion(
                NEUTRAL_SUMMARY_SYSTEM_PROMPT,
                user_message,
            )
            data = _extract_json(response_text)

            return NeutralSummaryResult(
                neutral_title=data.get("neutral_title", title),
                neutral_summary_short=data.get(
                    "neutral_summary_short",
                    (body or description or title or "")[:280],
                ),
                neutral_summary_extended=data.get("neutral_summary_extended"),
            )

        except Exception as e:
            logger.error(f"OpenAI summary generation failed: {e}")
            # Fallback to original content
            base_text = body or description or title or ""
            return NeutralSummaryResult(
                neutral_title=title or "Untitled",
                neutral_summary_short=base_text[:280],
                neutral_summary_extended=base_text[:1000] if len(base_text) > 280 else None,
            )

    def analyze_neutrality(
        self,
        title: str,
        description: Optional[str],
        body: Optional[str],
    ) -> NeutralityAnalysisResult:
        """Analyze content for bias using OpenAI."""
        user_message = NEUTRALITY_ANALYSIS_USER_TEMPLATE.format(
            title=title or "No title",
            description=description or "No description",
            body=body or "No body content",
        )

        try:
            response_text = self._chat_completion(
                NEUTRALITY_ANALYSIS_SYSTEM_PROMPT,
                user_message,
            )
            data = _extract_json(response_text)

            # Extract values with defaults
            neutrality_score = int(data.get("neutrality_score", 75))
            neutrality_score = max(0, min(100, neutrality_score))

            bias_terms = data.get("bias_terms", [])
            if not isinstance(bias_terms, list):
                bias_terms = []

            reading_level = int(data.get("reading_level", 8))
            reading_level = max(1, min(18, reading_level))

            political_lean = float(data.get("political_lean", 0.0))
            political_lean = max(-1.0, min(1.0, political_lean))

            # Find bias spans in the most relevant field
            if body:
                span_text, field = body, "original_body"
            elif description:
                span_text, field = description, "original_description"
            else:
                span_text, field = title or "", "original_title"

            bias_spans = _find_term_spans(span_text, bias_terms, field)

            return NeutralityAnalysisResult(
                neutrality_score=neutrality_score,
                bias_terms=bias_terms,
                bias_spans=bias_spans,
                reading_level=reading_level,
                political_lean=political_lean,
            )

        except Exception as e:
            logger.error(f"OpenAI neutrality analysis failed: {e}")
            # Fallback to neutral defaults
            return NeutralityAnalysisResult(
                neutrality_score=75,
                bias_terms=[],
                bias_spans=[],
                reading_level=8,
                political_lean=0.0,
            )
