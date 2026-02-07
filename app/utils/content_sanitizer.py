# app/utils/content_sanitizer.py
"""
Shared utilities for detecting and stripping content truncation markers.

Perigon (and potentially other API sources) truncate article bodies when
full content is gated behind subscription tiers. The truncation marker
looks like: "...[1811 symbols]" or "...[234 chars]" or "...[500 characters]"

This module centralizes the regex so it isn't duplicated across fetchers
and ingestion code.
"""

import re

# Matches Perigon-style truncation markers: "...[1811 symbols]", "...[234 chars]", etc.
TRUNCATION_PATTERN = re.compile(r"\.\.\.\s*\[\d+\s*(?:symbols?|chars?|characters?)\]")


def has_truncation_markers(body: str | None) -> bool:
    """Check if text contains API truncation markers."""
    if not body:
        return False
    return bool(TRUNCATION_PATTERN.search(body))


def strip_truncation_markers(body: str | None) -> str | None:
    """Remove API truncation markers from text."""
    if not body:
        return body
    return TRUNCATION_PATTERN.sub("", body).rstrip()
