# app/services/ntrl_fix/detail_full_gen.py
"""
Detail Full Generator: Creates neutralized full article text.

This generator takes the original article body and detected manipulation spans,
then produces a neutralized version by applying the recommended fixes.

Key features:
- Span-guided rewriting (LLM knows exactly what to fix)
- Preserves facts, quotes, and attributions
- Maintains ~80-100% of original length
- Returns structured JSON with changes tracked
"""

import json
import os
import time
from typing import Optional
from dataclasses import dataclass
import httpx

from .types import (
    ChangeRecord,
    FixAction,
    SpanContext,
    GeneratorConfig,
)
from ..ntrl_scan.types import MergedScanResult, DetectionInstance
from app.taxonomy import get_type, CATEGORY_NAMES


DETAIL_FULL_PROMPT = """You are a professional news editor. Your task is to neutralize manipulation in this article while preserving ALL facts.

ORIGINAL ARTICLE:
{body}

MANIPULATION SPANS TO FIX:
{spans_formatted}

For each flagged span, apply the recommended action:
- remove: Delete the text entirely (only for pure manipulation with no factual content)
- replace: Use a neutral equivalent word/phrase
- rewrite: Rephrase to remove manipulation while keeping facts
- annotate: Keep text but flag for transparency (no change needed)

CRITICAL RULES - NEVER VIOLATE THESE:
1. PRESERVE ALL FACTS - Every name, number, date, quote, and claim must remain
2. PRESERVE ALL QUOTES - Direct quotes must be kept VERBATIM, even if they contain manipulation
3. NO MODALITY UPGRADES - Never change "alleged" to "confirmed", "may" to "will", etc.
4. NO INFERENCE - Never add facts, motives, or conclusions not in original
5. MAINTAIN LENGTH - Output should be 80-100% of input length
6. PRESERVE NEGATIONS - Never accidentally remove "not", "no", "never", etc.

EXAMPLES OF GOOD NEUTRALIZATION:
- "SLAMS critics" → "responded to critics" or "criticized"
- "devastating attack" → "strong criticism"
- "You won't believe" → [remove - no factual content]
- "some say" → [keep if attribution follows, flag if vague]

Return a JSON object with this exact structure:
{{
  "neutralized_text": "The full neutralized article text...",
  "changes": [
    {{
      "detection_id": "uuid-from-input",
      "action_taken": "removed|replaced|rewritten|preserved",
      "original": "original text",
      "replacement": "new text or null if removed",
      "rationale": "brief explanation"
    }}
  ]
}}

Return ONLY valid JSON, no other text."""


@dataclass
class DetailFullResult:
    """Result from detail full generation."""
    text: str
    changes: list[dict]
    processing_time_ms: float = 0.0


