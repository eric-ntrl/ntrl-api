# app/services/llm_classifier.py
"""
LLM-based article classifier with multi-model retry and robust fallback.

Reliability chain:
1. gpt-4o-mini with structured JSON output
2. Retry gpt-4o-mini with simplified prompt (on validation failure)
3. gemini-2.0-flash as alternate model
4. Enhanced keyword classifier (last resort, explicitly flagged)

Classification is independent of neutralization — articles are classified
even if neutralization fails. The CLASSIFY stage runs after ingestion
and before neutralization in the pipeline.

Prompts are stored in the database for hot-reload without redeploy.
Fallback to hardcoded prompts if DB lookup fails.
"""

import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import Domain, FeedCategory, PipelineStage, PipelineStatus
from app.services.domain_mapper import map_domain_to_feed_category
from app.services.enhanced_keyword_classifier import classify_by_keywords

logger = logging.getLogger(__name__)

# Prompt cache for hot-reload
_classification_prompt_cache: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ClassificationResult:
    """Result of classifying a single article."""
    domain: str               # e.g. "governance_politics"
    feed_category: str        # e.g. "us" (from domain mapper)
    confidence: float         # 0.0-1.0 (LLM self-reported, 0.0 for keyword)
    tags: dict                # {geography, geography_detail, actors, action_type, topic_keywords}
    model: str                # "gpt-4o-mini", "gemini-2.0-flash", or "keyword"
    method: str               # "llm" or "keyword_fallback"


@dataclass
class ClassifyRunResult:
    """Result of a classification batch run."""
    total: int = 0
    success: int = 0
    llm: int = 0
    keyword_fallback: int = 0
    failed: int = 0
    errors: list = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


# ---------------------------------------------------------------------------
# LLM Prompt
# ---------------------------------------------------------------------------

CLASSIFICATION_SYSTEM_PROMPT = """You are a news article classifier. Classify articles into exactly one domain and detect geographic scope.

DOMAINS (pick exactly one):
- global_affairs: International relations, diplomacy, foreign policy, UN/NATO, treaties, summits
- governance_politics: Government, legislation, elections, political parties, policy, regulation
- law_justice: Courts, legal rulings, lawsuits, constitutional issues, civil rights law
- security_defense: Military, defense, intelligence, national security, cybersecurity threats
- crime_public_safety: Crime, policing, public safety, arrests, investigations, violence
- economy_macroeconomics: GDP, inflation, interest rates, monetary/fiscal policy, economic indicators
- finance_markets: Stock markets, trading, banking, investments, cryptocurrency, IPOs
- business_industry: Companies, corporate news, mergers, startups, revenue, products
- labor_demographics: Workers, unions, wages, employment, immigration, population trends
- infrastructure_systems: Transportation, roads, bridges, utilities, broadband, housing
- energy: Oil, gas, renewable energy, power grid, electric vehicles, energy policy
- environment_climate: Climate change, pollution, conservation, wildlife, sustainability
- science_research: Scientific discoveries, space, physics, biology, research studies
- health_medicine: Medical, diseases, treatments, public health, mental health, pharmaceuticals
- technology: AI, software, hardware, internet, tech companies, innovation
- media_information: Journalism, social media, misinformation, content moderation, press
- sports_competition: Professional/amateur sports, competitions, athletes, leagues
- society_culture: Social issues, education, arts, religion, cultural movements
- lifestyle_personal: Celebrity, entertainment, food, travel, fashion, personal finance
- incidents_disasters: Natural disasters, accidents, emergencies, mass incidents, weather events

GEOGRAPHY (pick exactly one):
- international: Non-US or multi-country focus
- us: US national scope
- local: City/county/neighborhood scope within US
- mixed: Both US and international elements

Respond with valid JSON only. No markdown, no explanation.

Output schema:
{
  "domain": "<one of the domain values above>",
  "confidence": <0.0-1.0>,
  "tags": {
    "geography": "<international|us|local|mixed>",
    "geography_detail": "<brief geographic note>",
    "actors": ["<key actors mentioned>"],
    "action_type": "<legislation|ruling|announcement|report|incident|other>",
    "topic_keywords": ["<2-5 key topic words>"]
  }
}"""

CLASSIFICATION_SIMPLIFIED_PROMPT = """Classify this news article. Pick one domain and one geography.

DOMAINS: global_affairs, governance_politics, law_justice, security_defense, crime_public_safety, economy_macroeconomics, finance_markets, business_industry, labor_demographics, infrastructure_systems, energy, environment_climate, science_research, health_medicine, technology, media_information, sports_competition, society_culture, lifestyle_personal, incidents_disasters

GEOGRAPHY: international, us, local, mixed

Respond with JSON only:
{"domain": "...", "confidence": 0.9, "tags": {"geography": "...", "geography_detail": "", "actors": [], "action_type": "", "topic_keywords": []}}"""

