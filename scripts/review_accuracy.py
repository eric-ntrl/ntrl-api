#!/usr/bin/env python3
"""
Human Review CLI for NtrlView Highlight Accuracy

This script allows human reviewers to:
1. View articles with predicted highlights (colored terminal output)
2. Grade each span: [C]orrect / [I]ncorrect / [P]artial / [S]kip
3. Record reasons for incorrect grades
4. Save results to tests/fixtures/reviews/

Usage:
    # Review specific article
    python scripts/review_accuracy.py --article 001

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

from app.services.neutralizer import MockNeutralizerProvider, TransparencySpan
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


def review_article(article_id: str, reviewer_name: str = "anonymous"):
    """Run interactive review for an article."""
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
    elif args.article:
        review_article(args.article, args.reviewer)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
