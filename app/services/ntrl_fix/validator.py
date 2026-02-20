# app/services/ntrl_fix/validator.py
"""
Red-Line Validator: Ensures rewriting doesn't violate semantic invariants.

This is a critical safety component that checks rewritten content against
the original to ensure no factual changes were introduced. It implements
10 invariance checks:

1. Entity Invariance - Names, organizations, places unchanged
2. Number Invariance - All numbers preserved exactly
3. Date Invariance - All dates preserved exactly
4. Attribution Invariance - Who said what preserved
5. Modality Invariance - Certainty levels not upgraded
6. Causality Invariance - Causal claims unchanged
7. Risk Invariance - Risk levels preserved
8. Quote Integrity - Direct quotes preserved verbatim
9. Scope Invariance - Quantifiers not changed
10. Negation Integrity - Negations preserved

Any failure in these checks indicates the rewrite may have changed meaning.
"""

import re
from functools import lru_cache

import spacy
from spacy.tokens import Doc

from .types import (
    CheckResult,
    ValidationResult,
    ValidationStatus,
)

ALLOWED_SPACY_MODELS = {"en_core_web_sm", "en_core_web_md", "en_core_web_lg"}


@lru_cache(maxsize=1)
def _get_spacy_model(model_name: str = "en_core_web_sm"):
    """Lazy-load and cache the spaCy model as a singleton."""
    if model_name not in ALLOWED_SPACY_MODELS:
        raise ValueError(f"Model '{model_name}' not in allowlist: {ALLOWED_SPACY_MODELS}")
    try:
        nlp = spacy.load(model_name)
    except OSError:
        import subprocess

        subprocess.run(["python", "-m", "spacy", "download", model_name], check=True)
        nlp = spacy.load(model_name)
    return nlp


