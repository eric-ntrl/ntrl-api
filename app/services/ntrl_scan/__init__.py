# app/services/ntrl_scan/__init__.py
"""
NTRL-SCAN: Detection phase of NTRL Filter v2

This module provides parallel detection of manipulation patterns in news articles.
It uses three complementary detectors:
- Lexical: Fast regex/pattern matching (~20ms)
- Structural: spaCy NLP analysis (~80ms)
- Semantic: LLM-based detection (~300ms)

Usage:
    from app.services.ntrl_scan import NTRLScanner, ScannerConfig

    # Basic usage with defaults
    scanner = NTRLScanner()
    result = await scanner.scan("Article text here", segment=ArticleSegment.BODY)

    # Configure specific detectors
    config = ScannerConfig(
        enable_semantic=False,  # Disable LLM for faster scanning
        semantic_provider="anthropic",
    )
    scanner = NTRLScanner(config=config)

    # Scan entire article
    results = await scanner.scan_article(
        title="Article Title",
        body="Article body text...",
    )
"""

from .lexical_detector import LexicalDetector, get_lexical_detector
from .scanner import NTRLScanner, ScannerConfig, scan_text
from .semantic_detector import (
    LLMConfig,
    SemanticDetector,
    create_semantic_detector,
)
from .structural_detector import StructuralDetector, get_structural_detector
from .types import (
    SEGMENT_MULTIPLIERS,
    ArticleSegment,
    DetectionInstance,
    DetectorSource,
    MergedScanResult,
    ScanResult,
    SpanAction,
)

__all__ = [
    # Types
    "DetectionInstance",
    "ScanResult",
    "MergedScanResult",
    "ArticleSegment",
    "DetectorSource",
    "SpanAction",
    "SEGMENT_MULTIPLIERS",
    # Lexical detector
    "LexicalDetector",
    "get_lexical_detector",
    # Structural detector
    "StructuralDetector",
    "get_structural_detector",
    # Semantic detector
    "SemanticDetector",
    "create_semantic_detector",
    "LLMConfig",
    # Scanner (main entry point)
    "NTRLScanner",
    "ScannerConfig",
    "scan_text",
]
