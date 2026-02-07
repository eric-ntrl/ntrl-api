"""
NTRL Neutralization Grader (v1.0) — Reference Python implementation

This module validates neutralized outputs against the NTRL Neutralization Canon v1.0
via a deterministic rule spec (ntrl_neutralization_grader_v1.json).

Design:
- Binary pass/fail per rule
- Deterministic checks only (no LLM calls)
- Heuristic checks are explicitly labeled (useful for catching regressions, not for absolute truth)

Recommended usage:
- Run in CI for prompt changes and post-processor changes
- Run in FastAPI pipeline before persisting/shipping neutral outputs

Inputs:
- original_text (required): the source article text (or headline text for headline-only grading)
- neutral_text (required): the model-produced neutral text (headline or brief)
- original_headline / neutral_headline (optional): when checking headline-specific constraints

Outputs:
- overall_pass: bool
- results: list[RuleResult]
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.-]*")


@dataclass
class RuleResult:
    rule_id: str
    passed: bool
    severity: str
    message: str = ""
    evidence: dict[str, Any] | None = None


def _words(s: str) -> list[str]:
    return WORD_RE.findall(s or "")


def _word_count(s: str) -> int:
    return len(_words(s))


def _lower(s: str) -> str:
    return (s or "").lower()


def _scan_tokens(text: str, tokens: list[str]) -> list[str]:
    """
    Scan for banned tokens using word boundaries to avoid false positives.
    E.g., "live" should not match "delivery".
    """
    t = _lower(text)
    hits = []
    for tok in tokens:
        # Use word boundary regex to avoid substring matches
        pattern = r"\b" + re.escape(tok.lower()) + r"\b"
        if re.search(pattern, t):
            hits.append(tok)
    return hits


def _agenda_scan_with_quote_exception(neutral: str, tokens: list[str]) -> list[str]:
    """
    Allow tokens only if they appear inside quotation marks in the neutral output.
    This is a minimal deterministic approximation. For stricter enforcement,
    require an attribution phrase near the quote in upstream generation.
    """
    # Find quoted spans
    quoted_spans = []
    for m in re.finditer(r"\"([^\"]+)\"", neutral):
        quoted_spans.append(m.group(1).lower())
    for m in re.finditer(r"‘([^’]+)’", neutral):
        quoted_spans.append(m.group(1).lower())
    for m in re.finditer(r"'([^']+)'", neutral):
        quoted_spans.append(m.group(1).lower())

    hits = []
    nlow = neutral.lower()
    for tok in tokens:
        if tok.lower() in nlow:
            # If any quoted span contains the token, allow; else flag
            if not any(tok.lower() in span for span in quoted_spans):
                hits.append(tok)
    return hits


def _regex_forbidden(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text or "")
    return m.group(0) if m else None


def _grammar_lint_min(text: str) -> list[str]:
    """
    Minimal deterministic lints:
    - empty quotes
    - repeated punctuation artifacts
    - leading punctuation fragments
    """
    t = (text or "").strip()
    problems = []
    if re.search(r"\"\\s*\"", t) or re.search(r"''", t) or re.search(r"‘\\s*’", t):
        problems.append("empty_quotes")
    if re.search(r"[,:;\\-]{2,}", t):
        problems.append("repeated_punct")
    if re.match(r"^[,:;\\-]+", t):
        problems.append("leading_punct")
    if re.search(r"\\s[,:;\\-]+\\s*$", t):
        problems.append("trailing_punct")
    return problems


def _all_caps_scan(text: str, allowlist: list[str]) -> list[str]:
    """
    Flags ALL CAPS tokens longer than 2 chars not in allowlist.
    """
    allow = set(allowlist)
    hits = []
    for tok in _words(text):
        if tok in allow:
            continue
        # consider tokens like "ALL", "LIVE", "BREAKING"
        if len(tok) >= 3 and tok.isupper():
            hits.append(tok)
    return hits


def _scope_marker_preservation(original: str, neutral: str, markers: list[str]) -> list[str]:
    """
    If a scope marker appears in original as a standalone word, it should appear in neutral.
    Uses word boundary matching to avoid false positives (e.g., "all" in "eventually").
    Returns missing markers.
    """
    o = original.lower()
    n = neutral.lower()
    missing = []
    for m in markers:
        ml = m.lower()
        # Use word boundary regex to find standalone occurrences
        pattern = r"\b" + re.escape(ml) + r"\b"
        if re.search(pattern, o) and not re.search(pattern, n):
            missing.append(m)
    return missing


def _compound_term_atomicity(original: str, neutral: str, terms: list[str]) -> list[str]:
    """
    If a compound term appears in original, require it in neutral.
    (This is intentionally strict; tune term list as canon evolves.)
    """
    o = original.lower()
    n = neutral.lower()
    missing = []
    for term in terms:
        tl = term.lower()
        if tl in o and tl not in n:
            missing.append(term)
    return missing


def _certainty_marker_preservation(original: str, neutral: str, markers: list[str]) -> list[str]:
    """
    If a certainty marker appears in original, it should appear in neutral.
    Uses word boundary matching to find phrase occurrences.
    Returns missing markers.
    """
    o = original.lower()
    n = neutral.lower()
    missing = []
    for m in markers:
        ml = m.lower()
        # Use word boundary regex to find phrase occurrences
        pattern = r"\b" + re.escape(ml) + r"\b"
        if re.search(pattern, o) and not re.search(pattern, n):
            missing.append(m)
    return missing


def _heuristic_no_new_entities_numbers(original: str, neutral: str) -> dict[str, Any]:
    """
    Heuristic: flags numbers or capitalized tokens that appear in neutral but not in original.
    Not perfect, but useful for catching obvious 'new facts' regressions.

    Returns dict with 'new_numbers' and 'new_capitalized_tokens'.
    """
    o = original or ""
    n = neutral or ""

    o_numbers = set(re.findall(r"\\b\\d[\\d,]*\\b", o))
    n_numbers = set(re.findall(r"\\b\\d[\\d,]*\\b", n))
    new_numbers = sorted(list(n_numbers - o_numbers))

    # capitalized tokens heuristic
    def caps_tokens(s: str) -> set[str]:
        toks = re.findall(r"\\b[A-Z][a-z]+(?:\\s[A-Z][a-z]+)*\\b", s)
        return set(toks)

    new_caps = sorted(list(caps_tokens(n) - caps_tokens(o)))

    return {"new_numbers": new_numbers, "new_capitalized_tokens": new_caps}


def load_spec(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def grade(
    spec: dict[str, Any],
    original_text: str,
    neutral_text: str,
    original_headline: str | None = None,
    neutral_headline: str | None = None,
) -> dict[str, Any]:
    results: list[RuleResult] = []
    overall_pass = True

    for rule in spec["rules"]:
        rid = rule["id"]
        severity = rule["severity"]
        check = rule["check"]
        ctype = check["type"]

        passed = True
        msg = ""
        evidence = None

        if ctype == "banned_token_scan":
            hits = _scan_tokens(neutral_text, check["banned"])
            if hits:
                passed = False
                msg = f"Found banned tokens: {hits}"
                evidence = {"hits": hits}

        elif ctype == "agenda_token_scan_with_quote_exception":
            hits = _agenda_scan_with_quote_exception(neutral_text, check["tokens"])
            if hits:
                passed = False
                msg = f"Agenda tokens not quoted: {hits}"
                evidence = {"hits": hits}

        elif ctype == "regex_forbidden":
            hit = _regex_forbidden(neutral_text, check["pattern"])
            if hit:
                passed = False
                msg = f"Forbidden pattern matched: {hit}"
                evidence = {"match": hit}

        elif ctype == "grammar_lint_min":
            probs = _grammar_lint_min(neutral_text)
            if probs:
                passed = False
                msg = f"Grammar lint issues: {probs}"
                evidence = {"issues": probs}

        elif ctype == "all_caps_scan":
            hits = _all_caps_scan(neutral_text, check["allowlist"])
            if hits:
                passed = False
                msg = f"ALL-CAPS emphasis found: {hits}"
                evidence = {"hits": hits}

        elif ctype == "headline_word_limit":
            if neutral_headline is not None:
                wc = _word_count(neutral_headline)
                if wc > int(check["max_words"]):
                    passed = False
                    msg = f"Headline word count {wc} exceeds {check['max_words']}"
                    evidence = {"word_count": wc, "max_words": check["max_words"]}

        elif ctype == "scope_marker_preservation":
            missing = _scope_marker_preservation(original_text, neutral_text, check["markers"])
            if missing:
                passed = False
                msg = f"Missing scope markers present in source: {missing}"
                evidence = {"missing": missing}

        elif ctype == "compound_term_atomicity":
            missing = _compound_term_atomicity(original_text, neutral_text, check["terms"])
            if missing:
                passed = False
                msg = f"Missing compound terms present in source: {missing}"
                evidence = {"missing": missing}

        elif ctype == "certainty_marker_preservation":
            missing = _certainty_marker_preservation(original_text, neutral_text, check["markers"])
            if missing:
                passed = False
                msg = f"Missing certainty markers present in source: {missing}"
                evidence = {"missing": missing}

        elif ctype == "heuristic_no_new_entities_numbers":
            ev = _heuristic_no_new_entities_numbers(original_text, neutral_text)
            # Fail only if we detect something; tune if too strict
            if ev["new_numbers"] or ev["new_capitalized_tokens"]:
                passed = False
                msg = "Potential new facts detected (heuristic)"
                evidence = ev

        else:
            passed = False
            msg = f"Unknown check type: {ctype}"
            evidence = {"type": ctype}

        if not passed:
            overall_pass = False if severity in ("critical", "major") else overall_pass

        results.append(RuleResult(rule_id=rid, passed=passed, severity=severity, message=msg, evidence=evidence))

    return {"overall_pass": overall_pass, "results": [r.__dict__ for r in results]}


# Default spec path relative to this file
_DEFAULT_SPEC_PATH = Path(__file__).parent.parent / "data" / "grader_spec_v1.json"


@lru_cache(maxsize=1)
def get_default_spec() -> dict[str, Any]:
    """Load and cache the default grader spec."""
    return load_spec(_DEFAULT_SPEC_PATH)


def grade_article(
    original_text: str,
    neutral_text: str,
    original_headline: str | None = None,
    neutral_headline: str | None = None,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Convenience function to grade an article using the default spec.

    Args:
        original_text: The source article text
        neutral_text: The neutralized article text
        original_headline: Optional original headline
        neutral_headline: Optional neutralized headline
        spec: Optional custom spec (uses default if not provided)

    Returns:
        Dict with overall_pass (bool) and results (list of rule results)
    """
    if spec is None:
        spec = get_default_spec()
    return grade(spec, original_text, neutral_text, original_headline, neutral_headline)


if __name__ == "__main__":
    spec = get_default_spec()
    sample = grade_article(
        original_text="Meghan Markle set to return to Britain with Harry this summer.",
        neutral_text="Meghan Markle and Harry return to Britain this summer.",
        original_headline="Meghan Markle set to return to Britain with Harry this summer.",
        neutral_headline="Meghan Markle and Harry return to Britain this summer.",
    )
    print(json.dumps(sample, indent=2))
