# app/rss_ingest.py

from __future__ import annotations

import json
import re
import ssl
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import feedparser
from sqlalchemy.orm import Session

from app import models
from app.pipeline_service import run_neutral_pipeline


# ---------------------------------------------------------------------------
# AP config
# ---------------------------------------------------------------------------

AP_TOP_NEWS = {
    "source_name": "AP News",
    "homepage_url": "https://apnews.com",
    # RSS endpoints have been flaky / non-resolving in your environment.
    # We still try a couple, but we ALWAYS fall back to scraping the tag page.
    "rss_candidates": [
        "https://rss.apnews.com/apf-topnews",  # (often fails to resolve)
        "https://apnews.com/rss/apf-topnews",  # (was 404 when tested)
    ],
    "tag_fallback_url": "https://apnews.com/tag/apf-topnews",
}


# ---------------------------------------------------------------------------
# Small HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------

def _http_get(url: str, *, timeout: int = 20) -> Tuple[str, str]:
    """
    Fetch URL using stdlib urllib (no extra deps).
    Returns (text, final_url).
    """
    headers = {
        "User-Agent": "NeutralNewsBackend/0.1 (+local-dev)",
        "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.9, text/html;q=0.8, */*;q=0.1",
    }
    req = Request(url, headers=headers, method="GET")
    ctx = ssl.create_default_context()
    with urlopen(req, timeout=timeout, context=ctx) as resp:
        final_url = getattr(resp, "geturl", lambda: url)()
        raw = resp.read()
    # Best-effort decode
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = raw.decode(errors="replace")
    return text, final_url


def _looks_like_xml(text: str) -> bool:
    if not text:
        return False
    t = text.lstrip().lower()
    if t.startswith("<?xml"):
        return True
    return ("<rss" in t) or ("<feed" in t) or ("<rdf:rdf" in t)


def _to_json_safe(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))