# Valid domain values for validation
VALID_DOMAINS = {d.value for d in Domain}


# ---------------------------------------------------------------------------
# Prompt loading from database
# ---------------------------------------------------------------------------

def get_classification_prompt(prompt_name: str = "classification_system_prompt") -> str:
    """
    Get classification prompt from database, with hardcoded fallback.

    Prompts are cached for performance. Use clear_classification_prompt_cache()
    to reload after changes.
    """
    if prompt_name in _classification_prompt_cache:
        return _classification_prompt_cache[prompt_name]

    # Try to fetch from database
    try:
        from app.database import SessionLocal
        from app import models

        db = SessionLocal()
        try:
            prompt = db.query(models.Prompt).filter(
                models.Prompt.name == prompt_name,
                models.Prompt.is_active == True,
            ).first()

            if prompt and prompt.content:
                _classification_prompt_cache[prompt_name] = prompt.content
                logger.info(f"[CLASSIFY] Loaded prompt '{prompt_name}' from DB (v{prompt.version})")
                return prompt.content
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"[CLASSIFY] Failed to load prompt '{prompt_name}' from DB: {e}")

    # Fallback to hardcoded prompts
    fallback = {
        "classification_system_prompt": CLASSIFICATION_SYSTEM_PROMPT,
        "classification_simplified_prompt": CLASSIFICATION_SIMPLIFIED_PROMPT,
    }

    if prompt_name in fallback:
        _classification_prompt_cache[prompt_name] = fallback[prompt_name]
        logger.info(f"[CLASSIFY] Using hardcoded fallback for '{prompt_name}'")
        return fallback[prompt_name]

    # If not a known prompt, return the system prompt as default
    logger.warning(f"[CLASSIFY] Unknown prompt '{prompt_name}', using system prompt")
    return CLASSIFICATION_SYSTEM_PROMPT


def clear_classification_prompt_cache() -> None:
    """Clear the prompt cache to force reload from DB."""
    _classification_prompt_cache.clear()
    logger.info("[CLASSIFY] Prompt cache cleared")


def _build_user_prompt(title: str, description: str, body_excerpt: str, source_slug: str) -> str:
    """Build the user prompt for classification."""
    parts = [f"TITLE: {title}"]
    if description:
        parts.append(f"DESCRIPTION: {description}")
    if source_slug:
        parts.append(f"SOURCE: {source_slug}")
    if body_excerpt:
        parts.append(f"EXCERPT: {body_excerpt[:2000]}")
    return "\n".join(parts)


def _parse_llm_response(content: str) -> Optional[dict]:
    """Parse and validate LLM JSON response."""
    try:
        # Strip markdown code blocks if present
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            json_lines = [line for line in lines if not line.startswith("```")]
            text = "\n".join(json_lines).strip()

        data = json.loads(text)

        # Validate domain
        domain = data.get("domain", "").lower().strip()
        if domain not in VALID_DOMAINS:
            logger.warning(f"[CLASSIFY] Invalid domain from LLM: {domain}")
            return None

        # Validate confidence
        confidence = data.get("confidence", 0.5)
        if not isinstance(confidence, (int, float)):
            confidence = 0.5
        confidence = max(0.0, min(1.0, float(confidence)))

        # Validate tags
        tags = data.get("tags", {})
        if not isinstance(tags, dict):
            tags = {}
        geography = tags.get("geography", "us")
        if geography not in ("international", "us", "local", "mixed"):
            geography = "us"
        tags["geography"] = geography

        return {
            "domain": domain,
            "confidence": confidence,
            "tags": tags,
        }
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"[CLASSIFY] Failed to parse LLM response: {e}")
        return None


# ---------------------------------------------------------------------------
# LLM call implementations
# ---------------------------------------------------------------------------

