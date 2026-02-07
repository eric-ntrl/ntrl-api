# app/schemas/search.py
"""
Schemas for search endpoints.

GET /v1/search - Full-text search with facets and suggestions
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SearchResultItem(BaseModel):
    """A single search result (article)."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Story ID (UUID)")
    feed_title: str = Field(..., description="Neutralized title")
    feed_summary: str = Field(..., description="Neutralized summary")
    detail_title: str | None = Field(None, description="Detailed headline")
    detail_brief: str | None = Field(None, description="3-5 paragraph brief")
    source_name: str = Field(..., description="Publisher name (e.g., AP, Reuters)")
    source_slug: str = Field(..., description="Publisher slug for filtering")
    source_url: str = Field(..., description="Original article URL")
    feed_category: str | None = Field(None, description="Category (world, us, technology, etc.)")
    published_at: datetime = Field(..., description="Original publish time")
    has_manipulative_content: bool = Field(..., description="Whether manipulative content was found")
    rank: float | None = Field(None, description="Search relevance score")


class FacetCount(BaseModel):
    """A count for a facet value."""

    key: str = Field(..., description="Facet value key (e.g., 'world', 'ap')")
    label: str = Field(..., description="Display label (e.g., 'World', 'Associated Press')")
    count: int = Field(..., description="Number of matching results")


class SearchFacets(BaseModel):
    """Facet counts for filtering."""

    categories: list[FacetCount] = Field(default_factory=list, description="Counts by feed category")
    sources: list[FacetCount] = Field(default_factory=list, description="Counts by publisher")


class SearchSuggestion(BaseModel):
    """An auto-complete suggestion."""

    type: Literal["section", "publisher", "recent"] = Field(..., description="Suggestion type")
    value: str = Field(..., description="Value to use for search/filter")
    label: str = Field(..., description="Display label")
    count: int | None = Field(None, description="Result count (for sections/publishers)")


class SearchResponse(BaseModel):
    """Response from the search endpoint."""

    query: str = Field(..., description="The search query")
    total: int = Field(..., description="Total matching results")
    limit: int = Field(..., description="Results per page")
    offset: int = Field(..., description="Current offset")
    items: list[SearchResultItem] = Field(default_factory=list, description="Search results for current page")
    facets: SearchFacets = Field(default_factory=SearchFacets, description="Facet counts for filters")
    suggestions: list[SearchSuggestion] = Field(
        default_factory=list, description="Auto-complete suggestions (for short queries)"
    )
