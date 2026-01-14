#!/usr/bin/env python
"""
Test script for Story 3.3: Grade and iterate Detail Brief until quality >= 8.5

This script:
1. Loads all 10 test corpus articles
2. Runs _neutralize_detail_brief() on each article
3. Grades each result with the deterministic grader
4. Scores each result with the LLM quality scorer
5. Reports average quality score and any failures
"""

import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Override prompt loading to use defaults directly (bypass DB)
import app.services.neutralizer as neutralizer_module
neutralizer_module._prompt_cache = {}  # Clear cache
neutralizer_module._active_model_cache = None

# Monkey-patch to use defaults
original_get_prompt = neutralizer_module.get_prompt
def get_prompt_with_defaults(name: str, default: str) -> str:
    """Return defaults directly without DB lookup."""
    return default
neutralizer_module.get_prompt = get_prompt_with_defaults

original_get_active_model = neutralizer_module.get_active_model
def get_active_model_bypass() -> str:
    """Return the model directly."""
    return "gpt-4o-mini"
neutralizer_module.get_active_model = get_active_model_bypass

from app.services.neutralizer import (
    OpenAINeutralizerProvider,
    MockNeutralizerProvider,
)
from app.services.grader import grade_article
from app.services.quality_scorer import score_quality


def load_test_corpus():
    """Load all test corpus articles."""
    corpus_dir = Path(__file__).parent.parent / "tests" / "fixtures" / "test_corpus"
    articles = []

    for i in range(1, 11):
        path = corpus_dir / f"article_{i:03d}.json"
        with open(path) as f:
            articles.append(json.load(f))

    return articles


def analyze_brief_structure(brief: str) -> dict:
    """
    Analyze if brief follows the grounding->context->knowledge->uncertainty flow.
    Returns analysis dict.
    """
    paragraphs = [p.strip() for p in brief.split('\n\n') if p.strip()]

    analysis = {
        "paragraph_count": len(paragraphs),
        "valid_paragraph_count": 3 <= len(paragraphs) <= 5,
        "has_headers": any(line.endswith(':') for line in brief.split('\n')),
        "has_bullets": any(line.strip().startswith(('-', '*', '•')) for line in brief.split('\n')),
        "has_numbers": any(line.strip().startswith(tuple(f"{i}." for i in range(1, 10))) for line in brief.split('\n')),
        "word_count": len(brief.split()),
        "valid_word_count": 100 <= len(brief.split()) <= 400,
    }

    # Check for forbidden patterns
    forbidden_headers = ["what happened", "context", "background", "uncertainty", "what is known"]
    analysis["has_forbidden_headers"] = any(
        h in brief.lower() for h in forbidden_headers
    )

    return analysis


