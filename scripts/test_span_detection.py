#!/usr/bin/env python3
"""
Test span detection against real articles.

Usage:
    # Test against staging API
    python scripts/test_span_detection.py

    # Test specific article
    python scripts/test_span_detection.py --article-id <uuid>

    # Test with local body file
    python scripts/test_span_detection.py --body-file /path/to/article.txt
"""

import argparse
import json
import os
import sys
from typing import Optional

import requests

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Staging API config
STAGING_API_URL = "https://api-staging-7b4d.up.railway.app"
API_KEY = "staging-key-123"


def get_brief_articles(hours: int = 24, limit: int = 10) -> list:
    """Get articles from the current brief."""
    url = f"{STAGING_API_URL}/v1/brief"
    params = {"hours": hours}
    headers = {"X-API-Key": API_KEY}

    response = requests.get(url, params=params, headers=headers)
    response.raise_for_status()

    data = response.json()
    articles = []
    for section in data.get("sections", []):
        for story in section.get("stories", []):
            articles.append({
                "id": story["id"],
                "title": story.get("title", ""),
                "section": section.get("section", ""),
            })
            if len(articles) >= limit:
                return articles
    return articles


def debug_spans(article_id: str) -> dict:
    """Call the debug/spans endpoint for an article."""
    url = f"{STAGING_API_URL}/v1/stories/{article_id}/debug/spans"
    headers = {"X-API-Key": API_KEY}

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def test_local_body(body: str) -> dict:
    """Test span detection locally against a body text."""
    from dotenv import load_dotenv
    load_dotenv()

    from app.services.neutralizer import detect_spans_debug_openai

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set in environment")
        sys.exit(1)

    model = os.environ.get("SPAN_DETECTION_MODEL", "gpt-5-mini")
    result = detect_spans_debug_openai(body, api_key, model)

    return {
        "llm_raw_response": result.llm_raw_response[:500] if result.llm_raw_response else None,
        "llm_phrases_count": len(result.llm_phrases),
        "llm_phrases": result.llm_phrases,
        "pipeline_trace": {
            "after_position_matching": len(result.spans_after_position),
            "after_quote_filter": len(result.spans_after_quotes),
            "after_false_positive_filter": len(result.spans_final),
            "phrases_filtered_by_quotes": result.filtered_by_quotes,
            "phrases_filtered_as_false_positives": result.filtered_as_false_positives,
            "phrases_not_found_in_text": result.not_found_in_text,
        },
        "final_span_count": len(result.spans_final),
        "final_spans": [
            {
                "text": s.original_text,
                "reason": s.reason.value if hasattr(s.reason, 'value') else str(s.reason),
                "action": s.action.value if hasattr(s.action, 'value') else str(s.action),
            }
            for s in result.spans_final
        ],
        "error": result.error,
    }


def print_result(article_id: str, title: str, result: dict) -> None:
    """Pretty print a debug result."""
    print(f"\n{'='*80}")
    print(f"Article: {article_id}")
    print(f"Title: {title[:60]}..." if len(title) > 60 else f"Title: {title}")
    print(f"{'='*80}")

    print(f"\nLLM returned {result.get('llm_phrases_count', 0)} phrases")

    trace = result.get("pipeline_trace", {})
    print(f"\nPipeline trace:")
    print(f"  After position matching: {trace.get('after_position_matching', 0)}")
    print(f"  After quote filter: {trace.get('after_quote_filter', 0)}")
    print(f"  After FP filter: {trace.get('after_false_positive_filter', 0)}")

    if trace.get("phrases_not_found_in_text"):
        print(f"\n  Not found in text: {trace['phrases_not_found_in_text']}")
    if trace.get("phrases_filtered_by_quotes"):
        print(f"  Filtered by quotes: {trace['phrases_filtered_by_quotes']}")
    if trace.get("phrases_filtered_as_false_positives"):
        print(f"  Filtered as FPs: {trace['phrases_filtered_as_false_positives']}")

    print(f"\nFinal span count: {result.get('final_span_count', 0)}")

    llm_phrases = result.get("llm_phrases", [])
    if llm_phrases:
        print("\nLLM phrases:")
        for p in llm_phrases[:15]:  # Show first 15
            phrase = p.get("phrase", "") if isinstance(p, dict) else p
            reason = p.get("reason", "?") if isinstance(p, dict) else "?"
            print(f"  - \"{phrase}\" ({reason})")
        if len(llm_phrases) > 15:
            print(f"  ... and {len(llm_phrases) - 15} more")

    final_spans = result.get("final_spans", [])
    if final_spans:
        print("\nFinal spans (after filtering):")
        for s in final_spans:
            text = s.get("text") or s.get("original_text", "")
            reason = s.get("reason", "?")
            print(f"  - \"{text}\" ({reason})")


def main():
    parser = argparse.ArgumentParser(description="Test span detection")
    parser.add_argument("--article-id", help="Test specific article by ID")
    parser.add_argument("--body-file", help="Test with local body file")
    parser.add_argument("--limit", type=int, default=5, help="Number of articles to test")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.body_file:
        # Test local body file
        with open(args.body_file) as f:
            body = f.read()
        result = test_local_body(body)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print_result("local", args.body_file, result)
        return

    if args.article_id:
        # Test specific article
        result = debug_spans(args.article_id)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print_result(args.article_id, result.get("story_id", ""), result)
        return

    # Test multiple articles from brief
    print(f"Fetching {args.limit} articles from staging brief...")
    articles = get_brief_articles(limit=args.limit)

    if not articles:
        print("No articles found in brief")
        return

    print(f"Found {len(articles)} articles")

    results = []
    for article in articles:
        try:
            result = debug_spans(article["id"])
            results.append({
                "id": article["id"],
                "title": article["title"],
                "result": result,
            })
            if not args.json:
                print_result(article["id"], article["title"], result)
        except Exception as e:
            print(f"\nERROR testing {article['id']}: {e}")

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        # Summary
        print(f"\n{'='*80}")
        print("SUMMARY")
        print(f"{'='*80}")
        for r in results:
            span_count = r["result"].get("final_span_count", 0)
            llm_count = r["result"].get("llm_phrases_count", 0)
            title = r["title"][:40] + "..." if len(r["title"]) > 40 else r["title"]
            print(f"  {title}: LLM={llm_count}, Final={span_count}")


if __name__ == "__main__":
    main()