def _domain_from_url(url: str, fallback_name: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or (fallback_name.lower().replace(" ", "") + ".unknown")


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    v = value.strip()
    # Handle trailing Z
    if v.endswith("Z"):
        v = v[:-1]
    try:
        return datetime.fromisoformat(v)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# RSS ingest (when RSS works)
# ---------------------------------------------------------------------------

def ingest_rss_feed(
    db: Session,
    *,
    source_name: str,
    homepage_url: str,
    rss_url: str,
    max_items: int = 10,
) -> Dict[str, Any]:
    parsed = feedparser.parse(rss_url)

    if getattr(parsed, "bozo", 0):
        err = str(getattr(parsed, "bozo_exception", "Unknown RSS parse error"))
        return {
            "status": "error",
            "rss_url": rss_url,
            "used_rss_url": rss_url,
            "ingested": 0,
            "skipped_existing": 0,
            "max_items": max_items,
            "error": f"feedparser exception: {err}",
            "attempts": [],
            "errors": [],
        }

    entries = parsed.entries[:max_items]
    ingested = 0
    skipped_existing = 0
    errors: List[Dict[str, Any]] = []

    # Ensure Source exists
    domain = _domain_from_url(homepage_url, source_name)
    source = db.query(models.Source).filter(models.Source.domain == domain).one_or_none()
    if not source:
        source = models.Source(
            name=source_name,
            domain=domain,
            api_identifier=None,
        )
        db.add(source)
        db.commit()
        db.refresh(source)

    for entry in entries:
        try:
            link = (entry.get("link") or "").strip()
            title = (entry.get("title") or "").strip()
            description = (entry.get("summary") or entry.get("description") or "").strip() or None

            if not link or not title:
                continue

            exists = db.query(models.ArticleRaw).filter(models.ArticleRaw.source_url == link).first()
            if exists:
                skipped_existing += 1
                continue

            published_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
            if published_parsed:
                published_at = datetime.utcfromtimestamp(time.mktime(published_parsed))
            else:
                published_at = datetime.utcnow()

            raw_payload = {
                "source_name": source_name,
                "homepage_url": homepage_url,
                "rss_url": rss_url,
                "entry": _to_json_safe(dict(entry)),
            }

            run_neutral_pipeline(
                db,
                source_name=source_name,
                source_url=link,
                published_at=published_at,
                title=title,
                description=description,
                body=None,
                raw_payload=raw_payload,
            )

            ingested += 1
        except Exception as e:
            errors.append({"url": entry.get("link"), "error": str(e)})

    return {
        "status": "ok",
        "rss_url": rss_url,
        "used_rss_url": rss_url,
        "ingested": ingested,
        "skipped_existing": skipped_existing,
        "max_items": max_items,
        "error": None,
        "attempts": [],
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# HTML fallback: scrape AP tag page (works even when RSS is down)
# ---------------------------------------------------------------------------

_ARTICLE_HREF_RE = re.compile(r'href="(/article/[^"]+)"', re.IGNORECASE)
_OG_TITLE_RE = re.compile(r'property="og:title"\s+content="([^"]+)"', re.IGNORECASE)
_OG_DESC_RE = re.compile(r'(name="description"\s+content="([^"]+)")|(property="og:description"\s+content="([^"]+)")', re.IGNORECASE)
_PUBTIME_RE = re.compile(r'property="article:published_time"\s+content="([^"]+)"', re.IGNORECASE)
_TITLE_TAG_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _scrape_ap_tag_for_article_urls(tag_url: str, *, max_items: int) -> Tuple[List[str], Dict[str, Any]]:
    """
    Returns (article_urls, debug_info)
    """
    html_text, final_url = _http_get(tag_url, timeout=20)

    # Find /article/... links and turn them into absolute URLs
    rels = _ARTICLE_HREF_RE.findall(html_text)
    urls: List[str] = []
    seen = set()

    for rel in rels:
        abs_url = urljoin(final_url, rel)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        urls.append(abs_url)
        if len(urls) >= max_items:
            break

    debug = {
        "tag_url": tag_url,
        "final_url": final_url,
        "found_links": len(rels),
        "selected": len(urls),
    }
    return urls, debug


def _extract_article_fields(article_url: str) -> Dict[str, Any]:
    """
    Fetch article HTML and extract best-effort title/description/published_at.
    """
    html_text, final_url = _http_get(article_url, timeout=20)

    title = None
    m = _OG_TITLE_RE.search(html_text)
    if m:
        title = m.group(1).strip()

    if not title:
        mt = _TITLE_TAG_RE.search(html_text)
        if mt:
            title = re.sub(r"\s+", " ", mt.group(1)).strip()

    desc = None
    md = _OG_DESC_RE.search(html_text)
    if md:
        # md may match either pattern; pick the first non-empty captured value
        desc = next((g for g in md.groups() if g and 'content="' not in g), None)
        if desc:
            desc = desc.strip()

    pub = None
    mp = _PUBTIME_RE.search(html_text)
    if mp:
        pub = _parse_iso_datetime(mp.group(1))

    if not pub:
        pub = datetime.utcnow()

    return {
        "final_url": final_url,
        "title": title or "AP News",
        "description": desc,
        "published_at": pub,
        "html_sample": html_text[:800],
    }


def ingest_ap_topnews(db: Session, *, max_items: int = 10) -> Dict[str, Any]:
    """
    Try RSS candidates first; if they fail, scrape AP tag page and ingest article URLs.
    Always returns a dict that includes max_items (so your API response model won't crash).
    """
    source_name = AP_TOP_NEWS["source_name"]
    homepage_url = AP_TOP_NEWS["homepage_url"]
    attempts: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    # 1) Try RSS candidates (optional)
    for cand in AP_TOP_NEWS["rss_candidates"]:
        try:
            # Quick check: can we fetch something that looks like XML?
            text, final_url = _http_get(cand, timeout=15)
            ok = _looks_like_xml(text)
            attempts.append(
                {"url": cand, "final_url": final_url, "ok": ok, "error": None if ok else f"not XML (sample: {text[:120]!r})"}
            )
            if ok:
                return ingest_rss_feed(
                    db,
                    source_name=source_name,
                    homepage_url=homepage_url,
                    rss_url=final_url,
                    max_items=max_items,
                )
        except Exception as e:
            attempts.append({"url": cand, "final_url": None, "ok": False, "error": str(e)})

    # 2) Fallback: scrape tag page
    tag_url = AP_TOP_NEWS["tag_fallback_url"]
    used_url = None
    ingested = 0
    skipped_existing = 0

    try:
        article_urls, debug = _scrape_ap_tag_for_article_urls(tag_url, max_items=max_items)
        attempts.append({"url": tag_url, "final_url": debug.get("final_url"), "ok": len(article_urls) > 0, "error": None if article_urls else "no article links found"})

        used_url = debug.get("final_url") or tag_url

        # Ensure Source exists
        domain = _domain_from_url(homepage_url, source_name)
        source = db.query(models.Source).filter(models.Source.domain == domain).one_or_none()
        if not source:
            source = models.Source(
                name=source_name,
                domain=domain,
                api_identifier=None,
            )
            db.add(source)
            db.commit()
            db.refresh(source)

        for url in article_urls:
            try:
                exists = db.query(models.ArticleRaw).filter(models.ArticleRaw.source_url == url).first()
                if exists:
                    skipped_existing += 1
                    continue

                fields = _extract_article_fields(url)

                run_neutral_pipeline(
                    db,
                    source_name=source_name,
                    source_url=url,
                    published_at=fields["published_at"],
                    title=fields["title"],
                    description=fields["description"],
                    body=None,
                    raw_payload={
                        "source_name": source_name,
                        "homepage_url": homepage_url,
                        "tag_url": used_url,
                        "article_url": url,
                        "final_url": fields.get("final_url"),
                        "html_sample": fields.get("html_sample"),
                    },
                )
                ingested += 1
            except Exception as e:
                errors.append({"url": url, "error": str(e)})

        return {
            "status": "ok" if ingested > 0 else "error",
            "rss_url": tag_url,          # kept for backwards compatibility in your response
            "used_rss_url": used_url,    # actually used URL (tag page final URL)
            "ingested": ingested,
            "skipped_existing": skipped_existing,
            "max_items": max_items,
            "error": None if ingested > 0 else "Scrape fallback did not ingest any items.",
            "attempts": attempts,
            "errors": errors,
        }

    except Exception as e:
        return {
            "status": "error",
            "rss_url": tag_url,
            "used_rss_url": used_url,
            "ingested": 0,
            "skipped_existing": 0,
            "max_items": max_items,
            "error": str(e),
            "attempts": attempts,
            "errors": errors,
        }
