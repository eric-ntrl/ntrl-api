# app/llm/base.py
"""
Base interface for LLM providers.
Allows swapping between OpenAI, Anthropic, or other providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class NeutralSummaryResult:
    """Result from neutral summary generation."""
    neutral_title: str
    neutral_summary_short: str
    neutral_summary_extended: Optional[str] = None


@dataclass
class BiasSpan:
    """A detected bias span in text."""
    start: int
    end: int
    text: str
    label: str
    severity: float
    term: str
    field: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "label": self.label,
            "severity": self.severity,
            "term": self.term,
            "field": self.field,
        }


@dataclass
class NeutralityAnalysisResult:
    """Result from neutrality analysis."""
    neutrality_score: int  # 0-100
    bias_terms: List[str]
    bias_spans: List[BiasSpan]
    reading_level: int
    political_lean: float  # -1.0 (left) to 1.0 (right)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "neutrality_score": self.neutrality_score,
            "bias_terms": self.bias_terms,
            "bias_spans": [span.to_dict() for span in self.bias_spans],
            "reading_level": self.reading_level,
            "political_lean": self.political_lean,
        }


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider name (e.g., 'openai', 'anthropic')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model being used (e.g., 'gpt-4o-mini')."""
        pass

    @abstractmethod
    def generate_neutral_summary(
        self,
        title: str,
        description: Optional[str],
        body: Optional[str],
    ) -> NeutralSummaryResult:
        """
        Generate a neutral summary of the article.

        Args:
            title: Original article title
            description: Optional article description/excerpt
            body: Optional full article body

        Returns:
            NeutralSummaryResult with neutral title and summaries
        """
        pass

    @abstractmethod
    def analyze_neutrality(
        self,
        title: str,
        description: Optional[str],
        body: Optional[str],
    ) -> NeutralityAnalysisResult:
        """
        Analyze the article for bias and neutrality.

        Args:
            title: Original article title
            description: Optional article description/excerpt
            body: Optional full article body

        Returns:
            NeutralityAnalysisResult with scores and bias detection
        """
        pass
