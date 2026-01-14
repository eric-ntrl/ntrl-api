# app/services/classifier.py
"""
Section classification using simple keyword heuristics.

Sections (in order):
1. World
2. U.S.
3. Local
4. Business & Markets
5. Technology

For POC, uses keyword matching. Can be enhanced with ML later.
"""

import re
from typing import Optional

from app.models import Section


# Keyword sets for each section (lowercase)
SECTION_KEYWORDS = {
    Section.WORLD: {
        # Countries/regions
        'china', 'russia', 'ukraine', 'europe', 'asia', 'africa', 'middle east',
        'israel', 'gaza', 'palestine', 'iran', 'north korea', 'india', 'japan',
        'uk', 'britain', 'france', 'germany', 'nato', 'united nations', 'un',
        'european union', 'eu', 'mexico', 'canada', 'brazil', 'australia',
        # World topics
        'international', 'foreign', 'global', 'diplomatic', 'embassy',
        'refugee', 'humanitarian', 'war', 'conflict', 'treaty', 'summit',
    },
    Section.US: {
        # Government
        'congress', 'senate', 'house of representatives', 'white house',
        'president', 'biden', 'trump', 'supreme court', 'federal',
        'democrat', 'republican', 'gop', 'election', 'vote', 'poll',
        # US places
        'washington', 'new york', 'california', 'texas', 'florida',
        # US topics
        'american', 'u.s.', 'us ', 'usa', 'united states', 'national',
        'immigration', 'border', 'fbi', 'cia', 'pentagon', 'military',
    },
    Section.LOCAL: {
        # Local governance
        'mayor', 'city council', 'county', 'municipal', 'local',
        'neighborhood', 'community', 'residents', 'hometown',
        # Local topics
        'school board', 'zoning', 'traffic', 'public transit',
        'local business', 'town', 'village', 'district',
    },
    Section.BUSINESS: {
        # Markets
        'stock', 'market', 'dow', 'nasdaq', 's&p', 'wall street',
        'investor', 'trading', 'shares', 'ipo', 'earnings',
        # Business
        'company', 'corporate', 'ceo', 'merger', 'acquisition',
        'revenue', 'profit', 'startup', 'venture', 'economy',
        'inflation', 'fed', 'federal reserve', 'interest rate', 'interest rates', 'rates',
        'gdp', 'unemployment', 'jobs report', 'retail', 'consumer',
        # Finance
        'bank', 'banking', 'finance', 'investment', 'hedge fund',
        'cryptocurrency', 'bitcoin', 'crypto',
    },
    Section.TECHNOLOGY: {
        # Companies
        'apple', 'google', 'microsoft', 'amazon', 'meta', 'facebook',
        'twitter', 'tesla', 'nvidia', 'openai', 'anthropic',
        # Tech topics
        'ai', 'artificial intelligence', 'machine learning', 'algorithm',
        'software', 'hardware', 'app', 'smartphone', 'iphone', 'android',
        'internet', 'cyber', 'hacker', 'data breach', 'privacy',
        'tech', 'technology', 'silicon valley', 'startup',
        'cloud', 'computing', 'chip', 'semiconductor',
        # Social media
        'social media', 'viral', 'platform', 'content moderation',
    },
}

# Source default sections (hint from source)
SOURCE_DEFAULT_SECTIONS = {
    'ap-world': Section.WORLD,
    'ap-us': Section.US,
    'ap-business': Section.BUSINESS,
    'ap-technology': Section.TECHNOLOGY,
    'reuters-world': Section.WORLD,
    'reuters-business': Section.BUSINESS,
    'reuters-technology': Section.TECHNOLOGY,
}


class SectionClassifier:
    """Classify stories into sections using keyword heuristics."""

    def classify(
        self,
        title: str,
        description: Optional[str] = None,
        body: Optional[str] = None,
        source_slug: Optional[str] = None,
    ) -> Section:
        """
        Classify a story into a section.

        Priority:
        1. Source hint (if specific section source)
        2. Keyword matching in title (weighted higher)
        3. Keyword matching in description/body
        4. Default to WORLD if no match
        """
        # Check source hint first
        if source_slug and source_slug in SOURCE_DEFAULT_SECTIONS:
            return SOURCE_DEFAULT_SECTIONS[source_slug]

        # Combine text for analysis
        text_parts = [title or '']
        if description:
            text_parts.append(description)
        if body:
            text_parts.append(body[:1000])  # Limit body for performance

        combined_text = ' '.join(text_parts).lower()

        # Score each section
        scores = {}
        for section, keywords in SECTION_KEYWORDS.items():
            score = 0
            for keyword in keywords:
                # Use word boundary matching to avoid partial matches (e.g., "un" in "announces")
                pattern = r'\b' + re.escape(keyword) + r'\b'
                # Title matches worth more
                if re.search(pattern, (title or '').lower()):
                    score += 3
                elif re.search(pattern, combined_text):
                    score += 1
            scores[section] = score

        # Find best match
        best_section = max(scores, key=scores.get)
        if scores[best_section] > 0:
            return best_section

        # Default to WORLD if no keywords match
        return Section.WORLD

    def classify_batch(
        self,
        stories: list,
    ) -> dict:
        """
        Classify a batch of stories.

        Args:
            stories: List of dicts with 'title', 'description', 'body', 'source_slug'

        Returns:
            Dict mapping story index to Section
        """
        results = {}
        for idx, story in enumerate(stories):
            section = self.classify(
                title=story.get('title', ''),
                description=story.get('description'),
                body=story.get('body'),
                source_slug=story.get('source_slug'),
            )
            results[idx] = section
        return results
