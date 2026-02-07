# app/services/ntrl_fix/__init__.py
"""
NTRL-FIX: Rewriting phase of NTRL Filter v2

This module provides span-guided content rewriting to neutralize detected
manipulation patterns. It uses the results from ntrl-scan to intelligently
fix manipulation while preserving all factual content.

Components:
- NTRLFixer: Main orchestrator for parallel generation
- DetailFullGenerator: Full article neutralization
- DetailBriefGenerator: Brief synthesis
- FeedOutputsGenerator: Title and summary
- RedLineValidator: 10 invariance checks

Usage:
    from app.services.ntrl_fix import NTRLFixer, FixerConfig

    # Basic usage
    fixer = NTRLFixer()
    result = await fixer.fix(
        body="Article body...",
        title="Original title...",
        body_scan=scan_result,
    )

    # Check validation
    if result.validation.passed:
        print(f"Neutralized: {result.detail_full}")
    else:
        print(f"Validation failed: {result.validation.failures}")
"""

from .detail_brief_gen import (
    DetailBriefGenerator,
    DetailBriefResult,
)
from .detail_full_gen import (
    DetailFullGenerator,
    DetailFullResult,
)
from .feed_outputs_gen import (
    FeedOutputsGenerator,
    FeedOutputsResult,
)
from .fixer import (
    FixerConfig,
    NTRLFixer,
    fix_article,
)
from .types import (
    ChangeRecord,
    CheckResult,
    FixAction,
    FixResult,
    GeneratorConfig,
    RiskLevel,
    SpanContext,
    ValidationResult,
    ValidationStatus,
)
from .validator import (
    RedLineValidator,
    get_validator,
)

__all__ = [
    # Types
    "FixAction",
    "ValidationStatus",
    "RiskLevel",
    "ChangeRecord",
    "CheckResult",
    "ValidationResult",
    "FixResult",
    "GeneratorConfig",
    "SpanContext",
    # Validator
    "RedLineValidator",
    "get_validator",
    # Generators
    "DetailFullGenerator",
    "DetailFullResult",
    "DetailBriefGenerator",
    "DetailBriefResult",
    "FeedOutputsGenerator",
    "FeedOutputsResult",
    # Fixer (main entry point)
    "NTRLFixer",
    "FixerConfig",
    "fix_article",
]
