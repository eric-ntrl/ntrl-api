# app/services/ntrl_fix/feed_outputs_gen.py
"""
Feed Outputs Generator: Creates neutralized title and summary for feeds.

This generator produces the short-form content used in feed views:
- feed_title: Neutralized headline (50-80 chars)
- feed_summary: Brief summary (100-150 chars)

Uses a fast model (Haiku/4o-mini) since this is a simple task.
"""

import json
import os
import time
from typing import Optional
from dataclasses import dataclass
import httpx

from .types import GeneratorConfig
from ..ntrl_scan.types import MergedScanResult


FEED_OUTPUTS_PROMPT = """Generate a neutral headline and summary for this news article.

ARTICLE BODY:
{body}

ORIGINAL TITLE (may contain manipulation):
{original_title}

TITLE MANIPULATION DETECTED:
{title_issues}

REQUIREMENTS:
1. feed_title: 50-80 characters, neutral, factual, no sensationalism
2. feed_summary: 100-150 characters, captures core news, no clickbait

RULES:
- Remove ALL urgency markers (BREAKING, URGENT, JUST IN)
- Remove rage verbs (slams, blasts, destroys)
- Remove clickbait patterns (you won't believe, shocking)
- Preserve key facts: who, what, where, when
- Use active voice when possible
- Never add information not in the article

EXAMPLES:
Bad: "BREAKING: Senator SLAMS opponent in devastating attack"
Good: "Senator criticizes opponent's policy proposal"

Bad: "You Won't Believe What This CEO Just Did"
Good: "Tech CEO announces major company restructuring"

Return JSON:
{{
  "feed_title": "The neutral headline...",
  "feed_summary": "Brief neutral summary of the key news..."
}}

Return ONLY valid JSON."""


@dataclass
class FeedOutputsResult:
    """Result from feed outputs generation."""
    feed_title: str
    feed_summary: str
    processing_time_ms: float = 0.0


