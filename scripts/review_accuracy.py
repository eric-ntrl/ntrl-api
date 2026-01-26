#!/usr/bin/env python3
"""
Human Review CLI for NtrlView Highlight Accuracy

This script allows human reviewers to:
1. View articles with predicted highlights (colored terminal output)
2. Grade each span: [C]orrect / [I]ncorrect / [P]artial / [S]kip
3. Record reasons for incorrect grades
4. Save results to tests/fixtures/reviews/
5. Update gold standard based on LLM predictions

Usage:
    # Review specific article (pattern-based mock provider)
    python scripts/review_accuracy.py --article 001

    # Review with LLM provider
    python scripts/review_accuracy.py --article 001 --provider openai

    # Update gold standard from LLM predictions
    python scripts/review_accuracy.py --update-gold 001 --provider openai

    # Generate aggregate report
    python scripts/review_accuracy.py --generate-report

    # List all articles needing review
    python scripts/review_accuracy.py --list
"""

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.neutralizer import (
    MockNeutralizerProvider,
    TransparencySpan,
    detect_spans_via_llm_openai,
    detect_spans_via_llm_anthropic,
    detect_spans_via_llm_gemini,
)
from app.models import SpanReason

# ANSI color codes for terminal output
class Colors:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    BG_YELLOW = "\033[103m"
    BG_RED = "\033[101m"


# Paths
FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
TEST_CORPUS_DIR = FIXTURES_DIR / "test_corpus"
GOLD_STANDARD_DIR = FIXTURES_DIR / "gold_standard"
REVIEWS_DIR = FIXTURES_DIR / "reviews"
METRICS_DIR = FIXTURES_DIR / "metrics"


@dataclass
class SpanGrade:
    """Grade for a single span."""
    span_index: int
    original_text: str
    start_char: int
    end_char: int
    reason: str
    grade: str  # C=Correct, I=Incorrect, P=Partial, S=Skip
    reviewer_note: str = ""


@dataclass
class ArticleReview:
    """Complete review of an article."""
    article_id: str
    reviewed_at: str
    reviewer: str
    total_spans: int
    grades: List[SpanGrade]
    false_negatives_noted: List[str]  # Phrases that should have been detected
    overall_notes: str


def load_article(article_id: str) -> dict:
    """Load a test article."""
    path = TEST_CORPUS_DIR / f"article_{article_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Article not found: {path}")
    with open(path) as f:
        return json.load(f)


def load_gold_standard(article_id: str) -> dict:
    """Load gold standard spans for an article."""
    path = GOLD_STANDARD_DIR / f"article_{article_id}_spans.json"
    if not path.exists():
        return {"article_id": article_id, "expected_spans": []}
    with open(path) as f:
        return json.load(f)


def save_gold_standard(article_id: str, data: dict):
    """Save gold standard spans for an article."""
    path = GOLD_STANDARD_DIR / f"article_{article_id}_spans.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"{Colors.GREEN}Saved gold standard: {path}{Colors.RESET}")


def get_llm_spans(body: str, provider: str) -> List[TransparencySpan]:
    """
    Get spans using an LLM provider.

    Args:
        body: Article body text
        provider: Provider name (openai, anthropic, gemini)

    Returns:
        List of TransparencySpan objects
    """
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        return detect_spans_via_llm_openai(body, api_key, model)

    elif provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        model = os.environ.get("ANTHROPIC_MODEL", "claude-3-haiku-20240307")
        return detect_spans_via_llm_anthropic(body, api_key, model)

    elif provider == "gemini":
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not set")
        model = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
        return detect_spans_via_llm_gemini(body, api_key, model)

    else:
        raise ValueError(f"Unknown provider: {provider}. Use: openai, anthropic, gemini")


