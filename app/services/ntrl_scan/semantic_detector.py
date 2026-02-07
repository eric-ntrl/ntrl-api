# app/services/ntrl_scan/semantic_detector.py
"""
Semantic Detector: LLM-based manipulation detection (~300ms).

This detector uses a fast LLM (Claude Haiku or GPT-4o-mini) to detect
subtle manipulation patterns that require semantic understanding:
- Motive certainty (C.2.3)
- Intent attribution (C.2.4)
- Identity/tribal priming (B.4.1)
- Presupposition traps (D.4.1)
- Agenda masking (F.3.1)
- False balance (C.6.1)

These patterns are too context-dependent for regex or simple NLP.
"""

import json
import os
import time
from dataclasses import dataclass

import httpx

from app.taxonomy import get_type

from .types import (
    ArticleSegment,
    DetectionInstance,
    DetectorSource,
    ScanResult,
    SpanAction,
)

# Detection prompt for the LLM
DETECTION_PROMPT = """Analyze this text for manipulation patterns that require semantic understanding.

Focus on these specific manipulation types (only flag if clearly present):

1. C.2.3 Motive certainty - Presenting inferred motives as known facts
   Example: "They did this to silence critics" (claiming to know why without evidence)

2. C.2.4 Intent attribution - Attributing intent without evidence
   Example: "Officials want you to be scared" (claiming to know others' goals)

3. B.4.1 Identity/tribal priming - Activating group identity to influence perception
   Example: "Real Americans know the truth" (defining who belongs)

4. D.4.1 Presupposition trap - Questions that presuppose contested claims
   Example: "Why did officials fail to act?" (assumes failure)

5. F.3.1 Agenda masking - Advocacy disguised as neutral reporting
   Example: Editorializing disguised as fact reporting

6. C.6.1 False balance - Treating evidence-based and baseless claims as equal
   Example: "Scientists say X, but some dispute this" (when dispute is fringe)

TEXT TO ANALYZE:
{text}

INSTRUCTIONS:
- Only flag clear, confident detections
- Provide exact character positions (span_start, span_end)
- Be conservative - when uncertain, don't flag
- Focus on subtle semantic manipulation, not obvious keywords

Return a JSON array of detections. Each detection must have:
- type_id: The manipulation type (e.g., "C.2.3")
- span_start: Character start position (0-indexed)
- span_end: Character end position (exclusive)
- text: The exact text span flagged
- confidence: 0.0 to 1.0
- rationale: Brief explanation (1 sentence)

If no manipulation found, return an empty array: []

Return ONLY valid JSON, no other text."""


@dataclass
class LLMConfig:
    """Configuration for LLM provider."""

    provider: str  # "anthropic", "openai", "mock"
    model: str
    api_key: str | None = None
    timeout: float = 30.0
    max_tokens: int = 1024


