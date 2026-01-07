# app/llm/__init__.py
"""
LLM provider abstraction layer.

Usage:
    from app.llm import get_llm_provider

    provider = get_llm_provider()  # Uses default from env
    result = provider.generate_neutral_summary(title, description, body)
"""

from __future__ import annotations

import os
from typing import Optional

from app.llm.base import (
    BiasSpan,
    LLMProvider,
    NeutralityAnalysisResult,
    NeutralSummaryResult,
)

__all__ = [
    "BiasSpan",
    "LLMProvider",
    "NeutralityAnalysisResult",
    "NeutralSummaryResult",
    "get_llm_provider",
]


def get_llm_provider(
    provider_name: Optional[str] = None,
    **kwargs,
) -> LLMProvider:
    """
    Factory function to get an LLM provider instance.

    Args:
        provider_name: Provider to use ('openai', 'anthropic', etc.)
                      If not provided, uses LLM_PROVIDER env var (default: 'openai')
        **kwargs: Additional arguments passed to the provider constructor

    Returns:
        Configured LLMProvider instance

    Example:
        provider = get_llm_provider()  # Uses default
        provider = get_llm_provider("openai", model="gpt-4o")
    """
    name = provider_name or os.getenv("LLM_PROVIDER", "openai")
    name = name.lower().strip()

    if name == "openai":
        from app.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(**kwargs)

    # Future: Add more providers here
    # elif name == "anthropic":
    #     from app.llm.anthropic_provider import AnthropicProvider
    #     return AnthropicProvider(**kwargs)

    raise ValueError(
        f"Unknown LLM provider: {name}. Available: openai"
    )
