"""Backfill per-publisher Source records for API-ingested articles.

Previously, all Perigon articles shared one Source named "Perigon News API"
and all NewsData articles shared one Source named "NewsData.io". This migration
creates per-publisher Source records by extracting the domain from original_url
and maps them to proper publisher names.

Revision ID: 016_backfill_publisher_sources
Revises: 015_add_api_source_fields
Create Date: 2026-02-04
"""
from typing import Sequence, Union
from urllib.parse import urlparse
import re
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = '016_backfill_publisher_sources'
down_revision: Union[str, Sequence[str], None] = '015_add_api_source_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Known domain-to-publisher mappings
DOMAIN_TO_PUBLISHER = {
    'bbc.com': 'BBC News',
    'bbc.co.uk': 'BBC News',
    'reuters.com': 'Reuters',
    'apnews.com': 'AP News',
    'cnn.com': 'CNN',
    'nytimes.com': 'The New York Times',
    'washingtonpost.com': 'The Washington Post',
    'theguardian.com': 'The Guardian',
    'dailymail.co.uk': 'Daily Mail',
    'foxnews.com': 'Fox News',
    'nbcnews.com': 'NBC News',
    'abcnews.go.com': 'ABC News',
    'cbsnews.com': 'CBS News',
    'politico.com': 'Politico',
    'thehill.com': 'The Hill',
    'aljazeera.com': 'Al Jazeera',
    'france24.com': 'France 24',
    'dw.com': 'DW News',
    'bloomberg.com': 'Bloomberg',
    'cnbc.com': 'CNBC',
    'npr.org': 'NPR',
    'pbs.org': 'PBS',
    'usatoday.com': 'USA Today',
    'wsj.com': 'The Wall Street Journal',
    'ft.com': 'Financial Times',
    'economist.com': 'The Economist',
    'independent.co.uk': 'The Independent',
    'telegraph.co.uk': 'The Telegraph',
    'sky.com': 'Sky News',
    'news.sky.com': 'Sky News',
    'skynews.com.au': 'Sky News Australia',
    'abc.net.au': 'ABC Australia',
    'smh.com.au': 'Sydney Morning Herald',
    'globalnews.ca': 'Global News',
    'cbc.ca': 'CBC News',
    'timesofindia.indiatimes.com': 'Times of India',
    'ndtv.com': 'NDTV',
    'hindustantimes.com': 'Hindustan Times',
    'scmp.com': 'South China Morning Post',
    'japantimes.co.jp': 'Japan Times',
    'straitstimes.com': 'The Straits Times',
    'channelnewsasia.com': 'CNA',
    'axios.com': 'Axios',
    'theatlantic.com': 'The Atlantic',
    'vox.com': 'Vox',
    'slate.com': 'Slate',
    'salon.com': 'Salon',
    'buzzfeednews.com': 'BuzzFeed News',
    'vice.com': 'Vice',
    'wired.com': 'Wired',
    'arstechnica.com': 'Ars Technica',
    'theverge.com': 'The Verge',
    'techcrunch.com': 'TechCrunch',
    'engadget.com': 'Engadget',
    'nypost.com': 'New York Post',
    'latimes.com': 'Los Angeles Times',
    'chicagotribune.com': 'Chicago Tribune',
    'miamiherald.com': 'Miami Herald',
    'mercurynews.com': 'Mercury News',
    'seattletimes.com': 'Seattle Times',
    'denverpost.com': 'Denver Post',
    'sfchronicle.com': 'San Francisco Chronicle',
    'newsweek.com': 'Newsweek',
    'time.com': 'Time',
    'forbes.com': 'Forbes',
    'businessinsider.com': 'Business Insider',
    'insider.com': 'Business Insider',
    'yahoo.com': 'Yahoo News',
    'news.yahoo.com': 'Yahoo News',
    'msn.com': 'MSN',
}