def load_existing_review(article_id: str) -> Optional[ArticleReview]:
    """Load an existing review if it exists."""
    path = REVIEWS_DIR / f"article_{article_id}_review.json"
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    return ArticleReview(
        article_id=data["article_id"],
        reviewed_at=data["reviewed_at"],
        reviewer=data["reviewer"],
        total_spans=data["total_spans"],
        grades=[SpanGrade(**g) for g in data["grades"]],
        false_negatives_noted=data.get("false_negatives_noted", []),
        overall_notes=data.get("overall_notes", ""),
    )


def save_review(review: ArticleReview):
    """Save a review to disk."""
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    path = REVIEWS_DIR / f"article_{review.article_id}_review.json"

    data = {
        "article_id": review.article_id,
        "reviewed_at": review.reviewed_at,
        "reviewer": review.reviewer,
        "total_spans": review.total_spans,
        "grades": [asdict(g) for g in review.grades],
        "false_negatives_noted": review.false_negatives_noted,
        "overall_notes": review.overall_notes,
    }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\n{Colors.GREEN}Review saved to: {path}{Colors.RESET}")


def highlight_text_with_spans(body: str, spans: List[TransparencySpan]) -> str:
    """
    Return the body text with spans highlighted using ANSI colors.
    Also shows span indices for grading.
    """
    if not spans:
        return body

    # Sort spans by position
    sorted_spans = sorted(spans, key=lambda s: s.start_char)

    result = []
    last_end = 0

    for i, span in enumerate(sorted_spans):
        # Add text before this span
        result.append(body[last_end:span.start_char])

        # Add highlighted span with index
        highlighted = (
            f"{Colors.BG_YELLOW}{Colors.BOLD}[{i}]{Colors.RESET}"
            f"{Colors.BG_YELLOW}{body[span.start_char:span.end_char]}{Colors.RESET}"
        )
        result.append(highlighted)

        last_end = span.end_char

    # Add remaining text
    result.append(body[last_end:])

    return "".join(result)


def display_article_with_highlights(article: dict, spans: List[TransparencySpan]):
    """Display the article with highlighted spans."""
    body = article.get("original_body", "")

    print("\n" + "=" * 80)
    print(f"{Colors.CYAN}ARTICLE: {article.get('id', 'unknown')}{Colors.RESET}")
    print(f"{Colors.BLUE}Title: {article.get('original_title', 'N/A')}{Colors.RESET}")
    print("=" * 80)

    print("\n" + highlight_text_with_spans(body, spans))
    print("\n" + "=" * 80)


def display_span_details(spans: List[TransparencySpan]):
    """Display details of each detected span."""
    if not spans:
        print(f"\n{Colors.GREEN}No spans detected.{Colors.RESET}")
        return

    print(f"\n{Colors.CYAN}DETECTED SPANS ({len(spans)} total):{Colors.RESET}")
    print("-" * 60)

    for i, span in enumerate(spans):
        reason_color = {
            SpanReason.CLICKBAIT: Colors.MAGENTA,
            SpanReason.URGENCY_INFLATION: Colors.RED,
            SpanReason.EMOTIONAL_TRIGGER: Colors.YELLOW,
            SpanReason.SELLING: Colors.CYAN,
            SpanReason.AGENDA_SIGNALING: Colors.BLUE,
            SpanReason.RHETORICAL_FRAMING: Colors.GREEN,
        }.get(span.reason, Colors.RESET)

        print(
            f"  [{i}] {Colors.BOLD}\"{span.original_text}\"{Colors.RESET} "
            f"({span.start_char}-{span.end_char})"
        )
        print(f"      Reason: {reason_color}{span.reason.value}{Colors.RESET}")
        print(f"      Action: {span.action.value}")
        if span.replacement_text:
            print(f"      Replacement: \"{span.replacement_text}\"")
        print()


