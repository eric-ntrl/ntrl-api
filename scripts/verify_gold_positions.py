#!/usr/bin/env python3
"""
Gold Standard Position Verification Script

Verifies that gold standard span positions are correct by:
1. Loading each article body from test corpus
2. For each gold standard span, extracting body[start_char:end_char]
3. Comparing extracted text to span.text
4. Reporting mismatches and optionally fixing positions

Usage:
    # Verify a specific article
    python scripts/verify_gold_positions.py --article 003

    # Verify all articles
    python scripts/verify_gold_positions.py --all

    # Auto-fix positions
    python scripts/verify_gold_positions.py --article 003 --fix
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# ANSI color codes
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


# Paths
FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
TEST_CORPUS_DIR = FIXTURES_DIR / "test_corpus"
GOLD_STANDARD_DIR = FIXTURES_DIR / "gold_standard"


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
    print(f"{Colors.GREEN}Saved: {path}{Colors.RESET}")


def find_text_position(body: str, text: str, start_hint: int = 0) -> Optional[int]:
    """
    Find the position of text in body, preferring position near start_hint.

    Args:
        body: Article body text
        text: Text to find
        start_hint: Approximate expected position

    Returns:
        Position of text, or None if not found
    """
    # Try exact match first
    pos = body.find(text)
    if pos == -1:
        # Try case-insensitive
        pos = body.lower().find(text.lower())

    if pos == -1:
        return None

    # If found, check if there's a closer match to the hint
    all_positions = []
    search_start = 0
    search_body = body.lower()
    search_text = text.lower()

    while True:
        pos = search_body.find(search_text, search_start)
        if pos == -1:
            break
        all_positions.append(pos)
        search_start = pos + 1

    if not all_positions:
        return None

    # Return position closest to the hint
    return min(all_positions, key=lambda p: abs(p - start_hint))


def verify_article(article_id: str, fix: bool = False, verbose: bool = True) -> dict:
    """
    Verify gold standard positions for an article.

    Args:
        article_id: Article ID (e.g., "003")
        fix: If True, auto-fix incorrect positions
        verbose: If True, print detailed output

    Returns:
        Dict with verification results
    """
    results = {
        "article_id": article_id,
        "total_spans": 0,
        "correct": 0,
        "incorrect": 0,
        "not_found": 0,
        "fixed": 0,
        "issues": [],
    }

    try:
        article = load_article(article_id)
    except FileNotFoundError as e:
        if verbose:
            print(f"{Colors.RED}Error: {e}{Colors.RESET}")
        results["issues"].append(str(e))
        return results

    gold_data = load_gold_standard(article_id)
    body = article.get("original_body", "")

    if not body:
        if verbose:
            print(f"{Colors.YELLOW}Article {article_id} has no body{Colors.RESET}")
        return results

    spans = gold_data.get("expected_spans", [])
    results["total_spans"] = len(spans)

    if verbose:
        print(f"\n{Colors.CYAN}Article {article_id}: Verifying {len(spans)} spans{Colors.RESET}")
        print("-" * 60)

    modified = False

    for span in spans:
        span_id = span.get("span_id", "?")
        expected_text = span.get("text", "")
        start_char = span.get("start_char", 0)
        end_char = span.get("end_char", 0)

        # Extract actual text at position
        actual_text = body[start_char:end_char]

        if actual_text == expected_text:
            results["correct"] += 1
            if verbose:
                print(f"  {Colors.GREEN}[OK]{Colors.RESET} {span_id}: \"{expected_text}\" at {start_char}-{end_char}")
        else:
            # Text doesn't match - try to find correct position
            correct_pos = find_text_position(body, expected_text, start_char)

            if correct_pos is not None:
                correct_end = correct_pos + len(expected_text)
                results["incorrect"] += 1

                if verbose:
                    print(
                        f"  {Colors.RED}[MISMATCH]{Colors.RESET} {span_id}: "
                        f"Expected \"{expected_text}\" at {start_char}-{end_char}, "
                        f"found \"{actual_text}\""
                    )
                    print(
                        f"    {Colors.YELLOW}-> Correct position: {correct_pos}-{correct_end}{Colors.RESET}"
                    )

                if fix:
                    span["start_char"] = correct_pos
                    span["end_char"] = correct_end
                    results["fixed"] += 1
                    modified = True
                    if verbose:
                        print(f"    {Colors.GREEN}[FIXED]{Colors.RESET}")

                results["issues"].append({
                    "span_id": span_id,
                    "text": expected_text,
                    "expected_pos": f"{start_char}-{end_char}",
                    "correct_pos": f"{correct_pos}-{correct_end}",
                })
            else:
                results["not_found"] += 1
                if verbose:
                    print(
                        f"  {Colors.RED}[NOT FOUND]{Colors.RESET} {span_id}: "
                        f"\"{expected_text}\" not found in body"
                    )
                results["issues"].append({
                    "span_id": span_id,
                    "text": expected_text,
                    "error": "Text not found in article body",
                })

    if modified and fix:
        # Update notes to indicate verification
        if "notes" in gold_data:
            gold_data["notes"] += " Positions verified and corrected."
        else:
            gold_data["notes"] = "Positions verified and corrected."
        save_gold_standard(article_id, gold_data)

    if verbose:
        print("-" * 60)
        print(
            f"  Summary: {Colors.GREEN}{results['correct']} correct{Colors.RESET}, "
            f"{Colors.RED}{results['incorrect']} incorrect{Colors.RESET}, "
            f"{Colors.YELLOW}{results['not_found']} not found{Colors.RESET}"
        )
        if fix and results["fixed"] > 0:
            print(f"  {Colors.GREEN}Fixed {results['fixed']} positions{Colors.RESET}")

    return results


def verify_all_articles(fix: bool = False) -> dict:
    """Verify all articles in the test corpus."""
    all_results = {
        "articles": [],
        "total_spans": 0,
        "total_correct": 0,
        "total_incorrect": 0,
        "total_not_found": 0,
        "total_fixed": 0,
    }

    # Find all article IDs
    article_ids = []
    for path in sorted(TEST_CORPUS_DIR.glob("article_*.json")):
        article_id = path.stem.replace("article_", "")
        article_ids.append(article_id)

    print(f"\n{Colors.CYAN}{'='*60}{Colors.RESET}")
    print(f"{Colors.CYAN}GOLD STANDARD POSITION VERIFICATION{Colors.RESET}")
    print(f"{Colors.CYAN}{'='*60}{Colors.RESET}")

    for article_id in article_ids:
        results = verify_article(article_id, fix=fix, verbose=True)
        all_results["articles"].append(results)
        all_results["total_spans"] += results["total_spans"]
        all_results["total_correct"] += results["correct"]
        all_results["total_incorrect"] += results["incorrect"]
        all_results["total_not_found"] += results["not_found"]
        all_results["total_fixed"] += results["fixed"]

    # Summary
    print(f"\n{Colors.CYAN}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}OVERALL SUMMARY{Colors.RESET}")
    print(f"{Colors.CYAN}{'='*60}{Colors.RESET}")
    print(f"  Total spans: {all_results['total_spans']}")
    print(f"  {Colors.GREEN}Correct: {all_results['total_correct']}{Colors.RESET}")
    print(f"  {Colors.RED}Incorrect: {all_results['total_incorrect']}{Colors.RESET}")
    print(f"  {Colors.YELLOW}Not found: {all_results['total_not_found']}{Colors.RESET}")
    if fix:
        print(f"  {Colors.GREEN}Fixed: {all_results['total_fixed']}{Colors.RESET}")

    accuracy = (
        all_results["total_correct"] / all_results["total_spans"] * 100
        if all_results["total_spans"] > 0
        else 100
    )
    print(f"\n  Position accuracy: {accuracy:.1f}%")

    return all_results


def main():
    parser = argparse.ArgumentParser(
        description="Verify gold standard span positions against article body text"
    )
    parser.add_argument(
        "--article", "-a",
        help="Article ID to verify (e.g., 003)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Verify all articles"
    )
    parser.add_argument(
        "--fix", "-f",
        action="store_true",
        help="Auto-fix incorrect positions"
    )

    args = parser.parse_args()

    if args.all:
        verify_all_articles(fix=args.fix)
    elif args.article:
        verify_article(args.article, fix=args.fix)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