def _extract_domain(url: str) -> str:
    """Extract the registrable domain from a URL."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ''
        # Strip www. prefix
        if hostname.startswith('www.'):
            hostname = hostname[4:]
        return hostname.lower()
    except Exception:
        return ''


def _domain_to_publisher_name(domain: str) -> str:
    """Convert a domain to a human-readable publisher name."""
    if domain in DOMAIN_TO_PUBLISHER:
        return DOMAIN_TO_PUBLISHER[domain]

    # Try without subdomain (e.g., news.bbc.co.uk -> bbc.co.uk)
    parts = domain.split('.')
    if len(parts) > 2:
        # Try last two parts (e.g., bbc.com)
        parent = '.'.join(parts[-2:])
        if parent in DOMAIN_TO_PUBLISHER:
            return DOMAIN_TO_PUBLISHER[parent]
        # Try last three parts for .co.uk style (e.g., bbc.co.uk)
        if len(parts) > 3:
            parent3 = '.'.join(parts[-3:])
            if parent3 in DOMAIN_TO_PUBLISHER:
                return DOMAIN_TO_PUBLISHER[parent3]

    # Fallback: title-case the main domain part
    # e.g., "breitbart.com" -> "Breitbart"
    if parts:
        name = parts[0] if len(parts) <= 2 else parts[-2]
        return name.capitalize()

    return domain


def _slugify(name: str, source_type: str) -> str:
    """Create a URL-safe slug for a publisher name."""
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return f"{source_type}-{slug}"


def upgrade() -> None:
    """Create per-publisher Source records and update stories_raw.source_id."""
    conn = op.get_bind()

    # Find all API-sourced stories grouped by domain
    rows = conn.execute(
        sa.text("""
            SELECT id, original_url, source_type, source_id
            FROM stories_raw
            WHERE source_type IN ('perigon', 'newsdata')
              AND original_url IS NOT NULL
              AND original_url != ''
        """)
    ).fetchall()

    if not rows:
        print("  No API-sourced articles to backfill.")
        return

    print(f"  Found {len(rows)} API-sourced articles to backfill.")

    # Group by domain
    domain_stories = {}  # domain -> [(story_id, source_type)]
    for row in rows:
        domain = _extract_domain(row.original_url)
        if not domain:
            continue
        if domain not in domain_stories:
            domain_stories[domain] = []
        domain_stories[domain].append((row.id, row.source_type))

    print(f"  Found {len(domain_stories)} unique publisher domains.")

    # Create Source records and update stories
    created = 0
    updated = 0
    for domain, stories in domain_stories.items():
        publisher_name = _domain_to_publisher_name(domain)
        source_type = stories[0][1]  # All stories for same domain have same type
        slug = _slugify(publisher_name, source_type)

        # Check if Source already exists
        existing = conn.execute(
            sa.text("SELECT id FROM sources WHERE slug = :slug"),
            {"slug": slug}
        ).fetchone()

        if existing:
            source_id = existing.id
        else:
            source_id = uuid.uuid4()
            conn.execute(
                sa.text("""
                    INSERT INTO sources (id, name, slug, rss_url, is_active, created_at, updated_at)
                    VALUES (:id, :name, :slug, :rss_url, false, NOW(), NOW())
                """),
                {
                    "id": source_id,
                    "name": publisher_name,
                    "slug": slug,
                    "rss_url": f"https://{source_type}-api.internal/{slug}",
                }
            )
            created += 1

        # Update all stories for this domain
        story_ids = [s[0] for s in stories]
        conn.execute(
            sa.text("""
                UPDATE stories_raw
                SET source_id = :source_id
                WHERE id = ANY(:story_ids)
            """),
            {"source_id": source_id, "story_ids": story_ids}
        )
        updated += len(story_ids)

    print(f"  Created {created} publisher Source records.")
    print(f"  Updated {updated} stories with correct publisher source.")


def downgrade() -> None:
    """Revert stories back to shared API source records.

    Note: This is a best-effort downgrade. It reassigns all API-sourced stories
    back to the shared 'api-perigon' or 'api-newsdata' Source records.
    Publisher Source records are NOT deleted (they may be referenced elsewhere).
    """
    conn = op.get_bind()

    for source_type, api_name in [('perigon', 'Perigon News API'), ('newsdata', 'NewsData.io')]:
        slug = f"api-{source_type}"
        api_source = conn.execute(
            sa.text("SELECT id FROM sources WHERE slug = :slug"),
            {"slug": slug}
        ).fetchone()

        if api_source:
            conn.execute(
                sa.text("""
                    UPDATE stories_raw
                    SET source_id = :api_source_id
                    WHERE source_type = :source_type
                """),
                {"api_source_id": api_source.id, "source_type": source_type}
            )
            print(f"  Reverted {source_type} stories to shared source '{api_name}'.")
        else:
            print(f"  Warning: shared source '{slug}' not found, skipping {source_type} revert.")