def get_grade_for_span(span_index: int, span: TransparencySpan) -> SpanGrade:
    """Interactively get a grade for a span."""
    print(f"\n{Colors.BOLD}Span [{span_index}]:{Colors.RESET} \"{span.original_text}\"")
    print(f"  Reason: {span.reason.value}, Action: {span.action.value}")

    while True:
        grade = input(
            f"  Grade [{Colors.GREEN}C{Colors.RESET}]orrect / "
            f"[{Colors.RED}I{Colors.RESET}]ncorrect / "
            f"[{Colors.YELLOW}P{Colors.RESET}]artial / "
            f"[{Colors.BLUE}S{Colors.RESET}]kip: "
        ).strip().upper()

        if grade in ("C", "I", "P", "S"):
            break
        print("  Please enter C, I, P, or S")

    note = ""
    if grade == "I":
        note = input("  Note (why incorrect?): ").strip()
    elif grade == "P":
        note = input("  Note (what's partial?): ").strip()

    return SpanGrade(
        span_index=span_index,
        original_text=span.original_text,
        start_char=span.start_char,
        end_char=span.end_char,
        reason=span.reason.value,
        grade=grade,
        reviewer_note=note,
    )


def review_article(article_id: str, reviewer_name: str = "anonymous", provider_name: Optional[str] = None):
    """Run interactive review for an article.

    Args:
        article_id: Article ID to review
        reviewer_name: Name of the reviewer
        provider_name: LLM provider to use (openai, anthropic, gemini), or None for mock
    """
    # Load article
    try:
        article = load_article(article_id)
    except FileNotFoundError as e:
        print(f"{Colors.RED}Error: {e}{Colors.RESET}")
        return

    # Get predicted spans
    body = article.get("original_body", "")
    if not body:
        print(f"{Colors.RED}Article has no body text.{Colors.RESET}")
        return

    if provider_name:
        # Use LLM provider
        print(f"{Colors.CYAN}Using LLM provider: {provider_name}{Colors.RESET}")
        try:
            spans = get_llm_spans(body, provider_name)
        except ValueError as e:
            print(f"{Colors.RED}Error: {e}{Colors.RESET}")
            return
    else:
        # Use pattern-based mock provider
        provider = MockNeutralizerProvider()
        spans = provider._find_spans(body, "body")

    # Display article with highlights
    display_article_with_highlights(article, spans)
    display_span_details(spans)

    # Check for existing review
    existing = load_existing_review(article_id)
    if existing:
        print(f"\n{Colors.YELLOW}Existing review found from {existing.reviewed_at}{Colors.RESET}")
        cont = input("Continue with new review? [y/N]: ").strip().lower()
        if cont != "y":
            return

    # Grade each span
    print(f"\n{Colors.CYAN}GRADING SPANS{Colors.RESET}")
    print("Grade each span's detection accuracy:")
    print("  C = Correct (true positive, right word, right reason)")
    print("  I = Incorrect (false positive, shouldn't be flagged)")
    print("  P = Partial (right word, wrong reason or boundary)")
    print("  S = Skip (unsure or needs more context)")
    print()

    grades = []
    for i, span in enumerate(spans):
        grade = get_grade_for_span(i, span)
        grades.append(grade)

    # Ask about false negatives
    print(f"\n{Colors.CYAN}FALSE NEGATIVES{Colors.RESET}")
    print("Were any manipulative phrases MISSED? (not highlighted)")
    print("Enter phrases separated by semicolons, or press Enter to skip:")
    fn_input = input("> ").strip()
    false_negatives = [p.strip() for p in fn_input.split(";") if p.strip()]

    # Overall notes
    print(f"\n{Colors.CYAN}OVERALL NOTES{Colors.RESET}")
    overall_notes = input("Any overall observations? (press Enter to skip): ").strip()

    # Create and save review
    review = ArticleReview(
        article_id=article_id,
        reviewed_at=datetime.now().isoformat(),
        reviewer=reviewer_name,
        total_spans=len(spans),
        grades=grades,
        false_negatives_noted=false_negatives,
        overall_notes=overall_notes,
    )

    save_review(review)

    # Print summary
    correct = sum(1 for g in grades if g.grade == "C")
    incorrect = sum(1 for g in grades if g.grade == "I")
    partial = sum(1 for g in grades if g.grade == "P")
    skipped = sum(1 for g in grades if g.grade == "S")

    print(f"\n{Colors.CYAN}REVIEW SUMMARY{Colors.RESET}")
    print(f"  {Colors.GREEN}Correct: {correct}{Colors.RESET}")
    print(f"  {Colors.RED}Incorrect: {incorrect}{Colors.RESET}")
    print(f"  {Colors.YELLOW}Partial: {partial}{Colors.RESET}")
    print(f"  {Colors.BLUE}Skipped: {skipped}{Colors.RESET}")
    print(f"  False negatives noted: {len(false_negatives)}")