class RedLineValidator:
    """
    Validates that rewritten content preserves factual accuracy.

    Uses a combination of NLP analysis and pattern matching to ensure
    no semantic changes were introduced during the rewriting process.
    """

    # Soft modality words that should not become hard
    SOFT_MODALS = {
        "alleged",
        "allegedly",
        "may",
        "might",
        "could",
        "likely",
        "suspected",
        "possible",
        "possibly",
        "perhaps",
        "reportedly",
        "apparently",
        "supposedly",
        "seemingly",
        "potentially",
        "uncertain",
        "unconfirmed",
        "claimed",
        "purported",
    }

    # Hard modality words that soft modals shouldn't become
    HARD_MODALS = {
        "confirmed",
        "proven",
        "did",
        "will",
        "definitely",
        "certainly",
        "absolutely",
        "undoubtedly",
        "clearly",
        "obviously",
        "known",
        "established",
        "verified",
        "true",
    }

    # Scope words that affect meaning
    SCOPE_WORDS = {
        "all",
        "every",
        "none",
        "no",
        "some",
        "most",
        "many",
        "few",
        "several",
        "any",
        "each",
        "both",
        "only",
        "just",
    }

    # Negation words
    NEGATION_WORDS = {
        "not",
        "no",
        "never",
        "neither",
        "nor",
        "none",
        "nothing",
        "nobody",
        "nowhere",
        "without",
        "deny",
        "denied",
        "refuse",
        "refused",
        "reject",
        "rejected",
    }

    # Causal indicators
    CAUSAL_WORDS = {
        "because",
        "caused",
        "causes",
        "causing",
        "due to",
        "result",
        "resulted",
        "resulting",
        "led to",
        "leads to",
        "therefore",
        "thus",
        "hence",
        "consequently",
        "so",
    }

    def __init__(self, model_name: str = "en_core_web_sm"):
        """Initialize with lazy-loaded spaCy model."""
        self.nlp = _get_spacy_model(model_name)

    def validate(self, original: str, rewritten: str, strict: bool = True) -> ValidationResult:
        """
        Validate rewritten content against original.

        Args:
            original: Original article text
            rewritten: Rewritten/neutralized text
            strict: If True, any failure fails validation

        Returns:
            ValidationResult with all check results
        """
        # Parse both texts with spaCy
        original_doc = self.nlp(original)
        rewritten_doc = self.nlp(rewritten)

        # Run all checks
        checks = {
            "entity_invariance": self._check_entities(original_doc, rewritten_doc),
            "number_invariance": self._check_numbers(original, rewritten),
            "date_invariance": self._check_dates(original_doc, rewritten_doc),
            "attribution_invariance": self._check_attributions(original, rewritten),
            "modality_invariance": self._check_modality(original, rewritten),
            "causality_invariance": self._check_causality(original, rewritten),
            "risk_invariance": self._check_risk(original, rewritten),
            "quote_integrity": self._check_quotes(original, rewritten),
            "scope_invariance": self._check_scope(original, rewritten),
            "negation_integrity": self._check_negation(original, rewritten),
        }

        # Determine overall pass/fail
        failures = [name for name, check in checks.items() if check.status == ValidationStatus.FAILED]

        if strict:
            passed = len(failures) == 0
        else:
            # In non-strict mode, allow some failures
            critical_checks = {"entity_invariance", "number_invariance", "quote_integrity", "negation_integrity"}
            critical_failures = [f for f in failures if f in critical_checks]
            passed = len(critical_failures) == 0

        return ValidationResult(
            passed=passed,
            checks=checks,
            failures=failures,
        )

    def _check_entities(self, original_doc: Doc, rewritten_doc: Doc) -> CheckResult:
        """
        Check that named entities are preserved.

        Verifies names, organizations, and locations are unchanged.
        """
        # Extract entities from both documents
        original_ents = set()
        for ent in original_doc.ents:
            if ent.label_ in {"PERSON", "ORG", "GPE", "LOC", "FAC", "NORP"}:
                original_ents.add(ent.text.lower().strip())

        rewritten_ents = set()
        for ent in rewritten_doc.ents:
            if ent.label_ in {"PERSON", "ORG", "GPE", "LOC", "FAC", "NORP"}:
                rewritten_ents.add(ent.text.lower().strip())

        # Find missing entities
        missing = original_ents - rewritten_ents

        # Filter out common words that might be misidentified as entities
        missing = {e for e in missing if len(e) > 2}

        if missing:
            return CheckResult(
                check_name="entity_invariance",
                status=ValidationStatus.FAILED,
                message=f"Missing entities: {', '.join(list(missing)[:5])}",
                details={"missing": list(missing)},
            )

        return CheckResult(
            check_name="entity_invariance", status=ValidationStatus.PASSED, message="All named entities preserved"
        )

    def _check_numbers(self, original: str, rewritten: str) -> CheckResult:
        """
        Check that all numbers are preserved exactly.

        Numbers include: integers, decimals, percentages, currency, ordinals.
        """
        # Pattern to match numbers in various formats
        number_pattern = r"""
            (?:
                \$?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?  |  # Currency/percentage
                \d+(?:\.\d+)?%?                    |  # Simple numbers
                \d+(?:st|nd|rd|th)                 |  # Ordinals
                \b(?:one|two|three|four|five|six|seven|eight|nine|ten|
                   eleven|twelve|hundred|thousand|million|billion)\b
            )
        """

        original_numbers = set(re.findall(number_pattern, original, re.VERBOSE | re.IGNORECASE))
        rewritten_numbers = set(re.findall(number_pattern, rewritten, re.VERBOSE | re.IGNORECASE))

        # Normalize for comparison
        original_normalized = {n.lower().replace(",", "") for n in original_numbers}
        rewritten_normalized = {n.lower().replace(",", "") for n in rewritten_numbers}

        missing = original_normalized - rewritten_normalized

        if missing:
            return CheckResult(
                check_name="number_invariance",
                status=ValidationStatus.FAILED,
                message=f"Missing numbers: {', '.join(list(missing)[:5])}",
                details={"missing": list(missing)},
            )

        return CheckResult(
            check_name="number_invariance", status=ValidationStatus.PASSED, message="All numbers preserved"
        )

    def _check_dates(self, original_doc: Doc, rewritten_doc: Doc) -> CheckResult:
        """
        Check that all dates are preserved.

        Uses spaCy's DATE entity recognition.
        """
        original_dates = {ent.text.lower().strip() for ent in original_doc.ents if ent.label_ == "DATE"}

        rewritten_dates = {ent.text.lower().strip() for ent in rewritten_doc.ents if ent.label_ == "DATE"}

        missing = original_dates - rewritten_dates

        if missing:
            return CheckResult(
                check_name="date_invariance",
                status=ValidationStatus.FAILED,
                message=f"Missing dates: {', '.join(list(missing)[:3])}",
                details={"missing": list(missing)},
            )

        return CheckResult(check_name="date_invariance", status=ValidationStatus.PASSED, message="All dates preserved")

    def _check_attributions(self, original: str, rewritten: str) -> CheckResult:
        """
        Check that attributions (who said what) are preserved.

        Looks for patterns like "X said", "according to X".
        """
        # Pattern to match attributions
        attribution_pattern = r"""
            (?:
                (?:according\s+to|said|stated|announced|confirmed|
                   reported|claimed|argued|explained|noted)\s+
                (?:by\s+)?
                [A-Z][a-z]+(?:\s+[A-Z][a-z]+)*
            ) |
            (?:
                [A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+
                (?:said|stated|announced|confirmed|reported|
                   claimed|argued|explained|noted|told|added)
            )
        """

        original_attrs = set(re.findall(attribution_pattern, original, re.VERBOSE))
        rewritten_attrs = set(re.findall(attribution_pattern, rewritten, re.VERBOSE))

        # Normalize
        original_normalized = {a.lower().strip() for a in original_attrs if a.strip()}
        rewritten_normalized = {a.lower().strip() for a in rewritten_attrs if a.strip()}

        missing = original_normalized - rewritten_normalized

        if missing:
            return CheckResult(
                check_name="attribution_invariance",
                status=ValidationStatus.WARNING,
                message="Potentially changed attributions",
                details={"missing": list(missing)[:3]},
            )

        return CheckResult(
            check_name="attribution_invariance", status=ValidationStatus.PASSED, message="Attributions preserved"
        )

    def _check_modality(self, original: str, rewritten: str) -> CheckResult:
        """
        Check that modality (certainty levels) hasn't been upgraded.

        Ensures "alleged" doesn't become "confirmed", etc.
        """
        original_lower = original.lower()
        rewritten_lower = rewritten.lower()

        violations = []

        for soft in self.SOFT_MODALS:
            if soft in original_lower:
                # Check if any hard modal appeared in rewritten
                # that wasn't in original
                for hard in self.HARD_MODALS:
                    if hard in rewritten_lower and hard not in original_lower:
                        violations.append(f"{soft} -> {hard}")

        if violations:
            return CheckResult(
                check_name="modality_invariance",
                status=ValidationStatus.FAILED,
                message=f"Modality upgraded: {violations[0]}",
                details={"violations": violations},
            )

        return CheckResult(
            check_name="modality_invariance", status=ValidationStatus.PASSED, message="Modality levels preserved"
        )

    def _check_causality(self, original: str, rewritten: str) -> CheckResult:
        """
        Check that causal claims are preserved.

        Ensures cause-effect relationships aren't changed.
        """
        original_lower = original.lower()
        rewritten_lower = rewritten.lower()

        # Check for causal language in original
        original_causal = [w for w in self.CAUSAL_WORDS if w in original_lower]

        if not original_causal:
            return CheckResult(
                check_name="causality_invariance",
                status=ValidationStatus.PASSED,
                message="No causal claims to preserve",
            )

        # Check if causal language is preserved
        missing_causal = [w for w in original_causal if w not in rewritten_lower]

        if missing_causal:
            return CheckResult(
                check_name="causality_invariance",
                status=ValidationStatus.WARNING,
                message=f"Causal language changed: {', '.join(missing_causal[:3])}",
                details={"missing": missing_causal},
            )

        return CheckResult(
            check_name="causality_invariance", status=ValidationStatus.PASSED, message="Causal relationships preserved"
        )

    def _check_risk(self, original: str, rewritten: str) -> CheckResult:
        """
        Check that risk levels and warnings are preserved.

        Ensures safety-relevant information isn't removed.
        """
        risk_indicators = [
            "warning",
            "danger",
            "risk",
            "threat",
            "hazard",
            "emergency",
            "critical",
            "severe",
            "urgent",
            "evacuate",
            "avoid",
            "caution",
            "alert",
        ]

        original_lower = original.lower()
        rewritten_lower = rewritten.lower()

        original_risks = [r for r in risk_indicators if r in original_lower]
        missing_risks = [r for r in original_risks if r not in rewritten_lower]

        if missing_risks:
            return CheckResult(
                check_name="risk_invariance",
                status=ValidationStatus.FAILED,
                message=f"Risk indicators removed: {', '.join(missing_risks)}",
                details={"removed": missing_risks},
            )

        return CheckResult(
            check_name="risk_invariance", status=ValidationStatus.PASSED, message="Risk levels preserved"
        )

    def _check_quotes(self, original: str, rewritten: str) -> CheckResult:
        """
        Check that direct quotes are preserved verbatim.

        Quotes should never be modified during neutralization.
        """
        # Extract quoted content
        quote_pattern = r'"([^"]+)"|"([^"]+)"|\'([^\']+)\''

        original_quotes = set()
        for match in re.finditer(quote_pattern, original):
            quote = match.group(1) or match.group(2) or match.group(3)
            if quote and len(quote) > 10:  # Skip very short quotes
                original_quotes.add(quote.strip())

        # Check each quote is preserved
        missing_quotes = []
        for quote in original_quotes:
            if quote not in rewritten:
                missing_quotes.append(quote[:50] + "..." if len(quote) > 50 else quote)

        if missing_quotes:
            return CheckResult(
                check_name="quote_integrity",
                status=ValidationStatus.FAILED,
                message="Quotes modified or removed",
                details={"missing": missing_quotes[:3]},
            )

        return CheckResult(
            check_name="quote_integrity", status=ValidationStatus.PASSED, message="All quotes preserved verbatim"
        )

    def _check_scope(self, original: str, rewritten: str) -> CheckResult:
        """
        Check that scope quantifiers are preserved.

        Ensures "all" doesn't become "some", etc.
        """
        original_lower = original.lower()
        rewritten_lower = rewritten.lower()

        scope_changes = []

        for word in self.SCOPE_WORDS:
            original_count = original_lower.count(word)
            rewritten_count = rewritten_lower.count(word)

            if original_count > 0 and rewritten_count < original_count:
                scope_changes.append(f"'{word}' reduced")

        if scope_changes:
            return CheckResult(
                check_name="scope_invariance",
                status=ValidationStatus.WARNING,
                message=f"Scope may have changed: {scope_changes[0]}",
                details={"changes": scope_changes},
            )

        return CheckResult(
            check_name="scope_invariance", status=ValidationStatus.PASSED, message="Scope quantifiers preserved"
        )

    def _check_negation(self, original: str, rewritten: str) -> CheckResult:
        """
        Check that negations are preserved.

        Accidentally removing a "not" can completely reverse meaning.
        """
        original_lower = original.lower()
        rewritten_lower = rewritten.lower()

        removed_negations = []

        for neg in self.NEGATION_WORDS:
            original_count = len(re.findall(r"\b" + neg + r"\b", original_lower))
            rewritten_count = len(re.findall(r"\b" + neg + r"\b", rewritten_lower))

            if original_count > rewritten_count:
                removed_negations.append(neg)

        if removed_negations:
            return CheckResult(
                check_name="negation_integrity",
                status=ValidationStatus.FAILED,
                message=f"Negations removed: {', '.join(removed_negations)}",
                details={"removed": removed_negations},
            )

        return CheckResult(
            check_name="negation_integrity", status=ValidationStatus.PASSED, message="Negations preserved"
        )


@lru_cache(maxsize=1)
def get_validator() -> RedLineValidator:
    """Get or create singleton validator instance."""
    return RedLineValidator()
