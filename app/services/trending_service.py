# app/services/trending_service.py
"""
Trending topics service.

Extracts trending topics from recent articles using TF-IDF-style keyword extraction.
"""

import logging
import re
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import models
from app.schemas.topics import TrendingTopic, TrendingTopicsResponse

logger = logging.getLogger(__name__)

# Common stopwords to filter out
STOPWORDS = {
    # Articles and determiners
    "a",
    "an",
    "the",
    "this",
    "that",
    "these",
    "those",
    # Pronouns
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "who",
    "what",
    "which",
    "his",
    "her",
    "its",
    "their",
    "our",
    "my",
    "your",
    # Prepositions and conjunctions
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "up",
    "about",
    "into",
    "over",
    "after",
    "and",
    "but",
    "or",
    "nor",
    "so",
    "yet",
    "as",
    # Verbs (common)
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "can",
    "must",
    "shall",
    "get",
    "gets",
    "got",
    "make",
    "makes",
    "made",
    "says",
    "said",
    "say",
    "set",
    "take",
    "takes",
    "took",
    # Adverbs and adjectives
    "more",
    "most",
    "very",
    "just",
    "also",
    "now",
    "even",
    "still",
    "well",
    "here",
    "there",
    "when",
    "where",
    "how",
    "why",
    "all",
    "some",
    "any",
    "each",
    "every",
    "both",
    "few",
    "many",
    "much",
    "other",
    "another",
    "such",
    "no",
    "not",
    "only",
    "own",
    "same",
    "than",
    "too",
    "out",
    # Common news words (not topical)
    "new",
    "news",
    "report",
    "reports",
    "according",
    "officials",
    "official",
    "year",
    "years",
    "day",
    "days",
    "week",
    "weeks",
    "month",
    "months",
    "time",
    "times",
    "first",
    "last",
    "people",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "million",
    "billion",
    "percent",
    "part",
    "way",
    "world",
    "country",
    "state",
    "government",
    "public",
    "case",
    "cases",
    "group",
    "company",
}

# Minimum word length to consider
MIN_WORD_LENGTH = 3

# Minimum article count to be considered trending
MIN_ARTICLE_COUNT = 3


def extract_keywords(text: str) -> list[str]:
    """
    Extract meaningful keywords from text.

    Returns a list of lowercase words/phrases that could be topics.
    """
    if not text:
        return []

    # Normalize text
    text = text.lower()

    # Extract words (alphanumeric + hyphens)
    words = re.findall(r"\b[a-z][a-z\-]*[a-z]\b|\b[a-z]{2,}\b", text)

    # Filter out stopwords and short words
    keywords = [w for w in words if w not in STOPWORDS and len(w) >= MIN_WORD_LENGTH]

    return keywords


def extract_bigrams(text: str) -> list[str]:
    """
    Extract meaningful bigrams (two-word phrases) from text.

    Returns phrases like "supreme court", "climate change", etc.
    """
    if not text:
        return []

    # Normalize text
    text = text.lower()

    # Extract words
    words = re.findall(r"\b[a-z][a-z\-]*[a-z]\b|\b[a-z]{2,}\b", text)

    # Generate bigrams, filtering stopwords
    bigrams = []
    for i in range(len(words) - 1):
        w1, w2 = words[i], words[i + 1]
        # Both words must be meaningful
        if w1 not in STOPWORDS and w2 not in STOPWORDS and len(w1) >= MIN_WORD_LENGTH and len(w2) >= MIN_WORD_LENGTH:
            bigrams.append(f"{w1} {w2}")

    return bigrams


class TrendingService:
    """Service for extracting trending topics from recent articles."""

    def __init__(self, db: Session):
        self.db = db

    def get_trending_topics(
        self,
        window_hours: int = 24,
        max_topics: int = 12,
        min_count: int = MIN_ARTICLE_COUNT,
    ) -> TrendingTopicsResponse:
        """
        Get trending topics from articles in the specified time window.

        Args:
            window_hours: Look back this many hours for articles
            max_topics: Maximum number of topics to return
            min_count: Minimum article count to be considered trending

        Returns:
            TrendingTopicsResponse with sorted topics
        """
        cutoff = datetime.utcnow() - timedelta(hours=window_hours)

        # Fetch recent article titles
        articles = (
            self.db.query(
                models.StoryNeutralized.feed_title,
                models.StoryNeutralized.feed_summary,
            )
            .join(models.StoryRaw, models.StoryNeutralized.story_raw_id == models.StoryRaw.id)
            .filter(
                models.StoryNeutralized.is_current == True,
                models.StoryNeutralized.neutralization_status == "success",
                models.StoryRaw.is_duplicate == False,
                models.StoryRaw.published_at >= cutoff,
            )
            .all()
        )

        if not articles:
            return TrendingTopicsResponse(
                topics=[],
                generated_at=datetime.utcnow(),
                window_hours=window_hours,
            )

        # Count keyword and bigram occurrences across articles
        # Using document frequency (count each term once per article)
        term_doc_count: Counter = Counter()
        term_sample_headline: dict = {}

        for title, summary in articles:
            # Extract from title (higher weight - title terms are more significant)
            title_keywords = set(extract_keywords(title))
            title_bigrams = set(extract_bigrams(title))

            # Extract from summary
            summary_keywords = set(extract_keywords(summary or ""))
            summary_bigrams = set(extract_bigrams(summary or ""))

            # Combine terms for this article (deduplicated)
            # Prefer bigrams over their constituent words
            all_bigrams = title_bigrams | summary_bigrams
            all_keywords = title_keywords | summary_keywords

            # Remove single words that are part of a bigram in this article
            for bigram in all_bigrams:
                parts = bigram.split()
                all_keywords -= set(parts)

            # Count each term once per article
            for term in all_bigrams:
                term_doc_count[term] += 1
                if term not in term_sample_headline:
                    term_sample_headline[term] = title

            for term in all_keywords:
                term_doc_count[term] += 1
                if term not in term_sample_headline:
                    term_sample_headline[term] = title

        # Filter by minimum count and get top topics
        trending = [(term, count) for term, count in term_doc_count.most_common(max_topics * 2) if count >= min_count][
            :max_topics
        ]

        # Build response
        topics = [
            TrendingTopic(
                term=term,
                label=term.title(),
                count=count,
                sample_headline=term_sample_headline.get(term),
            )
            for term, count in trending
        ]

        return TrendingTopicsResponse(
            topics=topics,
            generated_at=datetime.utcnow(),
            window_hours=window_hours,
        )
