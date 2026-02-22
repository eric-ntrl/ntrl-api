# app/utils/content_sanitizer.py
"""
Shared utilities for detecting and stripping content artifacts.

Handles:
- Perigon-style truncation markers: "...[1811 symbols]"
- Common web scraping artifacts: "RECOMMENDED STORIES", "Advertisement", etc.

This module centralizes cleanup so it isn't duplicated across fetchers
and ingestion code.
"""

import re

# Matches Perigon-style truncation markers: "...[1811 symbols]", "...[234 chars]", etc.
TRUNCATION_PATTERN = re.compile(r"\.\.\.\s*\[\d+\s*(?:symbols?|chars?|characters?)\]")

# Common scraping/API artifacts to strip from article bodies.
# Each pattern matches a full line (anchored with ^ and $, MULTILINE).
BODY_ARTIFACT_PATTERNS = [
    # Related/recommended content blocks
    re.compile(
        r"^(?:RECOMMENDED|RELATED|MORE|TRENDING|POPULAR)\s+(?:STORIES|ARTICLES|NEWS|READS|POSTS)\s*$",
        re.MULTILINE | re.IGNORECASE,
    ),
    # Advertising markers
    re.compile(r"^(?:Advertisement|Sponsored|ADVERTISEMENT|Ad)\s*$", re.MULTILINE | re.IGNORECASE),
    # Social sharing prompts
    re.compile(r"^(?:Share this|Share on|Follow us on|Subscribe to)\b.*$", re.MULTILINE | re.IGNORECASE),
    # Navigation/UI elements (standalone lines only)
    re.compile(
        r"^(?:Read more|Continue reading|Click here|Sign up|Log in|Subscribe)\s*$",
        re.MULTILINE | re.IGNORECASE,
    ),
    # Comment section headers
    re.compile(r"^(?:Comments|Leave a comment|Join the conversation)\s*$", re.MULTILINE | re.IGNORECASE),
    # Cookie/privacy notices
    re.compile(r"^(?:We use cookies|This site uses cookies|Accept cookies)\b.*$", re.MULTILINE | re.IGNORECASE),
]


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


def clean_body_artifacts(text: str) -> str:
    """Strip common scraping artifacts from article body text.

    Applied at ingestion time before paragraph deduplication. Removes
    navigation elements, ad markers, and related-content blocks that
    leak through web scrapers and API content.
    """
    for pattern in BODY_ARTIFACT_PATTERNS:
        text = pattern.sub("", text)
    # Collapse excessive blank lines left by removed artifacts
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
