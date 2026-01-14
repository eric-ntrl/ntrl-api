#!/usr/bin/env python
"""
Test script for Story 4.3: Grade and iterate Feed outputs until quality >= 8.5

This script:
1. Loads all 10 test corpus articles
2. First generates detail_brief for each (needed as input to feed outputs)
3. Runs _neutralize_feed_outputs() on each article
4. Grades each result with the deterministic grader
5. Scores each result with the LLM quality scorer
6. Validates feed_title <= 12 words and feed_summary <= 3 lines
7. Reports average quality score and any failures
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
from app.services.grader import grade_article, get_default_spec, grade
from app.services.quality_scorer import score_quality, score_feed_outputs


def get_feed_output_spec():
    """
    Create a grader spec for feed outputs (headlines and summaries).

    For compressed feed outputs, we skip A3 (scope markers) and A5 (certainty markers)
    because these rules are designed for full-length neutralization, not compression.

    A 6-word headline cannot preserve every marker from a 1000-word article.
    Instead, we check for:
    - No banned tokens (urgency, emotional, agenda)
    - No ALL-CAPS emphasis
    - Grammar intact
    - Headline word limits
    """
    base_spec = get_default_spec()

    # Filter out marker preservation rules that don't apply to compression
    skip_rules = {"A3_SCOPE_PRESERVED", "A5_CERTAINTY_PRESERVED"}

    filtered_rules = [
        rule for rule in base_spec["rules"]
        if rule["id"] not in skip_rules
    ]

    return {
        **base_spec,
        "rules": filtered_rules
    }


def grade_feed_output(original_text: str, neutral_text: str, neutral_headline: str = None):
    """Grade a feed output using the feed-appropriate spec."""
    spec = get_feed_output_spec()
    return grade(spec, original_text, neutral_text, neutral_headline=neutral_headline)


def load_test_corpus():
    """Load all test corpus articles."""
    corpus_dir = Path(__file__).parent.parent / "tests" / "fixtures" / "test_corpus"
    articles = []

    for i in range(1, 11):
        path = corpus_dir / f"article_{i:03d}.json"
        with open(path) as f:
            articles.append(json.load(f))

    return articles


def count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def count_lines(text: str, chars_per_line: int = 40) -> int:
    """
    Estimate number of lines for mobile display.
    Assumes ~40 chars per line on mobile.
    """
    return (len(text) + chars_per_line - 1) // chars_per_line


def validate_feed_constraints(feed_title: str, feed_summary: str, detail_title: str) -> dict:
    """
    Validate feed output constraints.
    Returns dict with validation results.
    """
    title_words = count_words(feed_title)
    summary_chars = len(feed_summary)
    summary_lines = count_lines(feed_summary, 40)

    return {
        "feed_title_words": title_words,
        "feed_title_valid": title_words <= 12,
        "feed_title_preferred": title_words <= 6,
        "feed_summary_chars": summary_chars,
        "feed_summary_lines": summary_lines,
        "feed_summary_valid": summary_lines <= 3,  # <=3 lines at 40 chars/line = <=120 chars
        "detail_title_words": count_words(detail_title),
    }


def run_test():
    """Run Feed outputs generation on test corpus and evaluate."""

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
    constraint_violations = []

    for article in articles:
        article_id = article["id"]
        original_body = article["original_body"]
        has_manipulative = article.get("has_manipulative_language", False)

        print(f"\n[Article {article_id}] {article['original_title'][:50]}...")
        print(f"  Has manipulative language: {has_manipulative}")
        print(f"  Body length: {len(original_body)} chars")

        # First, generate detail_brief (needed as input)
        try:
            detail_brief = provider._neutralize_detail_brief(original_body)
            print(f"  Detail brief generated: {len(detail_brief)} chars")
        except Exception as e:
            print(f"  ERROR: Failed to generate detail_brief: {e}")
            results.append({
                "id": article_id,
                "error": f"detail_brief generation failed: {e}",
                "grader_pass": False,
                "llm_score": 0.0,
            })
            continue

        # Run Feed outputs generation
        try:
            feed_outputs = provider._neutralize_feed_outputs(original_body, detail_brief)
            feed_title = feed_outputs.get("feed_title", "")
            feed_summary = feed_outputs.get("feed_summary", "")
            detail_title = feed_outputs.get("detail_title", "")
        except Exception as e:
            print(f"  ERROR: Failed to generate feed outputs: {e}")
            results.append({
                "id": article_id,
                "error": f"feed outputs generation failed: {e}",
                "grader_pass": False,
                "llm_score": 0.0,
            })
            continue

        print(f"  Feed title: \"{feed_title}\"")
        print(f"  Feed summary: \"{feed_summary[:80]}{'...' if len(feed_summary) > 80 else ''}\"")
        print(f"  Detail title: \"{detail_title}\"")

        # Validate constraints
        constraints = validate_feed_constraints(feed_title, feed_summary, detail_title)
        print(f"  Feed title words: {constraints['feed_title_words']} (<=12: {constraints['feed_title_valid']}, <=6 preferred: {constraints['feed_title_preferred']})")
        print(f"  Feed summary: {constraints['feed_summary_chars']} chars, ~{constraints['feed_summary_lines']} lines (<=3: {constraints['feed_summary_valid']})")

        if not constraints["feed_title_valid"]:
            print("  WARNING: feed_title exceeds 12 words!")
            constraint_violations.append({
                "id": article_id,
                "type": "feed_title_too_long",
                "value": feed_title,
                "words": constraints["feed_title_words"],
            })

        if not constraints["feed_summary_valid"]:
            print("  WARNING: feed_summary exceeds 3 lines!")
            constraint_violations.append({
                "id": article_id,
                "type": "feed_summary_too_long",
                "value": feed_summary,
                "chars": constraints["feed_summary_chars"],
            })

        # Build combined text for grading (all 3 outputs)
        combined_neutral = f"HEADLINE: {feed_title}\n\nSUMMARY: {feed_summary}\n\nDETAIL HEADLINE: {detail_title}"

        # Grade with deterministic grader (grade each output)
        # Use feed-specific grader that skips A3/A5 marker preservation rules
        # (those rules are for full-length neutralization, not compression)

        # Grade feed_title as headline
        grader_result_title = grade_feed_output(
            original_text=original_body,
            neutral_text=feed_title,
            neutral_headline=feed_title,
        )

        # Grade feed_summary
        grader_result_summary = grade_feed_output(
            original_text=original_body,
            neutral_text=feed_summary,
        )

        # Grade detail_title as headline
        grader_result_detail_title = grade_feed_output(
            original_text=original_body,
            neutral_text=detail_title,
            neutral_headline=detail_title,
        )

        # Overall pass if all pass
        grader_pass = (
            grader_result_title["overall_pass"] and
            grader_result_summary["overall_pass"] and
            grader_result_detail_title["overall_pass"]
        )

        print(f"  Grader - feed_title: {grader_result_title['overall_pass']}, feed_summary: {grader_result_summary['overall_pass']}, detail_title: {grader_result_detail_title['overall_pass']}")

        if not grader_pass:
            failed_rules = []
            for result, name in [
                (grader_result_title, "feed_title"),
                (grader_result_summary, "feed_summary"),
                (grader_result_detail_title, "detail_title"),
            ]:
                for rule in result["results"]:
                    if not rule["passed"]:
                        failed_rules.append({**rule, "output": name})
                        print(f"    FAILED ({name}): {rule['rule_id']} - {rule['message']}")

            grader_failures.append({
                "id": article_id,
                "failed_rules": failed_rules,
            })

        # Score with LLM quality scorer (using feed-specific rubric)
        try:
            quality_result = score_feed_outputs(
                original_text=original_body,
                feed_title=feed_title,
                feed_summary=feed_summary,
                detail_title=detail_title,
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
            "feed_title": feed_title,
            "feed_summary": feed_summary,
            "detail_title": detail_title,
            "detail_brief": detail_brief,
            "constraints": constraints,
            "grader_pass": grader_pass,
            "grader_results": {
                "feed_title": grader_result_title,
                "feed_summary": grader_result_summary,
                "detail_title": grader_result_detail_title,
            },
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

    # Constraint summary
    title_valid_count = sum(1 for r in results if r.get("constraints", {}).get("feed_title_valid", False))
    title_preferred_count = sum(1 for r in results if r.get("constraints", {}).get("feed_title_preferred", False))
    summary_valid_count = sum(1 for r in results if r.get("constraints", {}).get("feed_summary_valid", False))

    print(f"\nFeed title <=12 words: {title_valid_count}/{len(articles)}")
    print(f"Feed title <=6 words (preferred): {title_preferred_count}/{len(articles)}")
    print(f"Feed summary <=3 lines: {summary_valid_count}/{len(articles)}")

    if grader_failures:
        print(f"\nGrader failures ({len(grader_failures)}):")
        for failure in grader_failures:
            print(f"  Article {failure['id']}:")
            for rule in failure["failed_rules"]:
                print(f"    - [{rule.get('output', 'unknown')}] {rule['rule_id']}: {rule['message']}")

    if constraint_violations:
        print(f"\nConstraint violations ({len(constraint_violations)}):")
        for violation in constraint_violations:
            print(f"  Article {violation['id']}: {violation['type']}")
            if "words" in violation:
                print(f"    Value: \"{violation['value']}\" ({violation['words']} words)")
            else:
                print(f"    Value: \"{violation['value'][:50]}...\" ({violation.get('chars', '?')} chars)")

    # Quality check
    quality_threshold = 8.5
    all_constraints_met = (
        title_valid_count == len(articles) and
        summary_valid_count == len(articles)
    )

    if avg_score >= quality_threshold:
        print(f"\n✓ QUALITY THRESHOLD MET: {avg_score:.2f} >= {quality_threshold}")
    else:
        print(f"\n✗ QUALITY THRESHOLD NOT MET: {avg_score:.2f} < {quality_threshold}")

    if grader_pass_count == len(articles):
        print("✓ ALL ARTICLES PASS DETERMINISTIC GRADER")
    else:
        print(f"✗ {len(articles) - grader_pass_count} ARTICLES FAILED DETERMINISTIC GRADER")

    if all_constraints_met:
        print("✓ ALL FEED OUTPUTS MEET CONSTRAINTS (feed_title <=12 words, feed_summary <=3 lines)")
    else:
        print(f"✗ CONSTRAINT VIOLATIONS: {len(constraint_violations)}")

    # Return results for programmatic use
    return {
        "total_articles": len(articles),
        "grader_pass_count": grader_pass_count,
        "average_llm_score": avg_score,
        "quality_threshold_met": avg_score >= quality_threshold,
        "all_grader_pass": grader_pass_count == len(articles),
        "all_constraints_met": all_constraints_met,
        "title_valid_count": title_valid_count,
        "summary_valid_count": summary_valid_count,
        "results": results,
        "grader_failures": grader_failures,
        "constraint_violations": constraint_violations,
    }


if __name__ == "__main__":
    summary = run_test()

    # Write results to file for analysis
    output_path = Path(__file__).parent / "feed_outputs_results.json"
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nResults written to: {output_path}")

    # Exit with appropriate code
    if (summary["quality_threshold_met"] and
        summary["all_grader_pass"] and
        summary["all_constraints_met"]):
        sys.exit(0)
    else:
        sys.exit(1)
