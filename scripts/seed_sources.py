#!/usr/bin/env python3
"""
Seed script to initialize RSS sources for NTRL POC.

Usage:
    pipenv run python scripts/seed_sources.py
"""

import os
import sys
import uuid
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.orm import Session

from app import models
from app.database import SessionLocal

# Fixed set of sources for POC
SOURCES = [
    {
        "name": "Associated Press",
        "slug": "ap",
        "rss_url": "https://rsshub.app/apnews/topics/apf-topnews",
        "default_section": "world",
    },
    {
        "name": "AP - U.S. News",
        "slug": "ap-us",
        "rss_url": "https://rsshub.app/apnews/topics/apf-usnews",
        "default_section": "us",
    },
    {
        "name": "AP - World News",
        "slug": "ap-world",
        "rss_url": "https://rsshub.app/apnews/topics/apf-WorldNews",
        "default_section": "world",
    },
    {
        "name": "AP - Business",
        "slug": "ap-business",
        "rss_url": "https://rsshub.app/apnews/topics/apf-business",
        "default_section": "business",
    },
    {
        "name": "AP - Technology",
        "slug": "ap-technology",
        "rss_url": "https://rsshub.app/apnews/topics/apf-technology",
        "default_section": "technology",
    },
    {
        "name": "Reuters - World",
        "slug": "reuters-world",
        "rss_url": "https://www.reutersagency.com/feed/?best-topics=world&post_type=best",
        "default_section": "world",
    },
    {
        "name": "Reuters - Business",
        "slug": "reuters-business",
        "rss_url": "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
        "default_section": "business",
    },
    {
        "name": "NPR News",
        "slug": "npr",
        "rss_url": "https://feeds.npr.org/1001/rss.xml",
        "default_section": "us",
    },
    {
        "name": "BBC World",
        "slug": "bbc-world",
        "rss_url": "http://feeds.bbci.co.uk/news/world/rss.xml",
        "default_section": "world",
    },
    {
        "name": "BBC Technology",
        "slug": "bbc-technology",
        "rss_url": "http://feeds.bbci.co.uk/news/technology/rss.xml",
        "default_section": "technology",
    },
    {
        "name": "PBS NewsHour",
        "slug": "pbs",
        "rss_url": "https://www.pbs.org/newshour/feeds/rss/headlines",
        "default_section": "us",
    },
    {
        "name": "Al Jazeera English",
        "slug": "aljazeera",
        "rss_url": "https://www.aljazeera.com/xml/rss/all.xml",
        "default_section": "world",
    },
    {
        "name": "The Guardian - World",
        "slug": "guardian-world",
        "rss_url": "https://www.theguardian.com/world/rss",
        "default_section": "world",
    },
    {
        "name": "The Guardian - US",
        "slug": "guardian-us",
        "rss_url": "https://www.theguardian.com/us-news/rss",
        "default_section": "us",
    },
]


def seed_sources(db: Session) -> None:
    """Seed the sources table."""
    print("Seeding sources...")

    for source_data in SOURCES:
        # Check if exists
        existing = db.query(models.Source).filter(models.Source.slug == source_data["slug"]).first()

        if existing:
            print(f"  Source '{source_data['slug']}' already exists, skipping.")
            continue

        source = models.Source(
            id=uuid.uuid4(),
            name=source_data["name"],
            slug=source_data["slug"],
            rss_url=source_data["rss_url"],
            is_active=True,
            default_section=source_data.get("default_section"),
            created_at=datetime.utcnow(),
        )
        db.add(source)
        print(f"  Added source: {source_data['name']} ({source_data['slug']})")

    db.commit()
    print(f"Done! {len(SOURCES)} sources configured.")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        seed_sources(db)
    finally:
        db.close()