def _classify_openai(
    title: str,
    description: str,
    body_excerpt: str,
    source_slug: str,
    system_prompt: str,
    model: str = "gpt-4o-mini",
) -> Optional[dict]:
    """Classify using OpenAI API with JSON mode."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, timeout=10.0)
        user_prompt = _build_user_prompt(title, description, body_excerpt, source_slug)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content.strip()
        return _parse_llm_response(content)

    except Exception as e:
        logger.warning(f"[CLASSIFY] OpenAI {model} failed: {e}")
        return None


def _classify_gemini(
    title: str,
    description: str,
    body_excerpt: str,
    source_slug: str,
    system_prompt: str,
    model: str = "gemini-2.0-flash",
) -> Optional[dict]:
    """Classify using Gemini API with JSON mode."""
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        user_prompt = _build_user_prompt(title, description, body_excerpt, source_slug)

        # Map model names
        model_map = {
            "gemini-2.0-flash": "gemini-2.0-flash-exp",
            "gemini-1.5-flash": "gemini-1.5-flash",
        }
        resolved_model = model_map.get(model, model)

        gemini_model = genai.GenerativeModel(
            model_name=resolved_model,
            system_instruction=system_prompt,
            generation_config={
                "temperature": 0.2,
                "response_mime_type": "application/json",
            },
        )

        response = gemini_model.generate_content(user_prompt)
        content = response.text.strip()
        return _parse_llm_response(content)

    except Exception as e:
        logger.warning(f"[CLASSIFY] Gemini {model} failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------

class LLMClassifier:
    """LLM-based article classifier with multi-model retry and robust fallback."""

    def classify(
        self,
        title: str,
        description: Optional[str] = None,
        body_excerpt: Optional[str] = None,
        source_slug: Optional[str] = None,
    ) -> ClassificationResult:
        """
        Classify a single article through the reliability chain.

        1. gpt-4o-mini with full prompt (from DB or fallback)
        2. gpt-4o-mini with simplified prompt (from DB or fallback)
        3. gemini-2.0-flash with full prompt
        4. Enhanced keyword classifier (last resort)
        """
        desc = description or ""
        excerpt = body_excerpt or ""
        slug = source_slug or ""

        # Load prompts from DB (with fallback to hardcoded)
        system_prompt = get_classification_prompt("classification_system_prompt")
        simplified_prompt = get_classification_prompt("classification_simplified_prompt")

        # Attempt 1: gpt-4o-mini, full prompt
        result = _classify_openai(title, desc, excerpt, slug, system_prompt)
        if result:
            logger.info(f"[CLASSIFY] Success: OpenAI attempt 1, domain={result['domain']}")
            return self._make_result(result, model="gpt-4o-mini", method="llm")

        # Attempt 2: gpt-4o-mini, simplified prompt
        result = _classify_openai(title, desc, excerpt, slug, simplified_prompt)
        if result:
            logger.info(f"[CLASSIFY] Success: OpenAI attempt 2 (simplified), domain={result['domain']}")
            return self._make_result(result, model="gpt-4o-mini", method="llm")

        # Attempt 3: gemini-2.0-flash, full prompt
        result = _classify_gemini(title, desc, excerpt, slug, system_prompt)
        if result:
            logger.info(f"[CLASSIFY] Success: Gemini attempt 3, domain={result['domain']}")
            return self._make_result(result, model="gemini-2.0-flash", method="llm")

        # Attempt 4: Enhanced keyword classifier (last resort)
        logger.warning(f"[CLASSIFY] All LLM attempts failed, falling back to keyword classifier")
        kw_result = classify_by_keywords(title, desc, excerpt, slug)
        domain = kw_result["domain"]
        geography = kw_result["geography"]
        feed_category = map_domain_to_feed_category(domain, geography)

        return ClassificationResult(
            domain=domain,
            feed_category=feed_category,
            confidence=0.0,
            tags=kw_result["tags"],
            model="keyword",
            method="keyword_fallback",
        )

    def _make_result(self, parsed: dict, model: str, method: str) -> ClassificationResult:
        """Build ClassificationResult from parsed LLM response."""
        domain = parsed["domain"]
        geography = parsed.get("tags", {}).get("geography", "us")
        feed_category = map_domain_to_feed_category(domain, geography)

        return ClassificationResult(
            domain=domain,
            feed_category=feed_category,
            confidence=parsed.get("confidence", 0.5),
            tags=parsed.get("tags", {}),
            model=model,
            method=method,
        )

    def _prefetch_bodies(self, stories: List, storage) -> Dict[str, str]:
        """Pre-fetch article bodies from S3 in parallel using a thread pool.

        Returns a dict mapping story ID (str) to body excerpt (first 2000 chars).
        Stories without content URIs or failed downloads map to empty string.
        """
        body_map: Dict[str, str] = {}
        fetchable = [
            s for s in stories
            if s.raw_content_uri and s.raw_content_available
        ]

        if not fetchable:
            return body_map

        def _fetch_one(story_id: str, uri: str) -> tuple:
            try:
                body_bytes = storage.get(uri)
                if body_bytes:
                    return (story_id, body_bytes.decode("utf-8", errors="replace")[:2000])
            except Exception as e:
                logger.warning(f"[CLASSIFY] Failed to fetch body for {story_id}: {e}")
            return (story_id, "")

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(_fetch_one, str(s.id), s.raw_content_uri): s
                for s in fetchable
            }
            for future in as_completed(futures):
                story_id, excerpt = future.result()
                body_map[story_id] = excerpt

        logger.info(f"[CLASSIFY] Pre-fetched {len(body_map)} bodies from storage")
        return body_map

    def classify_pending(self, db: Session, limit: int = 25) -> ClassifyRunResult:
        """
        Classify stories where classified_at IS NULL.

        Pre-fetches article bodies from S3 in parallel, then runs
        the classification reliability chain serially.
        """
        from app import models
        from app.storage.factory import get_storage_provider

        run_result = ClassifyRunResult()

        # Find unclassified stories
        stories = (
            db.query(models.StoryRaw)
            .join(models.Source, models.StoryRaw.source_id == models.Source.id)
            .filter(models.StoryRaw.classified_at.is_(None))
            .filter(models.StoryRaw.is_duplicate == False)
            .order_by(models.StoryRaw.ingested_at.desc())
            .limit(limit)
            .all()
        )

        if not stories:
            logger.info("[CLASSIFY] No pending stories to classify")
            return run_result

        # Get storage provider for fetching body excerpts
        storage = None
        try:
            storage = get_storage_provider()
        except Exception as e:
            logger.warning(f"[CLASSIFY] Could not get storage provider: {e}")

        # Pre-fetch all bodies from S3 in parallel
        body_map: Dict[str, str] = {}
        if storage:
            body_map = self._prefetch_bodies(stories, storage)

        run_result.total = len(stories)
        logger.info(f"[CLASSIFY] Classifying {len(stories)} pending stories")

        for story in stories:
            try:
                body_excerpt = body_map.get(str(story.id), "")

                # Get source slug
                source_slug = ""
                if story.source:
                    source_slug = story.source.slug

                # Classify
                result = self.classify(
                    title=story.original_title,
                    description=story.original_description,
                    body_excerpt=body_excerpt,
                    source_slug=source_slug,
                )

                # Update story with classification results
                story.domain = result.domain
                story.feed_category = result.feed_category
                story.classification_tags = result.tags
                story.classification_confidence = result.confidence
                story.classification_model = result.model
                story.classification_method = result.method
                story.classified_at = datetime.now(timezone.utc)

                run_result.success += 1
                if result.method == "llm":
                    run_result.llm += 1
                else:
                    run_result.keyword_fallback += 1

            except Exception as e:
                logger.error(f"[CLASSIFY] Failed to classify story {story.id}: {e}")
                run_result.failed += 1
                run_result.errors.append(f"{story.id}: {str(e)}")

        db.commit()

        logger.info(
            f"[CLASSIFY] Complete: total={run_result.total}, "
            f"success={run_result.success}, llm={run_result.llm}, "
            f"keyword_fallback={run_result.keyword_fallback}, "
            f"failed={run_result.failed}"
        )

        return run_result

    def reclassify_all(self, db: Session, limit: int = 200) -> ClassifyRunResult:
        """
        Force reclassify all stories (for migration or prompt changes).

        Same as classify_pending but ignores classified_at filter.
        Pre-fetches article bodies from S3 in parallel.
        """
        from app import models
        from app.storage.factory import get_storage_provider

        run_result = ClassifyRunResult()

        stories = (
            db.query(models.StoryRaw)
            .join(models.Source, models.StoryRaw.source_id == models.Source.id)
            .filter(models.StoryRaw.is_duplicate == False)
            .order_by(models.StoryRaw.ingested_at.desc())
            .limit(limit)
            .all()
        )

        if not stories:
            logger.info("[CLASSIFY] No stories to reclassify")
            return run_result

        storage = None
        try:
            storage = get_storage_provider()
        except Exception as e:
            logger.warning(f"[CLASSIFY] Could not get storage provider: {e}")

        # Pre-fetch all bodies from S3 in parallel
        body_map: Dict[str, str] = {}
        if storage:
            body_map = self._prefetch_bodies(stories, storage)

        run_result.total = len(stories)
        logger.info(f"[CLASSIFY] Reclassifying {len(stories)} stories")

        for story in stories:
            try:
                body_excerpt = body_map.get(str(story.id), "")

                source_slug = ""
                if story.source:
                    source_slug = story.source.slug

                result = self.classify(
                    title=story.original_title,
                    description=story.original_description,
                    body_excerpt=body_excerpt,
                    source_slug=source_slug,
                )

                story.domain = result.domain
                story.feed_category = result.feed_category
                story.classification_tags = result.tags
                story.classification_confidence = result.confidence
                story.classification_model = result.model
                story.classification_method = result.method
                story.classified_at = datetime.now(timezone.utc)

                run_result.success += 1
                if result.method == "llm":
                    run_result.llm += 1
                else:
                    run_result.keyword_fallback += 1

            except Exception as e:
                logger.error(f"[CLASSIFY] Failed to reclassify story {story.id}: {e}")
                run_result.failed += 1
                run_result.errors.append(f"{story.id}: {str(e)}")

        db.commit()

        logger.info(
            f"[CLASSIFY] Reclassify complete: total={run_result.total}, "
            f"success={run_result.success}, llm={run_result.llm}, "
            f"keyword_fallback={run_result.keyword_fallback}, "
            f"failed={run_result.failed}"
        )

        return run_result
