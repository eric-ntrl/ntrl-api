#!/usr/bin/env python
"""
End-to-end test script for Story 5.3: Full pipeline testing with test corpus

This script:
1. Loads all 10 test corpus articles
2. Runs the FULL neutralization pipeline on each (3 LLM calls, 6 outputs)
3. Grades ALL outputs with the deterministic grader
4. Scores outputs with the LLM quality scorer
5. Validates all 6 outputs are generated for each article
6. Reports average quality score and any failures

This is the final validation that the complete pipeline works as designed.
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
    NeutralizationResult,
)
from app.services.grader import grade_article, get_default_spec, grade
from app.services.quality_scorer import score_quality, score_feed_outputs


def get_feed_output_spec():
    """
    Create a grader spec for feed outputs (headlines and summaries).

    For compressed feed outputs, we skip A3 (scope markers) and A5 (certainty markers)
    because these rules are designed for full-length neutralization, not compression.
    """
    base_spec = get_default_spec()
    skip_rules = {"A3_SCOPE_PRESERVED", "A5_CERTAINTY_PRESERVED"}
    filtered_rules = [
        rule for rule in base_spec["rules"]
        if rule["id"] not in skip_rules
    ]
    return {**base_spec, "rules": filtered_rules}


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
    return len(text.split()) if text else 0


def run_full_pipeline(provider, body: str) -> dict:
    """
    Run the full 3-call neutralization pipeline.

    Returns dict with all 6 outputs and spans.
    """
    result = {}

    # Call 1: Filter & Track (detail_full + spans)
    detail_full_result = provider._neutralize_detail_full(body)
    result["detail_full"] = detail_full_result.detail_full
    result["spans"] = detail_full_result.spans

    # Call 2: Synthesize (detail_brief)
    result["detail_brief"] = provider._neutralize_detail_brief(body)

    # Call 3: Compress (feed_title, feed_summary, detail_title)
    feed_outputs = provider._neutralize_feed_outputs(body, result["detail_brief"])
    result["feed_title"] = feed_outputs.get("feed_title", "")
    result["feed_summary"] = feed_outputs.get("feed_summary", "")
    result["detail_title"] = feed_outputs.get("detail_title", "")

    return result


def validate_outputs(outputs: dict) -> dict:
    """Validate that all 6 outputs are present and meet basic requirements."""
    required_fields = ["feed_title", "feed_summary", "detail_title", "detail_brief", "detail_full"]

    validation = {
        "all_present": True,
        "missing_fields": [],
        "field_lengths": {},
        "feed_title_words": 0,
        "feed_title_valid": False,
        "detail_title_words": 0,
    }

    for field in required_fields:
        value = outputs.get(field, "")
        if not value:
            validation["all_present"] = False
            validation["missing_fields"].append(field)
        else:
            validation["field_lengths"][field] = len(value)

    # Specific validations
    feed_title = outputs.get("feed_title", "")
    validation["feed_title_words"] = count_words(feed_title)
    validation["feed_title_valid"] = validation["feed_title_words"] <= 12

    detail_title = outputs.get("detail_title", "")
    validation["detail_title_words"] = count_words(detail_title)

    return validation


def grade_all_outputs(original_body: str, outputs: dict) -> dict:
    """Grade all outputs with deterministic grader."""
    full_spec = get_default_spec()
    feed_spec = get_feed_output_spec()

    results = {}

    # Grade detail_full (full article - use full spec)
    if outputs.get("detail_full"):
        results["detail_full"] = grade_article(
            original_text=original_body,
            neutral_text=outputs["detail_full"],
        )

    # Grade detail_brief (summarized - use full spec)
    if outputs.get("detail_brief"):
        results["detail_brief"] = grade_article(
            original_text=original_body,
            neutral_text=outputs["detail_brief"],
        )

    # Grade feed outputs (compressed - use feed spec without A3/A5)
    if outputs.get("feed_title"):
        results["feed_title"] = grade(
            feed_spec,
            original_text=original_body,
            neutral_text=outputs["feed_title"],
            neutral_headline=outputs["feed_title"],
        )

    if outputs.get("feed_summary"):
        results["feed_summary"] = grade(
            feed_spec,
            original_text=original_body,
            neutral_text=outputs["feed_summary"],
        )

    if outputs.get("detail_title"):
        results["detail_title"] = grade(
            feed_spec,
            original_text=original_body,
            neutral_text=outputs["detail_title"],
            neutral_headline=outputs["detail_title"],
        )

    return results


def score_all_outputs(original_body: str, outputs: dict, provider: str = "openai") -> dict:
    """Score all outputs with LLM quality scorer."""
    scores = {}

    # Score detail_full
    if outputs.get("detail_full"):
        try:
            result = score_quality(
                original_text=original_body,
                neutral_text=outputs["detail_full"],
                provider=provider,
            )
            scores["detail_full"] = {
                "score": result.score,
                "feedback": result.feedback,
                "violations": result.rule_violations,
            }
        except Exception as e:
            scores["detail_full"] = {"score": 0.0, "feedback": f"Error: {e}", "violations": []}

    # Score detail_brief
    if outputs.get("detail_brief"):
        try:
            result = score_quality(
                original_text=original_body,
                neutral_text=outputs["detail_brief"],
                provider=provider,
            )
            scores["detail_brief"] = {
                "score": result.score,
                "feedback": result.feedback,
                "violations": result.rule_violations,
            }
        except Exception as e:
            scores["detail_brief"] = {"score": 0.0, "feedback": f"Error: {e}", "violations": []}

    # Score feed outputs together
    if outputs.get("feed_title") and outputs.get("feed_summary") and outputs.get("detail_title"):
        try:
            result = score_feed_outputs(
                original_text=original_body,
                feed_title=outputs["feed_title"],
                feed_summary=outputs["feed_summary"],
                detail_title=outputs["detail_title"],
                provider=provider,
            )
            scores["feed_outputs"] = {
                "score": result.score,
                "feedback": result.feedback,
                "violations": result.rule_violations,
            }
        except Exception as e:
            scores["feed_outputs"] = {"score": 0.0, "feedback": f"Error: {e}", "violations": []}

    return scores


def run_test():
    """Run end-to-end pipeline test on test corpus."""

    # Check for API key
    if not os.getenv("OPENAI_API_KEY"):
        print("WARNING: No OPENAI_API_KEY set, using mock provider")
        provider = MockNeutralizerProvider()
    else:
        provider = OpenAINeutralizerProvider(model="gpt-4o-mini")

    print(f"Using provider: {provider.name} ({provider.model_name})")
    print("=" * 80)
    print("END-TO-END PIPELINE TEST")
    print("=" * 80)

    articles = load_test_corpus()
    results = []

    # Tracking metrics
    all_outputs_generated = 0
    grader_pass_count = 0
    llm_scores = {"detail_full": [], "detail_brief": [], "feed_outputs": []}
    failures = []

    for article in articles:
        article_id = article["id"]
        original_body = article["original_body"]
        has_manipulative = article.get("has_manipulative_language", False)

        print(f"\n[Article {article_id}] {article['original_title'][:50]}...")
        print(f"  Has manipulative language: {has_manipulative}")

        # Run full pipeline
        try:
            outputs = run_full_pipeline(provider, original_body)
        except Exception as e:
            print(f"  ERROR: Pipeline failed: {e}")
            failures.append({"id": article_id, "error": str(e)})
            continue

        # Validate outputs
        validation = validate_outputs(outputs)

        if validation["all_present"]:
            all_outputs_generated += 1
            print(f"  All 6 outputs generated")
        else:
            print(f"  MISSING outputs: {validation['missing_fields']}")
            failures.append({"id": article_id, "missing": validation["missing_fields"]})

        # Show output summaries
        print(f"    feed_title ({validation['feed_title_words']} words): \"{outputs.get('feed_title', '')[:60]}...\"")
        print(f"    feed_summary: \"{outputs.get('feed_summary', '')[:60]}...\"")
        print(f"    detail_title: \"{outputs.get('detail_title', '')[:60]}...\"")
        print(f"    detail_brief: {validation['field_lengths'].get('detail_brief', 0)} chars")
        print(f"    detail_full: {validation['field_lengths'].get('detail_full', 0)} chars")
        print(f"    spans: {len(outputs.get('spans', []))} changes tracked")

        # Grade all outputs
        grader_results = grade_all_outputs(original_body, outputs)

        all_pass = all(r.get("overall_pass", False) for r in grader_results.values())
        if all_pass:
            grader_pass_count += 1
            print(f"  Deterministic grader: ALL PASS")
        else:
            failed_outputs = [k for k, v in grader_results.items() if not v.get("overall_pass", False)]
            print(f"  Deterministic grader: FAILED ({', '.join(failed_outputs)})")
            for output_name, result in grader_results.items():
                if not result.get("overall_pass", False):
                    for rule in result.get("results", []):
                        if not rule.get("passed", True):
                            print(f"    [{output_name}] {rule.get('rule_id', '?')}: {rule.get('message', '?')}")

        # Score with LLM
        scores = score_all_outputs(original_body, outputs, provider="openai")

        for output_type, score_data in scores.items():
            score = score_data.get("score", 0.0)
            if output_type in llm_scores:
                llm_scores[output_type].append(score)
            print(f"  LLM score ({output_type}): {score:.1f}")

        # Store result
        results.append({
            "id": article_id,
            "has_manipulative": has_manipulative,
            "validation": validation,
            "outputs": {k: v if k != "spans" else f"{len(v)} spans" for k, v in outputs.items()},
            "grader_results": {k: v.get("overall_pass", False) for k, v in grader_results.items()},
            "grader_all_pass": all_pass,
            "llm_scores": {k: v.get("score", 0.0) for k, v in scores.items()},
        })

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    print(f"\nArticles processed: {len(articles)}")
    print(f"All 6 outputs generated: {all_outputs_generated}/{len(articles)}")
    print(f"Deterministic grader passed: {grader_pass_count}/{len(articles)}")

    # Calculate average scores
    avg_scores = {}
    for output_type, scores_list in llm_scores.items():
        if scores_list:
            avg_scores[output_type] = sum(scores_list) / len(scores_list)
            print(f"Average LLM score ({output_type}): {avg_scores[output_type]:.2f}")

    overall_avg = sum(avg_scores.values()) / len(avg_scores) if avg_scores else 0.0
    print(f"\nOverall average LLM score: {overall_avg:.2f}")

    # Quality check
    quality_threshold = 8.5
    all_thresholds_met = all(score >= quality_threshold for score in avg_scores.values())

    print(f"\n" + "-" * 40)
    if all_outputs_generated == len(articles):
        print("PASS: All 6 outputs generated for each article")
    else:
        print(f"FAIL: Only {all_outputs_generated}/{len(articles)} articles have all 6 outputs")

    if grader_pass_count == len(articles):
        print("PASS: All outputs pass deterministic grader")
    else:
        print(f"FAIL: {len(articles) - grader_pass_count} articles failed deterministic grader")

    if all_thresholds_met:
        print(f"PASS: All LLM quality scores >= {quality_threshold}")
    else:
        below_threshold = {k: v for k, v in avg_scores.items() if v < quality_threshold}
        print(f"FAIL: Some scores below {quality_threshold}: {below_threshold}")

    success = (
        all_outputs_generated == len(articles) and
        grader_pass_count == len(articles) and
        all_thresholds_met
    )

    print(f"\n{'SUCCESS' if success else 'FAILURE'}: End-to-end pipeline test {'passed' if success else 'failed'}")

    return {
        "total_articles": len(articles),
        "all_outputs_generated": all_outputs_generated,
        "grader_pass_count": grader_pass_count,
        "avg_scores": avg_scores,
        "overall_avg_score": overall_avg,
        "quality_threshold_met": all_thresholds_met,
        "success": success,
        "results": results,
        "failures": failures,
    }


if __name__ == "__main__":
    summary = run_test()

    # Write results to file for analysis
    output_path = Path(__file__).parent / "e2e_pipeline_results.json"
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nResults written to: {output_path}")

    # Exit with appropriate code
    sys.exit(0 if summary["success"] else 1)
