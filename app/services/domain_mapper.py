# app/services/domain_mapper.py
"""
Deterministic domain + geography → feed_category mapping.

Maps the 20 internal editorial domains to 10 user-facing feed categories.
15 domains map directly regardless of geography. 5 domains depend on the
geography tag (us/local/international) to route between World, U.S., and Local.
"""

from app.models import Domain, FeedCategory

# Direct mappings: domain → feed_category (geography-independent)
DIRECT_MAPPINGS: dict[str, FeedCategory] = {
    Domain.GLOBAL_AFFAIRS: FeedCategory.WORLD,
    Domain.ECONOMY_MACROECONOMICS: FeedCategory.BUSINESS,
    Domain.FINANCE_MARKETS: FeedCategory.BUSINESS,
    Domain.BUSINESS_INDUSTRY: FeedCategory.BUSINESS,
    Domain.LABOR_DEMOGRAPHICS: FeedCategory.BUSINESS,
    Domain.INFRASTRUCTURE_SYSTEMS: FeedCategory.BUSINESS,
    Domain.ENERGY: FeedCategory.ENVIRONMENT,
    Domain.ENVIRONMENT_CLIMATE: FeedCategory.ENVIRONMENT,
    Domain.SCIENCE_RESEARCH: FeedCategory.SCIENCE,
    Domain.HEALTH_MEDICINE: FeedCategory.HEALTH,
    Domain.TECHNOLOGY: FeedCategory.TECHNOLOGY,
    Domain.MEDIA_INFORMATION: FeedCategory.TECHNOLOGY,
    Domain.SPORTS_COMPETITION: FeedCategory.SPORTS,
    Domain.SOCIETY_CULTURE: FeedCategory.CULTURE,
    Domain.LIFESTYLE_PERSONAL: FeedCategory.CULTURE,
}

# Geography-dependent mappings: domain → {geography → feed_category}
GEO_DEPENDENT_MAPPINGS: dict[str, dict[str, FeedCategory]] = {
    Domain.GOVERNANCE_POLITICS: {
        "us": FeedCategory.US,
        "local": FeedCategory.US,
        "international": FeedCategory.WORLD,
        "mixed": FeedCategory.US,
    },
    Domain.LAW_JUSTICE: {
        "us": FeedCategory.US,
        "local": FeedCategory.US,
        "international": FeedCategory.WORLD,
        "mixed": FeedCategory.US,
    },
    Domain.SECURITY_DEFENSE: {
        "us": FeedCategory.US,
        "local": FeedCategory.US,
        "international": FeedCategory.WORLD,
        "mixed": FeedCategory.US,
    },
    Domain.CRIME_PUBLIC_SAFETY: {
        "us": FeedCategory.US,
        "local": FeedCategory.LOCAL,
        "international": FeedCategory.WORLD,
        "mixed": FeedCategory.US,
    },
    Domain.INCIDENTS_DISASTERS: {
        "us": FeedCategory.US,
        "local": FeedCategory.LOCAL,
        "international": FeedCategory.WORLD,
        "mixed": FeedCategory.US,
    },
}


def map_domain_to_feed_category(domain: str, geography: str = "us") -> str:
    """
    Map a domain + geography to a feed_category.

    Args:
        domain: One of the 20 Domain enum values (e.g. "governance_politics")
        geography: "us", "local", "international", or "mixed"

    Returns:
        Feed category string (e.g. "us", "world", "business")
    """
    # Normalize inputs
    domain = domain.lower().strip() if domain else ""
    geography = geography.lower().strip() if geography else "us"

    # Check direct mappings first
    if domain in DIRECT_MAPPINGS:
        return DIRECT_MAPPINGS[domain].value

    # Check geography-dependent mappings
    if domain in GEO_DEPENDENT_MAPPINGS:
        geo_map = GEO_DEPENDENT_MAPPINGS[domain]
        category = geo_map.get(geography, geo_map.get("us", FeedCategory.US))
        return category.value

    # Fallback for unknown domains
    return FeedCategory.WORLD.value
