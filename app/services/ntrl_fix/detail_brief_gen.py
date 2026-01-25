# app/services/ntrl_fix/detail_brief_gen.py
"""
Detail Brief Generator: Creates a short synthesis of the article.

This generator produces a condensed version of the article (2-4 paragraphs)
that captures the key facts without manipulation. It's used for the
"brief" view in the app.

Key features:
- Extracts core facts and narrative
- Removes all manipulation and filler
- Maintains journalistic accuracy
- ~200-400 words output
"""

import json
import os
import time
from typing import Optional
from dataclasses import dataclass
import httpx

from .types import GeneratorConfig
from ..ntrl_scan.types import MergedScanResult


DETAIL_BRIEF_PROMPT = """You are a professional news synthesizer. Create a brief, factual summary of this article.

ORIGINAL ARTICLE:
{body}

MANIPULATION DETECTED (for context - these have been flagged):
{manipulation_summary}

YOUR TASK:
Write a 2-4 paragraph summary (200-400 words) that:
1. Captures the core news event and key facts
2. Includes all important names, numbers, dates, and quotes
3. Uses neutral, objective language
4. Removes all sensationalism, emotional manipulation, and filler
5. Maintains chronological or logical flow

STYLE GUIDELINES:
- Start with the most important fact (inverted pyramid)
- Use active voice when possible
- Include direct quotes if they add substance
- End with relevant context or next steps

CRITICAL RULES:
- NEVER invent facts not in the original
- NEVER upgrade certainty (alleged → confirmed)
- NEVER remove safety-relevant information
- Preserve all direct quotes verbatim

Return a JSON object:
{{
  "brief": "The synthesized summary text...",
  "key_facts": ["fact 1", "fact 2", "fact 3"],
  "word_count": 250
}}

Return ONLY valid JSON."""


@dataclass
class DetailBriefResult:
    """Result from detail brief generation."""
    text: str
    key_facts: list[str]
    word_count: int
    processing_time_ms: float = 0.0


class DetailBriefGenerator:
    """
    Generates brief article synthesis.

    Creates a condensed version of the article that captures key facts
    while removing manipulation and unnecessary filler.
    """

    def __init__(self, config: Optional[GeneratorConfig] = None):
        """Initialize with configuration."""
        self.config = config or GeneratorConfig()
        self._client: Optional[httpx.AsyncClient] = None

        if self.config.provider == "auto":
            self._auto_configure()

    def _auto_configure(self):
        """Auto-configure from environment."""
        if os.getenv("ANTHROPIC_API_KEY"):
            self.config.provider = "anthropic"
            self.config.model = self.config.model or "claude-3-5-sonnet-20241022"
        elif os.getenv("OPENAI_API_KEY"):
            self.config.provider = "openai"
            self.config.model = self.config.model or "gpt-4o"
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
        scan_result: Optional[MergedScanResult] = None,
    ) -> DetailBriefResult:
        """
        Generate brief synthesis of article.

        Args:
            body: Original article body text
            scan_result: Optional detection results for context

        Returns:
            DetailBriefResult with synthesized brief
        """
        start_time = time.perf_counter()

        if not body or not body.strip():
            return DetailBriefResult(
                text="",
                key_facts=[],
                word_count=0,
                processing_time_ms=0.0
            )

        # Create manipulation summary for context
        manipulation_summary = self._create_manipulation_summary(scan_result)

        # Generate based on provider
        if self.config.provider == "mock":
            result = self._mock_generate(body)
        elif self.config.provider == "openai":
            result = await self._openai_generate(body, manipulation_summary)
        elif self.config.provider == "anthropic":
            result = await self._anthropic_generate(body, manipulation_summary)
        else:
            result = self._mock_generate(body)

        result.processing_time_ms = (time.perf_counter() - start_time) * 1000
        return result

    def _create_manipulation_summary(
        self,
        scan_result: Optional[MergedScanResult]
    ) -> str:
        """Create brief summary of detected manipulation for context."""
        if not scan_result or not scan_result.spans:
            return "No significant manipulation detected."

        # Summarize by category
        by_category: dict[str, int] = {}
        for span in scan_result.spans:
            cat = span.type_id_primary[0]  # e.g., "A" from "A.1.1"
            by_category[cat] = by_category.get(cat, 0) + 1

        category_names = {
            "A": "attention/engagement tactics",
            "B": "emotional manipulation",
            "C": "cognitive/epistemic issues",
            "D": "linguistic framing",
            "E": "structural/editorial issues",
            "F": "incentive/meta issues",
        }

        parts = []
        for cat, count in sorted(by_category.items()):
            name = category_names.get(cat, f"category {cat}")
            parts.append(f"{count} {name}")

        return f"Detected: {', '.join(parts)}"

    def _mock_generate(self, body: str) -> DetailBriefResult:
        """Mock generation for testing."""
        # Extract first few sentences as a simple mock
        sentences = body.replace('\n', ' ').split('. ')
        brief_sentences = sentences[:5]  # Take first 5 sentences

        # Simple cleanup
        brief = '. '.join(brief_sentences)
        if brief and not brief.endswith('.'):
            brief += '.'

        # Extract potential key facts (sentences with numbers or proper nouns)
        key_facts = []
        for sent in brief_sentences[:3]:
            if any(c.isdigit() for c in sent) or any(w[0].isupper() for w in sent.split() if w):
                key_facts.append(sent.strip())

        words = brief.split()
        return DetailBriefResult(
            text=brief,
            key_facts=key_facts[:3],
            word_count=len(words)
        )

    async def _openai_generate(
        self,
        body: str,
        manipulation_summary: str
    ) -> DetailBriefResult:
        """Generate using OpenAI API."""
        client = await self._get_client()

        prompt = DETAIL_BRIEF_PROMPT.format(
            body=body,
            manipulation_summary=manipulation_summary
        )

        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "max_tokens": 1024,
                "temperature": self.config.temperature,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            },
        )

        if response.status_code != 200:
            raise Exception(f"OpenAI API error: {response.status_code}")

        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")

        return self._parse_response(content, body)

    async def _anthropic_generate(
        self,
        body: str,
        manipulation_summary: str
    ) -> DetailBriefResult:
        """Generate using Anthropic API."""
        client = await self._get_client()

        prompt = DETAIL_BRIEF_PROMPT.format(
            body=body,
            manipulation_summary=manipulation_summary
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
                "max_tokens": 1024,
                "temperature": self.config.temperature,
                "messages": [{"role": "user", "content": prompt}],
            },
        )

        if response.status_code != 200:
            raise Exception(f"Anthropic API error: {response.status_code}")

        result = response.json()
        content = result.get("content", [{}])[0].get("text", "{}")

        return self._parse_response(content, body)

    def _parse_response(self, content: str, fallback_body: str) -> DetailBriefResult:
        """Parse LLM response."""
        try:
            data = json.loads(content)
            text = data.get("brief", "")
            return DetailBriefResult(
                text=text,
                key_facts=data.get("key_facts", []),
                word_count=data.get("word_count", len(text.split()))
            )
        except json.JSONDecodeError:
            # Fallback to mock
            return self._mock_generate(fallback_body)

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