class SemanticDetector:
    """
    LLM-based detection for subtle semantic manipulation.

    Uses a fast model (Haiku/GPT-4o-mini) to detect manipulation patterns
    that require understanding context, intent, and implication.
    """

    # Types this detector specializes in
    TARGET_TYPES = {
        "C.2.3",  # Motive certainty
        "C.2.4",  # Intent attribution
        "B.4.1",  # Identity/tribal priming
        "D.4.1",  # Presupposition trap
        "F.3.1",  # Agenda masking
        "C.6.1",  # False balance
        "C.6.2",  # Weight equalization
        "C.3.6",  # Anecdote-as-proof
        "F.1.1",  # Incentive opacity
    }

    def __init__(self, config: LLMConfig | None = None):
        """
        Initialize semantic detector with LLM configuration.

        Args:
            config: LLM configuration. If None, attempts to auto-configure
                   from environment variables.
        """
        if config is None:
            config = self._auto_configure()
        self.config = config
        self._client: httpx.AsyncClient | None = None

    def _auto_configure(self) -> LLMConfig:
        """Auto-configure from environment variables."""
        # Try Anthropic first (Haiku is fast and good)
        if os.getenv("ANTHROPIC_API_KEY"):
            return LLMConfig(
                provider="anthropic",
                model="claude-3-5-haiku-20241022",
                api_key=os.getenv("ANTHROPIC_API_KEY"),
            )

        # Try OpenAI
        if os.getenv("OPENAI_API_KEY"):
            return LLMConfig(
                provider="openai",
                model="gpt-4o-mini",
                api_key=os.getenv("OPENAI_API_KEY"),
            )

        # Fall back to mock
        return LLMConfig(provider="mock", model="mock")

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.config.timeout)
        return self._client

    async def detect(
        self,
        text: str,
        segment: ArticleSegment = ArticleSegment.BODY,
    ) -> ScanResult:
        """
        Detect semantic manipulation patterns using LLM.

        Args:
            text: The text to analyze
            segment: Which article segment this text is from

        Returns:
            ScanResult with detected manipulation instances
        """
        start_time = time.perf_counter()

        if not text or not text.strip():
            return ScanResult(
                spans=[],
                segment=segment,
                text_length=0,
                scan_duration_ms=0.0,
                detector_source=DetectorSource.SEMANTIC,
            )

        # Truncate very long text to stay within token limits
        max_chars = 8000  # ~2000 tokens
        truncated_text = text[:max_chars] if len(text) > max_chars else text

        try:
            if self.config.provider == "mock":
                detections = self._mock_detect(truncated_text, segment)
            elif self.config.provider == "anthropic":
                detections = await self._anthropic_detect(truncated_text, segment)
            elif self.config.provider == "openai":
                detections = await self._openai_detect(truncated_text, segment)
            else:
                detections = []
        except Exception as e:
            # Log error but don't fail - return empty result
            print(f"Semantic detector error: {e}")
            detections = []

        scan_duration_ms = (time.perf_counter() - start_time) * 1000

        return ScanResult(
            spans=detections,
            segment=segment,
            text_length=len(text),
            scan_duration_ms=round(scan_duration_ms, 2),
            detector_source=DetectorSource.SEMANTIC,
        )

    def _mock_detect(self, text: str, segment: ArticleSegment) -> list[DetectionInstance]:
        """Mock detection for testing without LLM."""
        detections = []
        text_lower = text.lower()

        # Simple heuristic patterns for mock
        mock_patterns = [
            ("they did this to", "C.2.3", "Motive certainty"),
            ("want you to", "C.2.4", "Intent attribution"),
            ("real americans", "B.4.1", "Identity/tribal priming"),
            ("why did officials fail", "D.4.1", "Presupposition trap"),
        ]

        for pattern, type_id, rationale in mock_patterns:
            idx = text_lower.find(pattern)
            if idx != -1:
                manip_type = get_type(type_id)
                if manip_type:
                    detection = DetectionInstance(
                        type_id_primary=type_id,
                        segment=segment,
                        span_start=idx,
                        span_end=idx + len(pattern),
                        text=text[idx : idx + len(pattern)],
                        confidence=0.75,
                        severity=manip_type.default_severity,
                        detector_source=DetectorSource.SEMANTIC,
                        recommended_action=SpanAction.REWRITE,
                        rationale=rationale,
                    )
                    detections.append(detection)

        return detections

    async def _anthropic_detect(self, text: str, segment: ArticleSegment) -> list[DetectionInstance]:
        """Detect using Anthropic Claude API."""
        client = await self._get_client()

        prompt = DETECTION_PROMPT.format(text=text)

        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.config.model,
                "max_tokens": self.config.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
        )

        if response.status_code != 200:
            raise Exception(f"Anthropic API error: {response.status_code}")

        result = response.json()
        content = result.get("content", [{}])[0].get("text", "[]")

        return self._parse_llm_response(content, segment)

    async def _openai_detect(self, text: str, segment: ArticleSegment) -> list[DetectionInstance]:
        """Detect using OpenAI API."""
        client = await self._get_client()

        prompt = DETECTION_PROMPT.format(text=text)

        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "max_tokens": self.config.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
        )

        if response.status_code != 200:
            raise Exception(f"OpenAI API error: {response.status_code}")

        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "[]")

        return self._parse_llm_response(content, segment)

    def _parse_llm_response(self, content: str, segment: ArticleSegment) -> list[DetectionInstance]:
        """Parse LLM JSON response into DetectionInstance objects."""
        detections = []

        try:
            # Handle both array and object responses
            data = json.loads(content)
            if isinstance(data, dict):
                # OpenAI might wrap in object
                data = data.get("detections", data.get("results", []))
            if not isinstance(data, list):
                return []

            for item in data:
                type_id = item.get("type_id", "")

                # Validate type_id exists in taxonomy
                if type_id not in self.TARGET_TYPES:
                    continue

                manip_type = get_type(type_id)
                if not manip_type:
                    continue

                # Extract fields with validation
                span_start = int(item.get("span_start", 0))
                span_end = int(item.get("span_end", span_start + 1))
                text = str(item.get("text", ""))
                confidence = float(item.get("confidence", 0.5))
                rationale = str(item.get("rationale", ""))

                # Clamp confidence
                confidence = max(0.0, min(1.0, confidence))

                detection = DetectionInstance(
                    type_id_primary=type_id,
                    segment=segment,
                    span_start=span_start,
                    span_end=span_end,
                    text=text,
                    confidence=confidence,
                    severity=manip_type.default_severity,
                    detector_source=DetectorSource.SEMANTIC,
                    recommended_action=manip_type.default_action,
                    rationale=rationale,
                )
                detections.append(detection)

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"Failed to parse LLM response: {e}")

        return detections

    async def detect_title(self, title: str) -> ScanResult:
        """Convenience method to scan a title."""
        return await self.detect(title, segment=ArticleSegment.TITLE)

    async def detect_body(self, body: str) -> ScanResult:
        """Convenience method to scan body text."""
        return await self.detect(body, segment=ArticleSegment.BODY)

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Factory function for creating detector with specific provider
def create_semantic_detector(
    provider: str = "auto",
    model: str | None = None,
) -> SemanticDetector:
    """
    Create a semantic detector with specified provider.

    Args:
        provider: "anthropic", "openai", "mock", or "auto" (default)
        model: Model name (optional, uses default for provider)

    Returns:
        Configured SemanticDetector instance
    """
    if provider == "auto":
        return SemanticDetector(config=None)  # Auto-configure

    if provider == "anthropic":
        config = LLMConfig(
            provider="anthropic",
            model=model or "claude-3-5-haiku-20241022",
            api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
    elif provider == "openai":
        config = LLMConfig(
            provider="openai",
            model=model or "gpt-4o-mini",
            api_key=os.getenv("OPENAI_API_KEY"),
        )
    else:
        config = LLMConfig(provider="mock", model="mock")

    return SemanticDetector(config=config)