def generate_report():
    """Generate aggregate accuracy report from all reviews."""
    print(f"\n{Colors.CYAN}ACCURACY REPORT{Colors.RESET}")
    print("=" * 60)

    # Load all reviews
    reviews = []
    if REVIEWS_DIR.exists():
        for path in REVIEWS_DIR.glob("article_*_review.json"):
            with open(path) as f:
                reviews.append(json.load(f))

    if not reviews:
        print("No reviews found. Run --article to review articles first.")
        return

    # Aggregate stats
    total_correct = 0
    total_incorrect = 0
    total_partial = 0
    total_skipped = 0
    total_fn = 0

    for review in reviews:
        for grade in review["grades"]:
            if grade["grade"] == "C":
                total_correct += 1
            elif grade["grade"] == "I":
                total_incorrect += 1
            elif grade["grade"] == "P":
                total_partial += 1
            elif grade["grade"] == "S":
                total_skipped += 1
        total_fn += len(review.get("false_negatives_noted", []))

    total_graded = total_correct + total_incorrect + total_partial

    # Calculate metrics
    if total_graded > 0:
        precision = total_correct / (total_correct + total_incorrect) if (total_correct + total_incorrect) > 0 else 0
        # For recall, we'd need to count all expected positives
        # Using TP / (TP + FN) approximation
        recall = total_correct / (total_correct + total_fn) if (total_correct + total_fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    else:
        precision = recall = f1 = 0.0

    print(f"\nArticles reviewed: {len(reviews)}")
    print(f"\n{Colors.BOLD}GRADES:{Colors.RESET}")
    print(f"  {Colors.GREEN}Correct (true positives): {total_correct}{Colors.RESET}")
    print(f"  {Colors.RED}Incorrect (false positives): {total_incorrect}{Colors.RESET}")
    print(f"  {Colors.YELLOW}Partial matches: {total_partial}{Colors.RESET}")
    print(f"  {Colors.BLUE}Skipped: {total_skipped}{Colors.RESET}")
    print(f"  False negatives noted: {total_fn}")

    print(f"\n{Colors.BOLD}METRICS:{Colors.RESET}")
    print(f"  Precision: {precision:.2%}")
    print(f"  Recall (est.): {recall:.2%}")
    print(f"  F1 Score: {f1:.2%}")

    # Per-article breakdown
    print(f"\n{Colors.BOLD}PER-ARTICLE:{Colors.RESET}")
    for review in reviews:
        article_id = review["article_id"]
        c = sum(1 for g in review["grades"] if g["grade"] == "C")
        i = sum(1 for g in review["grades"] if g["grade"] == "I")
        p = sum(1 for g in review["grades"] if g["grade"] == "P")
        fn = len(review.get("false_negatives_noted", []))
        print(f"  Article {article_id}: C={c}, I={i}, P={p}, FN={fn}")


def list_articles():
    """List all articles and their review status."""
    print(f"\n{Colors.CYAN}ARTICLES{Colors.RESET}")
    print("-" * 60)

    articles = sorted(TEST_CORPUS_DIR.glob("article_*.json"))

    for path in articles:
        article_id = path.stem.replace("article_", "")

        with open(path) as f:
            article = json.load(f)

        has_manipulation = article.get("has_manipulative_language", False)
        review_path = REVIEWS_DIR / f"article_{article_id}_review.json"
        reviewed = review_path.exists()

        status_icon = f"{Colors.GREEN}[R]{Colors.RESET}" if reviewed else "[ ]"
        manip_icon = f"{Colors.YELLOW}[M]{Colors.RESET}" if has_manipulation else "[C]"

        title = article.get("original_title", "N/A")[:50]

        print(f"  {status_icon} {manip_icon} {article_id}: {title}...")

    print()
    print("Legend: [R]=Reviewed, [ ]=Not reviewed, [M]=Has manipulation, [C]=Clean")


def update_gold_from_llm(article_id: str, provider_name: str):
    """
    Update gold standard from LLM predictions with human review.

    This workflow:
    1. Runs LLM detection on the article
    2. Loads existing gold standard
    3. Shows diff between current gold and LLM predictions
    4. Allows human to approve/reject each change
    5. Saves updated gold standard

    Args:
        article_id: Article ID to update
        provider_name: LLM provider to use
    """
    # Load article
    try:
        article = load_article(article_id)
    except FileNotFoundError as e:
        print(f"{Colors.RED}Error: {e}{Colors.RESET}")
        return

    body = article.get("original_body", "")
    if not body:
        print(f"{Colors.RED}Article has no body text.{Colors.RESET}")
        return

    # Get LLM predictions
    print(f"\n{Colors.CYAN}Running LLM detection with {provider_name}...{Colors.RESET}")
    try:
        llm_spans = get_llm_spans(body, provider_name)
    except ValueError as e:
        print(f"{Colors.RED}Error: {e}{Colors.RESET}")
        return

    print(f"LLM detected {len(llm_spans)} spans")

    # Load existing gold standard
    gold_data = load_gold_standard(article_id)
    existing_spans = gold_data.get("expected_spans", [])

    print(f"Existing gold standard has {len(existing_spans)} spans")

    # Display article with LLM highlights
    display_article_with_highlights(article, llm_spans)

    # Show comparison
    print(f"\n{Colors.CYAN}COMPARISON: LLM vs Gold Standard{Colors.RESET}")
    print("-" * 60)

    # Convert existing spans to a lookup by text
    existing_by_text = {s.get("text", "").lower(): s for s in existing_spans}

    new_spans = []
    for i, llm_span in enumerate(llm_spans):
        text_lower = llm_span.original_text.lower()
        if text_lower in existing_by_text:
            print(f"  [{i}] {Colors.GREEN}[MATCH]{Colors.RESET} \"{llm_span.original_text}\" - already in gold standard")
        else:
            print(f"  [{i}] {Colors.YELLOW}[NEW]{Colors.RESET} \"{llm_span.original_text}\" ({llm_span.reason.value})")
            new_spans.append(llm_span)

    # Check for spans in gold standard but not detected by LLM
    llm_texts = {s.original_text.lower() for s in llm_spans}
    missed = []
    for existing in existing_spans:
        if existing.get("text", "").lower() not in llm_texts:
            missed.append(existing)
            print(f"  {Colors.RED}[MISSED]{Colors.RESET} \"{existing.get('text', '')}\" - in gold but not detected by LLM")

    if not new_spans and not missed:
        print(f"\n{Colors.GREEN}LLM and gold standard match perfectly!{Colors.RESET}")
        return

    # Ask user to review new spans
    print(f"\n{Colors.CYAN}REVIEW NEW SPANS{Colors.RESET}")
    print("For each new span detected by LLM, decide whether to add to gold standard:")
    print("  [Y]es - Add to gold standard")
    print("  [N]o  - Reject (false positive)")
    print("  [S]kip - Skip this span")
    print()

    approved_new = []
    for span in new_spans:
        while True:
            response = input(
                f"  Add \"{span.original_text}\" ({span.reason.value})? [Y/N/S]: "
            ).strip().upper()
            if response in ("Y", "N", "S"):
                break
            print("  Please enter Y, N, or S")

        if response == "Y":
            approved_new.append({
                "span_id": f"{article_id}-{len(existing_spans) + len(approved_new) + 1:03d}",
                "start_char": span.start_char,
                "end_char": span.end_char,
                "text": span.original_text,
                "reason": span.reason.value,
                "action": span.action.value if hasattr(span.action, 'value') else str(span.action),
                "confidence": "medium",
            })

    # Ask about missed spans
    if missed:
        print(f"\n{Colors.CYAN}REVIEW MISSED SPANS{Colors.RESET}")
        print("The following spans are in gold standard but not detected by LLM.")
        print("  [K]eep - Keep in gold standard")
        print("  [R]emove - Remove from gold standard (was incorrect)")
        print()

        keep_missed = []
        for span in missed:
            while True:
                response = input(
                    f"  Keep \"{span.get('text', '')}\" ({span.get('reason', '')})? [K/R]: "
                ).strip().upper()
                if response in ("K", "R"):
                    break
                print("  Please enter K or R")

            if response == "K":
                keep_missed.append(span)

        # Update existing spans to only include those not missed or explicitly kept
        remaining = [s for s in existing_spans if s not in missed] + keep_missed
    else:
        remaining = existing_spans

    # Build updated gold standard
    updated_spans = remaining + approved_new

    # Sort by start_char
    updated_spans.sort(key=lambda s: s.get("start_char", 0))

    # Renumber span IDs
    for i, span in enumerate(updated_spans):
        span["span_id"] = f"{article_id}-{i + 1:03d}"

    # Preview changes
    print(f"\n{Colors.CYAN}UPDATED GOLD STANDARD PREVIEW{Colors.RESET}")
    print("-" * 60)
    print(f"  Previous spans: {len(existing_spans)}")
    print(f"  Updated spans:  {len(updated_spans)}")
    print(f"  New spans added: {len(approved_new)}")
    print(f"  Spans removed: {len(existing_spans) - len(remaining) + len(missed) - len([s for s in missed if s in remaining])}")

    # Confirm save
    confirm = input(f"\n  Save updated gold standard? [Y/N]: ").strip().upper()
    if confirm == "Y":
        gold_data["expected_spans"] = updated_spans
        gold_data["notes"] = gold_data.get("notes", "") + f" Updated from {provider_name} LLM on {datetime.now().isoformat()[:10]}."
        save_gold_standard(article_id, gold_data)
    else:
        print(f"{Colors.YELLOW}Changes discarded.{Colors.RESET}")


def main():
    parser = argparse.ArgumentParser(
        description="Human Review CLI for NtrlView Highlight Accuracy"
    )
    parser.add_argument(
        "--article", "-a",
        help="Article ID to review (e.g., 001)"
    )
    parser.add_argument(
        "--reviewer", "-r",
        default=os.environ.get("USER", "anonymous"),
        help="Reviewer name"
    )
    parser.add_argument(
        "--provider", "-p",
        choices=["openai", "anthropic", "gemini"],
        help="LLM provider for span detection (requires API key env var)"
    )
    parser.add_argument(
        "--update-gold", "-u",
        metavar="ARTICLE_ID",
        help="Update gold standard from LLM predictions (e.g., --update-gold 003)"
    )
    parser.add_argument(
        "--generate-report", "-g",
        action="store_true",
        help="Generate aggregate accuracy report"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all articles and their review status"
    )

    args = parser.parse_args()

    if args.generate_report:
        generate_report()
    elif args.list:
        list_articles()
    elif args.update_gold:
        if not args.provider:
            print(f"{Colors.RED}Error: --update-gold requires --provider{Colors.RESET}")
            print("Example: python scripts/review_accuracy.py --update-gold 003 --provider openai")
            sys.exit(1)
        update_gold_from_llm(args.update_gold, args.provider)
    elif args.article:
        review_article(args.article, args.reviewer, args.provider)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