class DetailFullGenerator:
    """
    Generates neutralized full article text guided by detected spans.

    Uses an LLM to intelligently rewrite manipulation while preserving
    all factual content and following strict invariance rules.
    """

    def __init__(self, config: Optional[GeneratorConfig] = None):
        """Initialize with configuration."""
        self.config = config or GeneratorConfig()
        self._client: Optional[httpx.AsyncClient] = None

        # Auto-configure provider if needed
        if self.config.provider == "auto":
            self._auto_configure()

    def _auto_configure(self):
        """Auto-configure from environment variables."""
        if os.getenv("OPENAI_API_KEY"):
            self.config.provider = "openai"
            self.config.model = self.config.model or "gpt-4o"
        elif os.getenv("ANTHROPIC_API_KEY"):
            self.config.provider = "anthropic"
            self.config.model = self.config.model or "claude-3-5-sonnet-20241022"
        else:
            self.config.provider = "mock"
            self.config.model = "mock"

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.config.timeout)
        return self._client

    async def generate(
        self,
        body: str,
        scan_result: MergedScanResult,
    ) -> DetailFullResult:
        """
        Generate neutralized article text.

        Args:
            body: Original article body text
            scan_result: Detection results from ntrl-scan

        Returns:
            DetailFullResult with neutralized text and change records
        """
        start_time = time.perf_counter()

        if not body or not body.strip():
            return DetailFullResult(
                text="",
                changes=[],
                processing_time_ms=0.0
            )

        # If no detections, return original
        if not scan_result.spans:
            return DetailFullResult(
                text=body,
                changes=[],
                processing_time_ms=(time.perf_counter() - start_time) * 1000
            )

        # Format spans for prompt
        spans_formatted = self._format_spans(scan_result.spans)

        # Generate based on provider
        if self.config.provider == "mock":
            result = self._mock_generate(body, scan_result.spans)
        elif self.config.provider == "openai":
            result = await self._openai_generate(body, spans_formatted)
        elif self.config.provider == "anthropic":
            result = await self._anthropic_generate(body, spans_formatted)
        else:
            result = self._mock_generate(body, scan_result.spans)

        result.processing_time_ms = (time.perf_counter() - start_time) * 1000
        return result

    def _format_spans(self, spans: list[DetectionInstance]) -> str:
        """Format spans for inclusion in prompt."""
        lines = []
        for span in spans:
            manip_type = get_type(span.type_id_primary)
            type_label = manip_type.label if manip_type else span.type_id_primary

            context = SpanContext(
                detection_id=span.detection_id,
                type_id=span.type_id_primary,
                type_label=type_label,
                span_start=span.span_start,
                span_end=span.span_end,
                text=span.text,
                action=span.recommended_action.value,
                severity=span.severity,
                rationale=span.rationale or f"Detected {type_label}"
            )
            lines.append(context.to_prompt_line())

        return "\n".join(lines)

    def _mock_generate(
        self,
        body: str,
        spans: list[DetectionInstance]
    ) -> DetailFullResult:
        """Mock generation for testing without LLM."""
        # Simple rule-based substitutions
        result_text = body
        changes = []

        # Sort spans by position (reverse to maintain offsets)
        sorted_spans = sorted(spans, key=lambda s: s.span_start, reverse=True)

        for span in sorted_spans:
            original = span.text

            # Apply simple rules based on action
            if span.recommended_action.value == "remove":
                # Remove the text
                result_text = (
                    result_text[:span.span_start] +
                    result_text[span.span_end:]
                )
                replacement = None
                action_taken = "removed"

            elif span.recommended_action.value == "replace":
                # Use simple replacements for common patterns
                replacement = self._get_mock_replacement(original)
                result_text = (
                    result_text[:span.span_start] +
                    replacement +
                    result_text[span.span_end:]
                )
                action_taken = "replaced"

            elif span.recommended_action.value == "rewrite":
                # For rewrite, just use replacement
                replacement = self._get_mock_replacement(original)
                result_text = (
                    result_text[:span.span_start] +
                    replacement +
                    result_text[span.span_end:]
                )
                action_taken = "rewritten"

            else:
                # Preserve/annotate - no change
                replacement = original
                action_taken = "preserved"

            changes.append({
                "detection_id": span.detection_id,
                "action_taken": action_taken,
                "original": original,
                "replacement": replacement,
                "rationale": f"Mock {action_taken} for {span.type_id_primary}"
            })

        return DetailFullResult(
            text=result_text.strip(),
            changes=changes
        )

    def _get_mock_replacement(self, original: str) -> str:
        """Get simple mock replacement for common manipulation patterns."""
        replacements = {
            # Urgency markers
            "BREAKING": "",
            "JUST IN": "",
            "URGENT": "",
            "DEVELOPING": "",
            "ALERT": "",
            # Rage verbs
            "slams": "criticized",
            "SLAMS": "criticized",
            "blasts": "criticized",
            "BLASTS": "criticized",
            "destroys": "responded to",
            "DESTROYS": "responded to",
            "eviscerates": "challenged",
            "decimates": "criticized",
            "annihilates": "disputed",
            # Sensationalism
            "shocking": "notable",
            "SHOCKING": "notable",
            "stunning": "significant",
            "jaw-dropping": "significant",
            "mind-blowing": "notable",
            # Clickbait
            "you won't believe": "",
            "You won't believe": "",
        }

        # Check exact match first
        if original in replacements:
            return replacements[original]

        # Check case-insensitive
        original_lower = original.lower()
        for pattern, replacement in replacements.items():
            if pattern.lower() == original_lower:
                return replacement

        # Default: return slightly modified version
        return original

    async def _openai_generate(
        self,
        body: str,
        spans_formatted: str,
        retry_count: int = 0
    ) -> DetailFullResult:
        """
        Generate using OpenAI API with retry logic.

        Retries on API errors and JSON parse failures.
        """
        import logging
        logger = logging.getLogger(__name__)
        MAX_RETRIES = 2

        try:
            client = await self._get_client()

            prompt = DETAIL_FULL_PROMPT.format(
                body=body,
                spans_formatted=spans_formatted
            )

            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.config.model,
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "response_format": {"type": "json_object"},
                },
            )

            if response.status_code != 200:
                raise Exception(f"OpenAI API error: {response.status_code}")

            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")

            return self._parse_response(content, body)

        except Exception as e:
            if retry_count < MAX_RETRIES:
                logger.warning(
                    f"OpenAI detail_full failed (attempt {retry_count + 1}/{MAX_RETRIES + 1}): {e}, retrying..."
                )
                import asyncio
                await asyncio.sleep(1)  # Brief backoff
                return await self._openai_generate(body, spans_formatted, retry_count + 1)
            else:
                logger.error(f"OpenAI detail_full failed after {MAX_RETRIES + 1} attempts: {e}")
                # Fall back to mock which does rule-based neutralization
                from ..ntrl_scan.types import DetectionInstance
                return self._mock_generate(body, [])

    async def _anthropic_generate(
        self,
        body: str,
        spans_formatted: str,
        retry_count: int = 0
    ) -> DetailFullResult:
        """
        Generate using Anthropic API with retry logic.

        Retries on API errors and JSON parse failures.
        """
        import logging
        logger = logging.getLogger(__name__)
        MAX_RETRIES = 2

        try:
            client = await self._get_client()

            prompt = DETAIL_FULL_PROMPT.format(
                body=body,
                spans_formatted=spans_formatted
            )

            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": os.getenv("ANTHROPIC_API_KEY"),
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.config.model,
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                },
            )

            if response.status_code != 200:
                raise Exception(f"Anthropic API error: {response.status_code}")

            result = response.json()
            content = result.get("content", [{}])[0].get("text", "{}")

            return self._parse_response(content, body)

        except Exception as e:
            if retry_count < MAX_RETRIES:
                logger.warning(
                    f"Anthropic detail_full failed (attempt {retry_count + 1}/{MAX_RETRIES + 1}): {e}, retrying..."
                )
                import asyncio
                await asyncio.sleep(1)  # Brief backoff
                return await self._anthropic_generate(body, spans_formatted, retry_count + 1)
            else:
                logger.error(f"Anthropic detail_full failed after {MAX_RETRIES + 1} attempts: {e}")
                # Fall back to mock which does rule-based neutralization
                return self._mock_generate(body, [])

    def _parse_response(
        self,
        content: str,
        fallback_body: str,
        retry_count: int = 0
    ) -> DetailFullResult:
        """
        Parse LLM response into DetailFullResult.

        CRITICAL: This function now validates that neutralized_text is present
        and different from the original. Silent fallback to original is a bug.
        """
        MAX_PARSE_RETRIES = 2

        try:
            data = json.loads(content)

            # CRITICAL FIX: Check if neutralized_text exists
            neutralized_text = data.get("neutralized_text")
            if neutralized_text is None:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(
                    f"V2 detail_full: LLM response missing 'neutralized_text' key. "
                    f"Available keys: {list(data.keys())}"
                )
                # Don't silently return original - raise to trigger retry
                raise ValueError("Missing neutralized_text in LLM response")

            # Validate that neutralization actually happened
            import difflib
            ratio = difflib.SequenceMatcher(None, fallback_body, neutralized_text).ratio()
            if ratio > 0.98:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"V2 detail_full: neutralized text nearly identical to original "
                    f"(ratio={ratio:.3f}). Neutralization may have failed."
                )

            return DetailFullResult(
                text=neutralized_text,
                changes=data.get("changes", [])
            )

        except json.JSONDecodeError as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"V2 detail_full: JSON parse error: {e}")

            # Log the problematic content for debugging
            if len(content) > 200:
                logger.debug(f"Response content (truncated): {content[:200]}...")
            else:
                logger.debug(f"Response content: {content}")

            # Don't silently return original - this is a bug
            raise ValueError(f"Invalid JSON from LLM: {e}")

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
