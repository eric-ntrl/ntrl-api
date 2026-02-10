# app/utils/content_cleaner.py
"""
Content cleaning pipeline for article bodies.

Removes UI artifacts, ads, CTAs, social sharing text, cookie notices, and
other non-journalistic content that survives body extraction. Applied BEFORE
neutralization and classification but NOT before span detection (spans must
reference the original body for position integrity).

Design constraints:
- Only strip content where the ENTIRE line is an artifact (paragraph-level)
- Never strip text inside quotation marks
- Never strip journalistic attribution phrases
- Feature-flagged via CONTENT_CLEANING_ENABLED env var
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


def _is_enabled() -> bool:
    """Check if content cleaning is enabled via env var."""
    return os.getenv("CONTENT_CLEANING_ENABLED", "true").lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Attribution whitelist — never strip lines containing these
# ---------------------------------------------------------------------------

ATTRIBUTION_PHRASES = [
    "according to",
    "as reported by",
    "contributed to this report",
    "spoke on condition of",
    "sources say",
    "sources said",
    "a spokesperson said",
    "a spokesperson for",
    "in a statement",
    "told reporters",
    "in an interview",
    "reporting by",
    "editing by",
    "writing by",
    "additional reporting by",
]

# ---------------------------------------------------------------------------
# Pattern categories — each matches ENTIRE stripped lines only
# ---------------------------------------------------------------------------

# Category 1: CTA / navigation
CTA_PATTERNS = [
    re.compile(r"^read\s+more\.?$", re.IGNORECASE),
    re.compile(r"^read\s+the\s+full\s+(story|article|report)\.?$", re.IGNORECASE),
    re.compile(r"^click\s+here\.?$", re.IGNORECASE),
    re.compile(r"^tap\s+here\.?$", re.IGNORECASE),
    re.compile(r"^watch\s+now\.?$", re.IGNORECASE),
    re.compile(r"^listen\s+now\.?$", re.IGNORECASE),
    re.compile(r"^subscribe\.?$", re.IGNORECASE),
    re.compile(r"^subscribe\s+now\.?$", re.IGNORECASE),
    re.compile(r"^continue\s+reading\.?$", re.IGNORECASE),
    re.compile(r"^see\s+also:?$", re.IGNORECASE),
    re.compile(r"^learn\s+more\.?$", re.IGNORECASE),
    re.compile(r"^download\s+(the\s+)?app\.?$", re.IGNORECASE),
]

# Category 2: Newsletter / subscription
NEWSLETTER_PATTERNS = [
    re.compile(r"^sign\s+up\s+for\b.*$", re.IGNORECASE),
    re.compile(r"^get\s+our\s+newsletter\.?$", re.IGNORECASE),
    re.compile(r"^subscribe\s+to\s+our\s+newsletter\.?$", re.IGNORECASE),
    re.compile(r"^enter\s+your\s+email.*$", re.IGNORECASE),
    re.compile(r"^join\s+our\s+mailing\s+list\.?$", re.IGNORECASE),
    re.compile(r"^never\s+miss\s+a\s+story\.?$", re.IGNORECASE),
    re.compile(r"^stay\s+informed\.?$", re.IGNORECASE),
    re.compile(r"^get\s+the\s+(latest|morning|evening|daily)\b.*newsletter.*$", re.IGNORECASE),
]

# Category 3: Social / sharing
SOCIAL_PATTERNS = [
    re.compile(r"^share\s+(this\s+)?(on|via)\s+\w+\.?$", re.IGNORECASE),
    re.compile(r"^follow\s+us\s+on\s+\w+\.?$", re.IGNORECASE),
    re.compile(r"^tweet\s+this\.?$", re.IGNORECASE),
    re.compile(r"^share\s+on\s+(facebook|twitter|x|linkedin|instagram|whatsapp|reddit)\.?$", re.IGNORECASE),
    re.compile(r"^like\s+us\s+on\s+facebook\.?$", re.IGNORECASE),
    re.compile(r"^find\s+us\s+on\s+\w+\.?$", re.IGNORECASE),
]

# Category 4: Cookie / GDPR
COOKIE_PATTERNS = [
    re.compile(r"^we\s+use\s+cookies\b.*$", re.IGNORECASE),
    re.compile(r"^this\s+(site|website)\s+uses\s+cookies\b.*$", re.IGNORECASE),
    re.compile(r"^accept\s+all\s+cookies\.?$", re.IGNORECASE),
    re.compile(r"^manage\s+cookie\s+(preferences|settings)\.?$", re.IGNORECASE),
    re.compile(r"^by\s+continuing\s+to\s+(use|browse)\s+this\s+site\b.*$", re.IGNORECASE),
]

# Category 5: Related content
RELATED_PATTERNS = [
    re.compile(r"^you\s+might\s+also\s+like:?$", re.IGNORECASE),
    re.compile(r"^related\s+(stories|articles|content|topics):?$", re.IGNORECASE),
    re.compile(r"^more\s+(from|on)\s+this\s+(topic|story|section):?$", re.IGNORECASE),
    re.compile(r"^recommended\s+(for\s+you|stories|reading):?$", re.IGNORECASE),
    re.compile(r"^trending\s+(now|stories):?$", re.IGNORECASE),
    re.compile(r"^popular\s+(stories|articles):?$", re.IGNORECASE),
    re.compile(r"^most\s+read:?$", re.IGNORECASE),
    re.compile(r"^don'?t\s+miss:?$", re.IGNORECASE),
]

# Category 6: Ad markers
AD_PATTERNS = [
    re.compile(r"^advertisement\.?$", re.IGNORECASE),
    re.compile(r"^sponsored\s+(content|by\b.*)$", re.IGNORECASE),
    re.compile(r"^ad$", re.IGNORECASE),
    re.compile(r"^promoted\s+content\.?$", re.IGNORECASE),
    re.compile(r"^paid\s+(content|partnership|post)\.?$", re.IGNORECASE),
    re.compile(r"^advertise\s+with\s+us\.?$", re.IGNORECASE),
]

# Category 7: Author bio CTAs (short trailing lines with @handles or "Follow" CTAs)
AUTHOR_BIO_PATTERNS = [
    re.compile(r"^follow\s+@\w+\.?$", re.IGNORECASE),
    re.compile(r"^@\w+$"),
    re.compile(r"^follow\s+\w+\s+on\s+(twitter|x|instagram)\.?$", re.IGNORECASE),
]

# Category 8: Video/embed references — transform, don't strip
VIDEO_PATTERNS = [
    re.compile(r"^\[?\s*video\s*:?\s*.+\]?$", re.IGNORECASE),
    re.compile(r"^watch\s+the\s+(video|clip|full\s+video)\s*(below|above)?\.?$", re.IGNORECASE),
    re.compile(r"^play\s+video\.?$", re.IGNORECASE),
    re.compile(r"^\[?\s*embed\s*:?\s*.+\]?$", re.IGNORECASE),
]

# All non-video pattern categories with labels for logging
STRIP_CATEGORIES = [
    ("cta", CTA_PATTERNS),
    ("newsletter", NEWSLETTER_PATTERNS),
    ("social", SOCIAL_PATTERNS),
    ("cookie", COOKIE_PATTERNS),
    ("related", RELATED_PATTERNS),
    ("ad", AD_PATTERNS),
    ("author_bio", AUTHOR_BIO_PATTERNS),
]


def _is_inside_quotes(line: str) -> bool:
    """Check if the line content appears to be inside quotation marks."""
    stripped = line.strip()
    # Check for surrounding quotes (straight or curly)
    if (
        (stripped.startswith('"') and stripped.endswith('"'))
        or (stripped.startswith("\u201c") and stripped.endswith("\u201d"))
        or (stripped.startswith("'") and stripped.endswith("'"))
    ):
        return True
    return False


def _contains_attribution(line: str) -> bool:
    """Check if line contains journalistic attribution phrases."""
    line_lower = line.lower()
    return any(phrase in line_lower for phrase in ATTRIBUTION_PHRASES)


def _match_strip_category(stripped_line: str) -> str | None:
    """Return the category name if the line matches a strip pattern, else None."""
    for category_name, patterns in STRIP_CATEGORIES:
        for pattern in patterns:
            if pattern.match(stripped_line):
                return category_name
    return None


def _match_video(stripped_line: str) -> bool:
    """Check if line matches a video/embed reference."""
    return any(p.match(stripped_line) for p in VIDEO_PATTERNS)


# Regex to collapse 3+ consecutive newlines into 2
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def clean_article_body(text: str | None) -> str:
    """
    Clean article body by removing UI artifacts, ads, and other non-journalistic content.

    Rules:
    - Only removes lines where the ENTIRE line matches an artifact pattern
    - Never removes text inside quotation marks
    - Never removes lines containing journalistic attribution
    - Transforms video references into informational notes
    - Normalizes excessive blank lines

    Args:
        text: Raw article body text

    Returns:
        Cleaned article body, or original text if cleaning is disabled/unnecessary
    """
    if not text:
        return text or ""

    if not _is_enabled():
        return text

    removed_counts: dict[str, int] = {}
    cleaned_lines: list[str] = []

    for line in text.split("\n"):
        stripped = line.strip()

        # Keep empty lines (will normalize later)
        if not stripped:
            cleaned_lines.append(line)
            continue

        # Guard: never touch lines inside quotation marks
        if _is_inside_quotes(stripped):
            cleaned_lines.append(line)
            continue

        # Guard: never touch lines with journalistic attribution
        if _contains_attribution(stripped):
            cleaned_lines.append(line)
            continue

        # Check video/embed — transform, don't strip
        if _match_video(stripped):
            cleaned_lines.append("[This article includes multimedia content at the original source.]")
            removed_counts["video_transform"] = removed_counts.get("video_transform", 0) + 1
            continue

        # Check strip categories
        category = _match_strip_category(stripped)
        if category:
            removed_counts[category] = removed_counts.get(category, 0) + 1
            continue  # Skip this line

        # Keep the line
        cleaned_lines.append(line)

    result = "\n".join(cleaned_lines)

    # Normalize: collapse 3+ consecutive newlines to 2
    result = _MULTI_NEWLINE.sub("\n\n", result).strip()

    total_removed = sum(removed_counts.values())
    if total_removed > 0:
        counts_str = ", ".join(f"{k}: {v}" for k, v in sorted(removed_counts.items()))
        logger.info(f"[CONTENT_CLEAN] Removed {total_removed} lines ({counts_str})")

    return result