def run_test():
    """Run Detail Brief generation on test corpus and evaluate."""

    # Check for API key
    if not os.getenv("OPENAI_API_KEY"):
        print("WARNING: No OPENAI_API_KEY set, using mock provider")
        provider = MockNeutralizerProvider()
    else:
        provider = OpenAINeutralizerProvider(model="gpt-4o-mini")

    print(f"Using provider: {provider.name} ({provider.model_name})")
    print("=" * 80)

    articles = load_test_corpus()

    results = []
    total_score = 0.0
    grader_failures = []
    llm_scores = []
    structure_issues = []

    for article in articles:
        article_id = article["id"]
        original_body = article["original_body"]
        has_manipulative = article.get("has_manipulative_language", False)

        print(f"\n[Article {article_id}] {article['original_title'][:50]}...")
        print(f"  Has manipulative language: {has_manipulative}")
        print(f"  Body length: {len(original_body)} chars")

        # Run Detail Brief generation
        try:
            detail_brief = provider._neutralize_detail_brief(original_body)
        except Exception as e:
            print(f"  ERROR: Failed to neutralize: {e}")
            results.append({
                "id": article_id,
                "error": str(e),
                "grader_pass": False,
                "llm_score": 0.0,
            })
            continue

        print(f"  Detail brief length: {len(detail_brief)} chars")

        # Analyze structure
        structure = analyze_brief_structure(detail_brief)
        print(f"  Paragraphs: {structure['paragraph_count']} (valid: {structure['valid_paragraph_count']})")
        print(f"  Words: {structure['word_count']} (valid: {structure['valid_word_count']})")

        if structure["has_headers"]:
            print("  WARNING: Contains headers (forbidden)")
        if structure["has_bullets"]:
            print("  WARNING: Contains bullets (forbidden)")
        if structure["has_forbidden_headers"]:
            print("  WARNING: Contains forbidden header text")

        if not structure["valid_paragraph_count"] or structure["has_headers"] or structure["has_bullets"]:
            structure_issues.append({
                "id": article_id,
                "issues": structure,
            })

        # Grade with deterministic grader
        grader_result = grade_article(
            original_text=original_body,
            neutral_text=detail_brief,
        )

        grader_pass = grader_result["overall_pass"]
        print(f"  Grader pass: {grader_pass}")

        if not grader_pass:
            failed_rules = [r for r in grader_result["results"] if not r["passed"]]
            for rule in failed_rules:
                print(f"    FAILED: {rule['rule_id']} - {rule['message']}")
            grader_failures.append({
                "id": article_id,
                "failed_rules": failed_rules,
            })

        # Score with LLM quality scorer
        try:
            quality_result = score_quality(
                original_text=original_body,
                neutral_text=detail_brief,
                provider="openai",
            )
            llm_score = quality_result.score
            feedback = quality_result.feedback
            violations = quality_result.rule_violations
        except Exception as e:
            print(f"  WARNING: LLM scoring failed: {e}")
            llm_score = 0.0
            feedback = f"Scoring failed: {e}"
            violations = []

        print(f"  LLM quality score: {llm_score}")
        if feedback:
            print(f"  Feedback: {feedback}")
        if violations:
            print(f"  Violations: {[v.get('rule', 'unknown') for v in violations]}")

        total_score += llm_score
        llm_scores.append(llm_score)

        results.append({
            "id": article_id,
            "has_manipulative": has_manipulative,
            "original_length": len(original_body),
            "detail_brief_length": len(detail_brief),
            "detail_brief": detail_brief,
            "structure": structure,
            "grader_pass": grader_pass,
            "llm_score": llm_score,
            "feedback": feedback,
            "violations": violations,
        })

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    avg_score = total_score / len(articles) if articles else 0.0
    grader_pass_count = sum(1 for r in results if r.get("grader_pass", False))

    print(f"\nArticles processed: {len(articles)}")
    print(f"Deterministic grader: {grader_pass_count}/{len(articles)} passed")
    print(f"Average LLM quality score: {avg_score:.2f}")
    print(f"Individual scores: {llm_scores}")

    if grader_failures:
        print(f"\nGrader failures ({len(grader_failures)}):")
        for failure in grader_failures:
            print(f"  Article {failure['id']}:")
            for rule in failure["failed_rules"]:
                print(f"    - {rule['rule_id']}: {rule['message']}")

    if structure_issues:
        print(f"\nStructure issues ({len(structure_issues)}):")
        for issue in structure_issues:
            print(f"  Article {issue['id']}: {issue['issues']}")

    # Quality check
    quality_threshold = 8.5
    if avg_score >= quality_threshold:
        print(f"\n✓ QUALITY THRESHOLD MET: {avg_score:.2f} >= {quality_threshold}")
    else:
        print(f"\n✗ QUALITY THRESHOLD NOT MET: {avg_score:.2f} < {quality_threshold}")

    if grader_pass_count == len(articles):
        print("✓ ALL ARTICLES PASS DETERMINISTIC GRADER")
    else:
        print(f"✗ {len(articles) - grader_pass_count} ARTICLES FAILED DETERMINISTIC GRADER")

    if len(structure_issues) == 0:
        print("✓ ALL BRIEFS FOLLOW PROPER STRUCTURE (3-5 paragraphs, no headers/bullets)")
    else:
        print(f"✗ {len(structure_issues)} BRIEFS HAVE STRUCTURE ISSUES")

    # Return results for programmatic use
    return {
        "total_articles": len(articles),
        "grader_pass_count": grader_pass_count,
        "average_llm_score": avg_score,
        "quality_threshold_met": avg_score >= quality_threshold,
        "all_grader_pass": grader_pass_count == len(articles),
        "structure_issues_count": len(structure_issues),
        "results": results,
        "grader_failures": grader_failures,
        "structure_issues": structure_issues,
    }


if __name__ == "__main__":
    summary = run_test()

    # Write results to file for analysis
    output_path = Path(__file__).parent / "detail_brief_results.json"
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nResults written to: {output_path}")

    # Exit with appropriate code
    if summary["quality_threshold_met"] and summary["all_grader_pass"]:
        sys.exit(0)
    else:
        sys.exit(1)