class FeedOutputsGenerator:
    """
    Generates neutralized feed title and summary.

    Uses a fast model for this simple task to minimize latency.
    """

    def __init__(self, config: Optional[GeneratorConfig] = None):
        """Initialize with configuration."""
        self.config = config or GeneratorConfig()
        self._client: Optional[httpx.AsyncClient] = None

        if self.config.provider == "auto":
            self._auto_configure()

    def _auto_configure(self):
        """Auto-configure with fast models."""
        if os.getenv("OPENAI_API_KEY"):
            self.config.provider = "openai"
            self.config.model = self.config.model or "gpt-4o-mini"
        elif os.getenv("ANTHROPIC_API_KEY"):
            self.config.provider = "anthropic"
            self.config.model = self.config.model or "claude-3-5-haiku-20241022"
        else:
            self.config.provider = "mock"

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.config.timeout)
        return self._client

    async def generate(
        self,
        body: str,
        original_title: str = "",
        title_scan: Optional[MergedScanResult] = None,
    ) -> FeedOutputsResult:
        """
        Generate neutralized feed title and summary.

        Args:
            body: Article body text
            original_title: Original article title
            title_scan: Detection results for title

        Returns:
            FeedOutputsResult with feed_title and feed_summary
        """
        start_time = time.perf_counter()

        if not body or not body.strip():
            return FeedOutputsResult(
                feed_title="",
                feed_summary="",
                processing_time_ms=0.0
            )

        # Summarize title issues for context
        title_issues = self._summarize_title_issues(title_scan)

        # Generate based on provider
        if self.config.provider == "mock":
            result = self._mock_generate(body, original_title)
        elif self.config.provider == "openai":
            result = await self._openai_generate(body, original_title, title_issues)
        elif self.config.provider == "anthropic":
            result = await self._anthropic_generate(body, original_title, title_issues)
        else:
            result = self._mock_generate(body, original_title)

        result.processing_time_ms = (time.perf_counter() - start_time) * 1000
        return result

    def _summarize_title_issues(
        self,
        title_scan: Optional[MergedScanResult]
    ) -> str:
        """Summarize issues found in title."""
        if not title_scan or not title_scan.spans:
            return "None detected"

        issues = []
        for span in title_scan.spans:
            issues.append(f"{span.type_id_primary}: \"{span.text}\"")

        return "; ".join(issues[:5])

    def _mock_generate(
        self,
        body: str,
        original_title: str
    ) -> FeedOutputsResult:
        """Mock generation for testing."""
        # Clean up title
        title = original_title or ""

        # Remove common manipulation patterns
        removals = [
            "BREAKING:", "BREAKING ", "JUST IN:", "URGENT:",
            "DEVELOPING:", "ALERT:", "EXCLUSIVE:",
            "You won't believe", "You Won't Believe",
        ]
        for r in removals:
            title = title.replace(r, "")

        # Replace rage verbs
        replacements = {
            " slams ": " criticizes ",
            " SLAMS ": " criticizes ",
            " blasts ": " criticizes ",
            " BLASTS ": " criticizes ",
            " destroys ": " challenges ",
            " DESTROYS ": " challenges ",
            " devastating ": " strong ",
            " shocking ": " notable ",
            " SHOCKING ": " notable ",
        }
        for old, new in replacements.items():
            title = title.replace(old, new)

        title = title.strip()

        # If no title, extract from first sentence
        if not title:
            first_sentence = body.split('.')[0].strip()
            title = first_sentence[:80] if first_sentence else "News Update"

        # Truncate if too long
        if len(title) > 80:
            title = title[:77] + "..."

        # Generate summary from first ~150 chars of body
        summary = body[:150].strip()
        if len(summary) >= 150:
            # Find last complete word
            last_space = summary.rfind(' ')
            if last_space > 100:
                summary = summary[:last_space] + "..."

        return FeedOutputsResult(
            feed_title=title,
            feed_summary=summary
        )

    async def _openai_generate(
        self,
        body: str,
        original_title: str,
        title_issues: str
    ) -> FeedOutputsResult:
        """Generate using OpenAI API."""
        client = await self._get_client()

        # Truncate body for prompt efficiency
        body_truncated = body[:2000] if len(body) > 2000 else body

        prompt = FEED_OUTPUTS_PROMPT.format(
            body=body_truncated,
            original_title=original_title or "(none provided)",
            title_issues=title_issues
        )

        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "max_tokens": 256,
                "temperature": 0.2,  # More deterministic for titles
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
        )

        if response.status_code != 200:
            raise Exception(f"OpenAI API error: {response.status_code}")

        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")

        return self._parse_response(content, body, original_title)

    async def _anthropic_generate(
        self,
        body: str,
        original_title: str,
        title_issues: str
    ) -> FeedOutputsResult:
        """Generate using Anthropic API."""
        client = await self._get_client()

        body_truncated = body[:2000] if len(body) > 2000 else body

        prompt = FEED_OUTPUTS_PROMPT.format(
            body=body_truncated,
            original_title=original_title or "(none provided)",
            title_issues=title_issues
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
                "max_tokens": 256,
                "temperature": 0.2,
                "messages": [{"role": "user", "content": prompt}],
            },
        )

        if response.status_code != 200:
            raise Exception(f"Anthropic API error: {response.status_code}")

        result = response.json()
        content = result.get("content", [{}])[0].get("text", "{}")

        return self._parse_response(content, body, original_title)

    def _parse_response(
        self,
        content: str,
        body: str,
        original_title: str
    ) -> FeedOutputsResult:
        """Parse LLM response."""
        try:
            data = json.loads(content)
            return FeedOutputsResult(
                feed_title=data.get("feed_title", ""),
                feed_summary=data.get("feed_summary", "")
            )
        except json.JSONDecodeError:
            return self._mock_generate(body, original_title)

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
