# app/services/url_validator.py
"""
URL validation service for the NTRL pipeline.

Validates article URLs during ingestion to detect broken links (404, 410, 403)
before they reach the brief. Results are stored on StoryRaw and checked by the
QC gate's url_reachable check.

Usage:
    result = validate_url("https://example.com/article")
    # result.status: "reachable", "unreachable", "timeout", "redirect"
"""

import ipaddress
import logging
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is in a private/reserved range."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    except ValueError:
        return False


def _check_ssrf(url: str) -> None:
    """Block requests to private/internal IP addresses."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return
        # Resolve DNS and check all returned IPs
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if _is_private_ip(ip):
                raise ValueError(f"SSRF blocked: {hostname} resolves to private IP {ip}")
    except socket.gaierror:
        pass  # DNS resolution failure will be caught by httpx
    except ValueError:
        raise


# Rate limiting: minimum seconds between requests to the same domain
_DOMAIN_RATE_LIMIT_S = 0.5
_MAX_DOMAIN_ENTRIES = 1000
_last_request_by_domain: dict[str, float] = {}


@dataclass
class URLValidationResult:
    """Result from validating a single URL."""

    status: str  # "reachable", "unreachable", "timeout", "redirect"
    http_code: int | None = None
    final_url: str | None = None
    response_time_ms: int = 0


def _extract_domain(url: str) -> str:
    """Extract domain from URL for rate limiting."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return parsed.netloc or ""
    except Exception:
        return ""


def _rate_limit(domain: str) -> None:
    """Sleep if we've recently hit this domain."""
    if not domain:
        return
    last_time = _last_request_by_domain.get(domain, 0)
    elapsed = time.monotonic() - last_time
    if elapsed < _DOMAIN_RATE_LIMIT_S:
        time.sleep(_DOMAIN_RATE_LIMIT_S - elapsed)
    _last_request_by_domain[domain] = time.monotonic()
    if len(_last_request_by_domain) > _MAX_DOMAIN_ENTRIES:
        sorted_domains = sorted(_last_request_by_domain, key=_last_request_by_domain.get)
        for d in sorted_domains[: len(sorted_domains) // 2]:
            del _last_request_by_domain[d]


def validate_url(url: str, timeout: float = 5.0) -> URLValidationResult:
    """
    Validate a URL by making an HTTP request.

    Strategy:
    1. Try HEAD request first (fast, low bandwidth)
    2. Fall back to GET if HEAD returns 405 Method Not Allowed
    3. Follow redirects (max 3 hops)

    Args:
        url: The URL to validate
        timeout: Request timeout in seconds

    Returns:
        URLValidationResult with status, HTTP code, and final URL
    """
    if not url or not url.strip():
        return URLValidationResult(status="unreachable", http_code=None)

    # SSRF protection: block requests to private/internal IPs
    try:
        _check_ssrf(url)
    except ValueError as e:
        logger.warning(f"[URL_VALIDATOR] {e}")
        return URLValidationResult(status="unreachable", http_code=None)

    domain = _extract_domain(url)
    _rate_limit(domain)

    start_ms = int(time.monotonic() * 1000)

    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            max_redirects=3,
            headers={
                "User-Agent": "NTRL-LinkChecker/1.0 (https://ntrl.news)",
            },
        ) as client:
            # Try HEAD first (fast)
            try:
                response = client.head(url)
            except httpx.HTTPStatusError:
                response = client.get(url)

            # Fall back to GET if HEAD returned 405
            if response.status_code == 405:
                response = client.get(url)

            elapsed_ms = int(time.monotonic() * 1000) - start_ms

            # Determine final URL (after redirects)
            final_url = str(response.url) if str(response.url) != url else None

            # Classify result
            if 200 <= response.status_code < 400:
                status = "redirect" if final_url else "reachable"
            elif response.status_code in (404, 410, 403):
                status = "unreachable"
            else:
                # 5xx or other errors — treat as temporary
                status = "unreachable"

            return URLValidationResult(
                status=status,
                http_code=response.status_code,
                final_url=final_url,
                response_time_ms=elapsed_ms,
            )

    except httpx.TimeoutException:
        elapsed_ms = int(time.monotonic() * 1000) - start_ms
        return URLValidationResult(
            status="timeout",
            http_code=None,
            response_time_ms=elapsed_ms,
        )
    except (httpx.ConnectError, httpx.NetworkError) as e:
        elapsed_ms = int(time.monotonic() * 1000) - start_ms
        logger.debug(f"[URL_VALIDATOR] Network error for {url}: {e}")
        return URLValidationResult(
            status="unreachable",
            http_code=None,
            response_time_ms=elapsed_ms,
        )
    except Exception as e:
        elapsed_ms = int(time.monotonic() * 1000) - start_ms
        logger.warning(f"[URL_VALIDATOR] Unexpected error validating {url}: {e}")
        return URLValidationResult(
            status="unreachable",
            http_code=None,
            response_time_ms=elapsed_ms,
        )


def validate_and_store(
    db: Session,
    story_raw: models.StoryRaw,
) -> URLValidationResult:
    """
    Validate a story's original URL and store results on the StoryRaw record.

    Args:
        db: Database session
        story_raw: The StoryRaw record to validate

    Returns:
        URLValidationResult
    """
    result = validate_url(story_raw.original_url)

    story_raw.url_status = result.status
    story_raw.url_checked_at = datetime.now(UTC)
    story_raw.url_http_status = result.http_code
    story_raw.url_final_location = result.final_url

    logger.info(
        f"[URL_VALIDATOR] {result.status} ({result.http_code}) "
        f"{story_raw.original_url[:80]} [{result.response_time_ms}ms]"
    )

    return result


def validate_batch(
    db: Session,
    limit: int = 100,
) -> dict:
    """
    Validate URLs for stories that haven't been checked yet.

    Args:
        db: Database session
        limit: Max stories to check per batch

    Returns:
        Dict with validation stats
    """
    # Find stories without URL validation
    stories = (
        db.query(models.StoryRaw)
        .filter(
            models.StoryRaw.url_status.is_(None),
            models.StoryRaw.original_url.isnot(None),
        )
        .order_by(models.StoryRaw.ingested_at.desc())
        .limit(limit)
        .all()
    )

    stats = {
        "total": len(stories),
        "reachable": 0,
        "unreachable": 0,
        "timeout": 0,
        "redirect": 0,
    }

    chunk_size = 20
    for i, story in enumerate(stories):
        result = validate_and_store(db, story)
        stats[result.status] = stats.get(result.status, 0) + 1
        if (i + 1) % chunk_size == 0:
            db.commit()

    db.commit()

    logger.info(
        f"[URL_VALIDATOR] Batch complete: {stats['total']} checked, "
        f"{stats['reachable']} reachable, {stats['unreachable']} unreachable, "
        f"{stats['timeout']} timeout, {stats['redirect']} redirect"
    )

    return stats
