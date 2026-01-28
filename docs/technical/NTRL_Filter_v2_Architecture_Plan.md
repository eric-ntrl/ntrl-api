# NTRL Filter v2: High-Performance Architecture Plan

**Version**: 1.0
**Date**: January 24, 2026
**Status**: Approved for Implementation
**Author**: Claude Code + Eric Brown

---

## Executive Summary

Redesign the NTRL filter as a two-phase, parallel architecture:
- **Phase 1 (ntrl-scan)**: Detect manipulation spans with 80+ taxonomy types
- **Phase 2 (ntrl-fix)**: Rewrite content guided by detected spans

**Target**: 1-2 seconds per article (vs 6-12 seconds current)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    NTRL FILTER v2 ARCHITECTURE                              │
│                    Target: 1-2 seconds per article                          │
└─────────────────────────────────────────────────────────────────────────────┘

                    ┌─────────────────────────────────────┐
                    │        NORMALIZED ARTICLE           │
                    │   (body + metadata from ingestion)  │
                    └─────────────────────────────────────┘
                                      │
    ══════════════════════════════════╪══════════════════════════════════
    ║           PHASE 1: NTRL-SCAN (Detection)  ~400ms                  ║
    ══════════════════════════════════╪══════════════════════════════════
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         │                            │                            │
         ▼                            ▼                            ▼
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│  LEXICAL SCAN   │         │ STRUCTURAL SCAN │         │  SEMANTIC SCAN  │
│  (regex + lists)│         │   (spaCy NLP)   │         │ (Haiku/4o-mini) │
│     ~20ms       │         │     ~80ms       │         │    ~300ms       │
└─────────────────┘         └─────────────────┘         └─────────────────┘
         │                            │                            │
         └────────────────────────────┼────────────────────────────┘
                                      ▼
                    ┌─────────────────────────────────────┐
                    │        MERGE + SCORE + DECIDE       │
                    │   • Dedupe overlapping spans        │
                    │   • Assign severity 1-5             │
                    │   • Apply segment multipliers       │
                    │   • Determine action per span       │
                    │              ~10ms                  │
                    └─────────────────────────────────────┘
                                      │
                                      │ DetectionResult {
                                      │   spans: [{type_id, severity, action, ...}],
                                      │   summary_stats: {...}
                                      │ }
                                      ▼
    ══════════════════════════════════╪══════════════════════════════════
    ║           PHASE 2: NTRL-FIX (Rewriting)  ~800ms                   ║
    ══════════════════════════════════╪══════════════════════════════════
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         │                            │                            │
         ▼                            ▼                            ▼
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│  GENERATE       │         │  GENERATE       │         │  GENERATE       │
│  detail_full    │         │  detail_brief   │         │  feed_outputs   │
│ (GPT-4o/Sonnet) │         │ (GPT-4o/Sonnet) │         │ (Haiku/4o-mini) │
│    ~600ms       │         │    ~500ms       │         │    ~200ms       │
└─────────────────┘         └─────────────────┘         └─────────────────┘
         │                            │                            │
         └────────────────────────────┼────────────────────────────┘
                                      ▼
                    ┌─────────────────────────────────────┐
                    │         RED-LINE VALIDATOR          │
                    │   10 invariance checks (pure Python)│
                    │              ~20ms                  │
                    └─────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────────┐
                    │             OUTPUTS                 │
                    │  • Clean article (5 fields)         │
                    │  • Transparency package             │
                    └─────────────────────────────────────┘
```

---

## 1. Canonical Taxonomy (80+ Types)

### 1.1 New Enum Structure

Create `/code/ntrl-api/app/taxonomy.py`:

```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional

class ManipulationCategory(str, Enum):
    """Level 1 categories"""
    ATTENTION_ENGAGEMENT = "A"      # Attention & Engagement
    EMOTIONAL_AFFECTIVE = "B"       # Emotional & Affective
    COGNITIVE_EPISTEMIC = "C"       # Cognitive & Epistemic
    LINGUISTIC_FRAMING = "D"        # Linguistic & Framing
    STRUCTURAL_EDITORIAL = "E"      # Structural & Editorial
    INCENTIVE_META = "F"            # Incentive & Meta

@dataclass
class ManipulationType:
    type_id: str                    # e.g., "A.1.1"
    category: ManipulationCategory  # L1
    l2: str                         # e.g., "Curiosity Gap"
    l3: str                         # e.g., "Withheld Key Fact"
    label: str                      # Human-friendly name
    examples: list[str]             # Detection examples
    default_severity: int           # 1-5
    default_action: str             # remove/replace/rewrite/annotate

# Full taxonomy registry (80+ types)
MANIPULATION_TAXONOMY = {
    # A. Attention & Engagement
    "A.1.1": ManipulationType("A.1.1", ManipulationCategory.ATTENTION_ENGAGEMENT,
                              "Curiosity Gap", "Curiosity gap",
                              "Curiosity gap", ["You won't believe"], 4, "rewrite"),
    "A.1.2": ManipulationType("A.1.2", ManipulationCategory.ATTENTION_ENGAGEMENT,
                              "Curiosity Gap", "Open-loop teaser",
                              "Open-loop teaser", ["but it's not what you think"], 4, "rewrite"),
    # ... 78+ more types
}
```

### 1.2 Database Schema Changes

Update `/code/ntrl-api/app/models.py`:

```python
class ManipulationSpan(Base):
    """Enhanced span model with full taxonomy support"""
    __tablename__ = "manipulation_spans"

    id = Column(UUID, primary_key=True)
    story_neutralized_id = Column(UUID, ForeignKey("story_neutralized.id"))

    # Taxonomy binding
    type_id_primary = Column(String(10), nullable=False)  # e.g., "A.1.1"
    type_ids_secondary = Column(ARRAY(String), default=[])

    # Location
    segment = Column(String(20))  # title/deck/lede/body/caption
    span_start = Column(Integer, nullable=False)
    span_end = Column(Integer, nullable=False)
    original_text = Column(Text, nullable=False)

    # Scoring
    confidence = Column(Float, nullable=False)  # 0-1
    severity = Column(Integer, nullable=False)  # 1-5
    severity_weighted = Column(Float)  # After segment multiplier

    # Decision
    action = Column(String(20))  # remove/replace/rewrite/annotate/preserve
    rewritten_text = Column(Text)
    rationale = Column(Text)

    # Audit
    detector_source = Column(String(20))  # lexical/structural/semantic
    exemptions_applied = Column(ARRAY(String), default=[])
```

---

## 2. Phase 1: NTRL-SCAN (Detection)

### 2.1 Detector Architecture

Create `/code/ntrl-api/app/services/ntrl_scan/`:

```
ntrl_scan/
├── __init__.py
├── detector_base.py      # Abstract detector interface
├── lexical_detector.py   # Regex + word lists (~20ms)
├── structural_detector.py # spaCy NLP (~80ms)
├── semantic_detector.py  # LLM-based (~300ms)
├── merger.py             # Combine + dedupe spans
├── scorer.py             # Severity scoring + segment multipliers
├── decider.py            # Policy matrix → action
└── scanner.py            # Orchestrator (parallel execution)
```

### 2.2 Lexical Detector (Pure Python, ~20ms)

```python
class LexicalDetector:
    """Fast pattern matching for obvious manipulation"""

    PATTERNS = {
        "A.1.1": [r"you won't believe", r"can't believe"],
        "A.1.2": [r"but it's not what you think", r"one thing changes everything"],
        "A.2.1": [r"BREAKING", r"JUST IN", r"URGENT", r"DEVELOPING"],
        "B.2.2": [r"\bslams?\b", r"\bblasts?\b", r"\bdestroys?\b", r"\beviscerates?\b"],
        # ... 50+ more patterns
    }

    QUOTE_BOUNDARY_REGEX = r'"[^"]*"|\'[^\']*\''  # Skip quoted content

    def detect(self, text: str, segment: str) -> list[DetectionInstance]:
        spans = []
        for type_id, patterns in self.PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    if not self._inside_quote(text, match.start()):
                        spans.append(DetectionInstance(
                            type_id=type_id,
                            span_start=match.start(),
                            span_end=match.end(),
                            text=match.group(),
                            confidence=0.95,
                            detector="lexical"
                        ))
        return spans
```

### 2.3 Structural Detector (spaCy, ~80ms)

```python
class StructuralDetector:
    """NLP-based detection for linguistic manipulation"""

    def __init__(self):
        self.nlp = spacy.load("en_core_web_sm")  # Fast model

    def detect(self, text: str, segment: str) -> list[DetectionInstance]:
        doc = self.nlp(text)
        spans = []

        # D.3.1 Passive voice with hidden agent
        for sent in doc.sents:
            if self._is_agentless_passive(sent):
                spans.append(DetectionInstance(
                    type_id="D.3.1",
                    span_start=sent.start_char,
                    span_end=sent.end_char,
                    text=sent.text,
                    confidence=0.85,
                    detector="structural"
                ))

        # A.1.4 Rhetorical questions
        for sent in doc.sents:
            if sent.text.strip().endswith("?") and self._is_rhetorical(sent):
                spans.append(DetectionInstance(
                    type_id="A.1.4",
                    ...
                ))

        return spans
```

### 2.4 Semantic Detector (LLM, ~300ms)

```python
class SemanticDetector:
    """LLM-based detection for subtle manipulation"""

    def __init__(self, provider: str = "haiku"):
        self.model = "claude-3-5-haiku-20241022" if provider == "haiku" else "gpt-4o-mini"

    PROMPT = """Analyze this text for manipulation patterns NOT caught by simple rules.

Focus on:
- C.3.2 Motive certainty ("They did this to...")
- C.3.3 Intent attribution ("Officials want you to...")
- B.4.1 Identity/tribal priming ("Real Americans...")
- D.4.1 Presupposition traps ("Why did officials fail...")
- F.3.1 Agenda masking (advocacy as neutral)

Text: {text}

Return JSON array of detections with: type_id, span_start, span_end, text, confidence, rationale
Only return subtle manipulation that regex wouldn't catch."""

    async def detect(self, text: str, segment: str) -> list[DetectionInstance]:
        response = await self.llm.generate(
            self.PROMPT.format(text=text),
            response_format="json",
            max_tokens=1024
        )
        return self._parse_response(response)
```

### 2.5 Scanner Orchestrator (Parallel Execution)

```python
class NTRLScanner:
    """Orchestrates parallel detection and merges results"""

    async def scan(self, article: NormalizedArticle) -> ScanResult:
        # Run detectors in parallel
        lexical_task = asyncio.create_task(
            self.lexical.detect(article.body, "body")
        )
        structural_task = asyncio.create_task(
            self.structural.detect(article.body, "body")
        )
        semantic_task = asyncio.create_task(
            self.semantic.detect(article.body, "body")
        )

        # Also scan title with higher weight
        title_lexical = asyncio.create_task(
            self.lexical.detect(article.title, "title")
        )

        # Await all
        results = await asyncio.gather(
            lexical_task, structural_task, semantic_task, title_lexical
        )

        # Merge and dedupe
        all_spans = self.merger.merge(results)

        # Score with severity and segment multipliers
        scored_spans = self.scorer.score(all_spans)

        # Decide action per span
        decided_spans = self.decider.decide(scored_spans)

        return ScanResult(
            spans=decided_spans,
            summary_stats=self._compute_stats(decided_spans)
        )
```

---

## 3. Phase 2: NTRL-FIX (Rewriting)

### 3.1 Fixer Architecture

Create `/code/ntrl-api/app/services/ntrl_fix/`:

```
ntrl_fix/
├── __init__.py
├── fixer.py              # Orchestrator
├── detail_full_gen.py    # Full article rewrite
├── detail_brief_gen.py   # Brief synthesis
├── feed_outputs_gen.py   # Title + summary
├── validator.py          # Red-line validator
└── templates.py          # Rewrite templates
```

### 3.2 Span-Guided Rewriting

The key innovation: instead of asking LLM to detect AND rewrite, we provide the spans:

```python
DETAIL_FULL_PROMPT = """Rewrite this article by applying the following changes.

ORIGINAL ARTICLE:
{body}

CHANGES TO APPLY:
{spans_formatted}

For each span:
- If action=remove: Delete the text entirely
- If action=replace: Use the suggested replacement
- If action=rewrite: Rewrite to remove manipulation while preserving facts
- If action=annotate: Keep text, note in transparency

CRITICAL RULES:
- Preserve ALL facts, names, numbers, dates, quotes
- Never change modality (alleged→confirmed, may→will)
- Never infer motives or add facts
- Output should be ~80-100% of input length

Return JSON: {"filtered_article": "...", "changes_applied": [...]}"""
```

### 3.3 Parallel Generation

```python
class NTRLFixer:
    """Generates all outputs in parallel, guided by scan results"""

    async def fix(self, article: NormalizedArticle, scan: ScanResult) -> FixResult:
        # Prepare span context for prompts
        span_context = self._format_spans_for_prompt(scan.spans)

        # Run generators in parallel
        detail_full_task = asyncio.create_task(
            self.detail_full_gen.generate(article.body, span_context)
        )
        detail_brief_task = asyncio.create_task(
            self.detail_brief_gen.generate(article.body, span_context)
        )
        feed_outputs_task = asyncio.create_task(
            self.feed_outputs_gen.generate(article.body, span_context)
        )

        detail_full, detail_brief, feed_outputs = await asyncio.gather(
            detail_full_task, detail_brief_task, feed_outputs_task
        )

        # Validate all outputs
        validation = self.validator.validate(
            original=article,
            detail_full=detail_full,
            detail_brief=detail_brief,
            feed_outputs=feed_outputs
        )

        if not validation.passed:
            # Fallback: retry with conservative settings
            return await self._fallback_fix(article, scan, validation.failures)

        return FixResult(
            detail_full=detail_full,
            detail_brief=detail_brief,
            **feed_outputs,
            validation=validation
        )
```

---

## 4. Red-Line Validator (10 Invariance Checks)

```python
class RedLineValidator:
    """Ensures rewriting doesn't violate semantic invariants"""

    def validate(self, original: str, rewritten: str) -> ValidationResult:
        checks = {
            "entity_invariance": self._check_entities(original, rewritten),
            "number_invariance": self._check_numbers(original, rewritten),
            "date_invariance": self._check_dates(original, rewritten),
            "attribution_invariance": self._check_attributions(original, rewritten),
            "modality_invariance": self._check_modality(original, rewritten),
            "causality_invariance": self._check_causality(original, rewritten),
            "risk_invariance": self._check_risk(original, rewritten),
            "quote_integrity": self._check_quotes(original, rewritten),
            "scope_invariance": self._check_scope(original, rewritten),
            "negation_integrity": self._check_negation(original, rewritten),
        }

        failures = [k for k, v in checks.items() if not v.passed]

        return ValidationResult(
            passed=len(failures) == 0,
            checks=checks,
            failures=failures,
            risk_level=self._compute_risk(failures)
        )

    def _check_entities(self, original: str, rewritten: str) -> CheckResult:
        """Verify names/orgs/places unchanged"""
        original_ents = self._extract_entities(original)
        rewritten_ents = self._extract_entities(rewritten)
        missing = original_ents - rewritten_ents
        return CheckResult(passed=len(missing) == 0, missing=list(missing))

    def _check_modality(self, original: str, rewritten: str) -> CheckResult:
        """Verify alleged/may/likely not upgraded to did/will/confirmed"""
        SOFT_MODALS = ["alleged", "allegedly", "may", "might", "could", "likely", "suspected"]
        HARD_MODALS = ["confirmed", "proven", "did", "will", "definitely"]

        for soft in SOFT_MODALS:
            if soft in original.lower():
                # Check it wasn't replaced with hard modal
                if any(hard in rewritten.lower() for hard in HARD_MODALS):
                    return CheckResult(passed=False, violation=f"{soft} → hard modal")
        return CheckResult(passed=True)
```

---

## 5. LLM Strategy

| Task | Model | Rationale | Latency |
|------|-------|-----------|---------|
| Semantic Detection | Claude 3.5 Haiku | Fast, good at pattern recognition | ~300ms |
| detail_full Generation | GPT-4o | Best at preserving nuance while rewriting | ~600ms |
| detail_brief Synthesis | Claude 3.5 Sonnet | Excellent summarization | ~500ms |
| Feed Outputs | GPT-4o-mini | Simple task, fast model | ~200ms |
| Batch Background | Claude 3.5 Sonnet | 3-5 articles per call | ~1.5s total |

### Model Fallback Chain
```
Primary: OpenAI GPT-4o
   ↓ (rate limit/error)
Secondary: Claude 3.5 Sonnet
   ↓ (rate limit/error)
Tertiary: Gemini 2.0 Flash
   ↓ (all fail)
Fallback: Mock provider (rules-only, no LLM)
```

---

## 6. Transparency Package

```python
@dataclass
class TransparencyPackage:
    """Rich transparency output for ntrl view UI"""

    # Summary statistics
    total_detections: int
    detections_by_category: dict[str, int]  # A: 5, B: 3, C: 2
    detections_by_severity: dict[int, int]  # 1: 2, 2: 5, 3: 3
    manipulation_density: float  # detections / word count

    # Per-span details
    changes: list[ChangeRecord]  # Full before/after with type_id

    # Epistemic risk flags
    epistemic_flags: list[str]  # ["anonymous_source_heavy", "missing_baseline"]

    # Red-line validation
    validation_result: ValidationResult

    # Audit trail
    filter_version: str
    taxonomy_version: str
    models_used: dict[str, str]
    processing_time_ms: int

@dataclass
class ChangeRecord:
    detection_id: str
    type_id: str
    category_label: str  # "Emotional & Affective"
    type_label: str      # "Rage verbs"
    segment: str
    span_start: int
    span_end: int
    before: str
    after: str
    action: str
    severity: int
    confidence: float
    rationale: str
```

---

## 7. Performance Optimizations

### 7.1 Caching Strategy
- **Normalized article cache**: 1 hour TTL in Redis
- **Scan result cache**: By content hash, persisted with article
- **LLM response cache**: By prompt hash, 24 hour TTL

### 7.2 Adaptive Batching
```python
class AdaptiveBatcher:
    """Single article for real-time, batch for background"""

    async def process(self, articles: list[Article], mode: str):
        if mode == "realtime" or len(articles) == 1:
            # Process individually for lowest latency
            return await asyncio.gather(*[
                self.pipeline.process(a) for a in articles
            ])
        else:
            # Batch 3-5 articles in single LLM calls
            batches = self._chunk(articles, size=4)
            return await asyncio.gather(*[
                self.pipeline.process_batch(b) for b in batches
            ])
```

### 7.3 Connection Pooling
- HTTP/2 persistent connections to LLM APIs
- Connection pool size: 10 per provider
- Request timeout: 30 seconds

---

## 8. Files to Create/Modify

### New Files
```
/code/ntrl-api/app/
├── taxonomy.py                          # 80+ manipulation types
├── services/
│   ├── ntrl_scan/
│   │   ├── __init__.py
│   │   ├── detector_base.py
│   │   ├── lexical_detector.py
│   │   ├── structural_detector.py
│   │   ├── semantic_detector.py
│   │   ├── merger.py
│   │   ├── scorer.py
│   │   ├── decider.py
│   │   └── scanner.py
│   ├── ntrl_fix/
│   │   ├── __init__.py
│   │   ├── fixer.py
│   │   ├── detail_full_gen.py
│   │   ├── detail_brief_gen.py
│   │   ├── feed_outputs_gen.py
│   │   ├── validator.py
│   │   └── templates.py
│   └── pipeline.py                      # New orchestrator
```

### Modified Files
```
/code/ntrl-api/app/
├── models.py                            # Add ManipulationSpan model
├── schemas/
│   ├── transparency.py                  # New transparency schemas
│   └── stories.py                       # Update response schemas
├── routers/
│   └── admin.py                         # Add /v1/scan and /v1/fix endpoints
└── Pipfile                              # Add spacy dependency
```

---

## 9. Migration Path

### Phase 1: Foundation
1. Create taxonomy.py with all 80+ types
2. Add ManipulationSpan model + migration
3. Implement lexical detector with top 30 patterns
4. Write unit tests for detector

### Phase 2: Detection
5. Implement structural detector with spaCy
6. Implement semantic detector with Haiku
7. Build scanner orchestrator with parallel execution
8. Test scan pipeline end-to-end

### Phase 3: Generation
9. Implement span-guided detail_full generator
10. Implement detail_brief generator
11. Implement feed_outputs generator
12. Build red-line validator

### Phase 4: Integration
13. Wire up full pipeline
14. Implement caching layer
15. Add adaptive batching
16. Performance testing and optimization

---

## 10. Verification

### Unit Tests
```bash
# Run detector tests
pipenv run pytest tests/test_lexical_detector.py -v
pipenv run pytest tests/test_structural_detector.py -v
pipenv run pytest tests/test_semantic_detector.py -v

# Run validator tests
pipenv run pytest tests/test_red_line_validator.py -v
```

### Integration Test
```bash
# Process single article through new pipeline
curl -X POST http://localhost:8000/v1/pipeline/process \
  -H "Content-Type: application/json" \
  -d '{"article_id": "uuid-here", "mode": "full"}'
```

### Performance Benchmark
```bash
# Measure latency for 100 articles
pipenv run python scripts/benchmark_pipeline.py --count=100
# Target: p50 < 1.5s, p95 < 2.5s
```

### A/B Comparison
```bash
# Compare old vs new pipeline outputs
pipenv run python scripts/compare_pipelines.py --sample=50
```

---

## 11. Article Ingestion Architecture (Multi-Source)

### 11.1 Ingestion Strategy Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    MULTI-SOURCE INGESTION ARCHITECTURE                      │
│              Goal: Maximum coverage of quality journalism globally          │
└─────────────────────────────────────────────────────────────────────────────┘

                         ┌─────────────────────────────────┐
                         │      SOURCE REGISTRY            │
                         │  (500+ sources, expandable)     │
                         └─────────────────────────────────┘
                                        │
         ┌──────────────────────────────┼──────────────────────────────┐
         │                              │                              │
         ▼                              ▼                              ▼
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│   RSS FEEDS     │         │   WEB SCRAPING  │         │   NEWS APIs     │
│  (Free, fast)   │         │  (Broad reach)  │         │ (Paid, reliable)│
│                 │         │                 │         │                 │
│ • AP, Reuters   │         │ • Trafilatura   │         │ • NewsAPI.org   │
│ • NPR, BBC      │         │ • Newspaper3k   │         │ • Mediastack    │
│ • NYT, WaPo     │         │ • BeautifulSoup │         │ • Currents API  │
│ • Local papers  │         │ • Playwright    │         │ • GDELT         │
│                 │         │   (JS-rendered) │         │ • Event Registry│
│   ~200 sources  │         │   ~100 sources  │         │   ~10 providers │
└─────────────────┘         └─────────────────┘         └─────────────────┘
         │                              │                              │
         └──────────────────────────────┼──────────────────────────────┘
                                        ▼
                         ┌─────────────────────────────────┐
                         │        NORMALIZATION            │
                         │  • HTML cleanup                 │
                         │  • Cruft removal                │
                         │  • Encoding normalization       │
                         │  • Language detection           │
                         └─────────────────────────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────────┐
                         │        DEDUPLICATION            │
                         │  • URL hash                     │
                         │  • Content similarity (MinHash) │
                         │  • Wire service tracking        │
                         └─────────────────────────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────────┐
                         │     CLASSIFICATION              │
                         │  • 20+ categories (expandable)  │
                         │  • Multi-label support          │
                         │  • Geographic tagging           │
                         └─────────────────────────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────────┐
                         │        STORAGE                  │
                         │  • Metadata → PostgreSQL        │
                         │  • Body → S3                    │
                         │  • Index → Elasticsearch (opt)  │
                         └─────────────────────────────────┘
```

### 11.2 Source Types and Strategies

#### A. RSS Feeds (Primary, Free)

```python
class RSSIngestionProvider:
    """Polls RSS feeds for new articles"""

    TIER_1_SOURCES = [
        # Wire Services (highest priority)
        {"name": "AP News", "rss": "https://rsshub.app/apnews/topics/apf-topnews"},
        {"name": "Reuters", "rss": "https://www.reutersagency.com/feed/"},
        {"name": "AFP", "rss": "https://www.afp.com/en/rss"},

        # Major US
        {"name": "NPR", "rss": "https://feeds.npr.org/1001/rss.xml"},
        {"name": "PBS NewsHour", "rss": "https://www.pbs.org/newshour/feeds/rss/headlines"},
        {"name": "NYT", "rss": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"},
        {"name": "Washington Post", "rss": "https://feeds.washingtonpost.com/rss/world"},

        # Major International
        {"name": "BBC", "rss": "http://feeds.bbci.co.uk/news/world/rss.xml"},
        {"name": "The Guardian", "rss": "https://www.theguardian.com/world/rss"},
        {"name": "Al Jazeera", "rss": "https://www.aljazeera.com/xml/rss/all.xml"},
        {"name": "DW", "rss": "https://rss.dw.com/xml/rss-en-all"},
        {"name": "France24", "rss": "https://www.france24.com/en/rss"},
        {"name": "NHK World", "rss": "https://www3.nhk.or.jp/nhkworld/en/news/"},
    ]

    CATEGORY_FEEDS = {
        "business": ["Bloomberg", "Financial Times", "WSJ", "CNBC"],
        "technology": ["Ars Technica", "The Verge", "Wired", "TechCrunch"],
        "science": ["Nature", "Science", "Scientific American", "Phys.org"],
        "health": ["STAT News", "KFF Health News", "MedPage Today"],
        "sports": ["ESPN", "The Athletic", "Sports Illustrated"],
        "entertainment": ["Variety", "Hollywood Reporter", "Rolling Stone"],
        "politics": ["Politico", "The Hill", "Roll Call"],
        # ... expand to 20+ categories
    }
```

#### B. Web Scraping (Secondary, Broad Reach)

```python
class ScrapingIngestionProvider:
    """Direct scraping for sources without good RSS"""

    SCRAPER_CONFIGS = {
        "trafilatura": {
            "enabled": True,
            "fallback_order": 1,
            "config": {
                "favor_precision": True,
                "include_comments": False,
                "include_tables": True,
                "deduplicate": True,
            }
        },
        "newspaper3k": {
            "enabled": True,
            "fallback_order": 2,
            "use_for": ["legacy_sites", "blogs"]
        },
        "playwright": {
            "enabled": True,
            "fallback_order": 3,
            "use_for": ["js_rendered", "paywalled_previews"],
            "config": {
                "wait_for": "networkidle",
                "timeout_ms": 30000
            }
        }
    }

    async def scrape(self, url: str) -> ArticleContent:
        """Try scrapers in priority order"""
        for scraper_name in self._get_scraper_order(url):
            try:
                content = await self.scrapers[scraper_name].extract(url)
                if self._is_valid_article(content):
                    return content
            except ScraperError:
                continue
        raise IngestionError(f"All scrapers failed for {url}")
```

#### C. News APIs (Premium, High-Reliability)

```python
class APIIngestionProvider:
    """Paid and free news APIs for reliable, structured data"""

    API_PROVIDERS = {
        "newsapi": {
            "url": "https://newsapi.org/v2/",
            "type": "freemium",  # 100 req/day free, then paid
            "features": ["full_content", "sources", "categories"],
            "rate_limit": 100,  # per day
        },
        "mediastack": {
            "url": "https://api.mediastack.com/v1/",
            "type": "paid",
            "features": ["full_content", "multilingual", "historical"],
            "rate_limit": 500,  # per month on free tier
        },
        "currents": {
            "url": "https://api.currentsapi.services/v1/",
            "type": "freemium",
            "features": ["real_time", "categories", "language"],
            "rate_limit": 600,  # per day
        },
        "gdelt": {
            "url": "https://api.gdeltproject.org/",
            "type": "free",
            "features": ["global_coverage", "sentiment", "themes"],
            "rate_limit": None,  # No limit
        },
        "event_registry": {
            "url": "https://eventregistry.org/api/v1/",
            "type": "paid",
            "features": ["events", "concepts", "clusters"],
            "rate_limit": 2000,  # per day
        },
        "perigon": {
            "url": "https://api.goperigon.com/v1/",
            "type": "paid",
            "features": ["journalist_info", "bias_scoring", "clustering"],
            "rate_limit": 1000,
        }
    }
```

#### D. Additional Ingestion Methods (Future)

```python
# Social listening (Twitter/X, Reddit)
class SocialIngestionProvider:
    """Track breaking news from social sources"""
    sources = ["twitter_lists", "reddit_news", "bluesky"]

# Newsletter parsing
class NewsletterIngestionProvider:
    """Parse email newsletters for exclusive content"""
    sources = ["substack", "beehiiv", "buttondown"]

# Podcast transcription
class PodcastIngestionProvider:
    """Transcribe news podcasts"""
    sources = ["npr_podcasts", "bbc_podcasts", "spotify_news"]

# Video news transcription
class VideoIngestionProvider:
    """Transcribe news videos"""
    sources = ["youtube_news", "c_span"]
```

### 11.3 Expanded Category System (20+ Categories)

```python
class NewsCategory(str, Enum):
    """Expanded from 5 to 20+ categories"""

    # Original 5
    WORLD = "world"
    US = "us"
    BUSINESS = "business"
    TECHNOLOGY = "technology"
    SPORTS = "sports"

    # Expanded categories
    POLITICS = "politics"           # Domestic political news
    ECONOMY = "economy"             # Markets, Fed, employment
    SCIENCE = "science"             # Research, discoveries
    HEALTH = "health"               # Medical, public health
    ENVIRONMENT = "environment"     # Climate, conservation
    ENTERTAINMENT = "entertainment" # Movies, music, celebrities
    CULTURE = "culture"             # Arts, books, lifestyle
    EDUCATION = "education"         # Schools, universities
    CRIME = "crime"                 # Law enforcement, courts
    OPINION = "opinion"             # Editorials, op-eds (flagged differently)
    LOCAL = "local"                 # Regional news (with geo-tagging)
    INTERNATIONAL = "international" # Non-US global affairs
    MILITARY = "military"           # Defense, veterans
    RELIGION = "religion"           # Faith, religious institutions
    FOOD = "food"                   # Food industry, recipes
    TRAVEL = "travel"               # Tourism, destinations
    REAL_ESTATE = "real_estate"     # Housing, property
    AUTOMOTIVE = "automotive"       # Cars, transportation
    WEATHER = "weather"             # Forecasts, climate events
    OBITUARIES = "obituaries"       # Notable deaths

# Multi-label support
class ArticleCategories:
    primary: NewsCategory           # Main category
    secondary: list[NewsCategory]   # Additional categories (max 3)
    geographic: list[str]           # ["US", "California", "San Francisco"]
```

### 11.4 Source Quality Scoring

```python
@dataclass
class SourceQuality:
    """Track source reliability for prioritization"""

    source_id: str

    # Credibility metrics
    factual_rating: float       # 0-1, from media bias checkers
    editorial_standards: float  # 0-1, does it issue corrections?
    transparency_score: float   # 0-1, ownership/funding disclosed?

    # Content metrics
    avg_article_length: int     # Longer = more substantial
    multimedia_ratio: float     # Images, videos per article
    update_frequency: str       # "hourly", "daily", "weekly"

    # NTRL-specific metrics
    manipulation_density: float # Avg manipulation per article
    neutralization_success: float # How often our filter works well

    # Tier assignment
    tier: int  # 1 = highest priority, 4 = lowest

SOURCE_TIERS = {
    1: ["AP", "Reuters", "AFP", "BBC", "NPR"],  # Wire + public broadcasters
    2: ["NYT", "WaPo", "Guardian", "WSJ"],      # Major quality papers
    3: ["CNN", "MSNBC", "Fox", "Politico"],     # Cable news, political
    4: ["Tabloids", "Aggregators", "Blogs"],    # Lower editorial standards
}
```

---

## 12. Anti-Sterility Guardrails (What NOT to Remove)

The spec defines 7 categories of content that MUST be preserved. This is critical to avoid making articles feel "too clean" or losing important information.

### 12.1 Guardrail Categories

```python
class AntiSterilityGuardrails:
    """Prevent over-filtering that removes legitimate content"""

    def check_guardrails(self, span: DetectionInstance, context: ArticleContext) -> GuardrailResult:
        """Check if span should be exempted from removal"""

        exemptions = []

        # A. Legitimate Warnings
        if self._is_legitimate_warning(span, context):
            exemptions.append(GuardrailExemption(
                type="legitimate_warning",
                reason="Public safety warning with source + magnitude + timeframe"
            ))

        # B. Genuine Uncertainty
        if self._is_genuine_uncertainty(span, context):
            exemptions.append(GuardrailExemption(
                type="genuine_uncertainty",
                reason="Epistemic uncertainty is information, not manipulation"
            ))

        # C. Moral Language in Quotes
        if self._is_quoted_opinion(span, context):
            exemptions.append(GuardrailExemption(
                type="quoted_opinion",
                reason="Direct quote expressing opinion - preserve verbatim"
            ))

        # D. Material Conflict
        if self._is_material_conflict(span, context):
            exemptions.append(GuardrailExemption(
                type="material_conflict",
                reason="Real disagreement/tradeoff - remove inflation, not conflict"
            ))

        # E. Human Stakes
        if self._is_human_stakes(span, context):
            exemptions.append(GuardrailExemption(
                type="human_stakes",
                reason="Factual human impact - preserve stakes, remove steering"
            ))

        # F. Accountability/Agency
        if self._is_accountability(span, context):
            exemptions.append(GuardrailExemption(
                type="accountability",
                reason="Clear actor/responsibility - don't blur agency"
            ))

        # G. Asymmetric Reality
        if self._is_asymmetric_reality(span, context):
            exemptions.append(GuardrailExemption(
                type="asymmetric_reality",
                reason="Evidence genuinely asymmetric - don't force false balance"
            ))

        return GuardrailResult(
            should_preserve=len(exemptions) > 0,
            exemptions=exemptions
        )
```

### 12.2 Guardrail Decision Matrix

| Guardrail Type | When to Preserve | Example |
|----------------|------------------|---------|
| **Legitimate Warning** | Has source + magnitude + timeframe | "CDC urges immediate evacuation of Zone 3" |
| **Genuine Uncertainty** | Epistemic markers present | "The cause remains unknown" |
| **Quoted Opinion** | Inside direct quotes | Senator: "This is a disgrace" |
| **Material Conflict** | Real disagreement, not manufactured | "The two parties failed to reach agreement" |
| **Human Stakes** | Factual impact, not emotional steering | "12 families lost their homes" |
| **Accountability** | Clear actor attribution | "The CEO authorized the layoffs" |
| **Asymmetric Reality** | Evidence genuinely one-sided | "All 47 studies found..." |

---

## 13. Transparency UI Data (NTRL View Screen)

### 13.1 Data Flow to Frontend

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TRANSPARENCY DATA FLOW                                   │
└─────────────────────────────────────────────────────────────────────────────┘

 BACKEND                                      FRONTEND (ntrl-view screen)
 ───────                                      ─────────────────────────────

┌──────────────────┐                         ┌────────────────────────────┐
│ ManipulationSpan │                         │  HEADER SUMMARY            │
│                  │    GET /v1/stories/     │  "12 changes made"         │
│ • type_id        │    {id}/transparency    │  "3 urgency, 5 emotional,  │
│ • span_start     │  ─────────────────────▶ │   4 framing"               │
│ • span_end       │                         │                            │
│ • original_text  │                         │  [Severity breakdown]      │
│ • rewritten_text │                         │  ████░░░░ 3 high           │
│ • action         │                         │  ██████░░ 6 medium         │
│ • severity       │                         │  ███░░░░░ 3 low            │
│ • rationale      │                         └────────────────────────────┘
└──────────────────┘
         │                                   ┌────────────────────────────┐
         │                                   │  INTERACTIVE DIFF VIEW     │
         │                                   │                            │
         ▼                                   │  "BREAKING: Senator ████   │
┌──────────────────┐                         │   slams critics in ████    │
│ TransparencyPkg  │                         │   devastating attack"      │
│                  │                         │           ▼                │
│ • changes[]      │                         │  "Senator criticized       │
│ • summary_stats  │                         │   critics in statement"    │
│ • epistemic_flags│                         │                            │
│ • validation     │                         │  [Tap span for details]    │
└──────────────────┘                         └────────────────────────────┘

                                             ┌────────────────────────────┐
                                             │  SPAN DETAIL POPOVER       │
                                             │                            │
                                             │  Type: B.2.2 Rage verbs    │
                                             │  Category: Emotional       │
                                             │  Severity: 4/5             │
                                             │  Confidence: 92%           │
                                             │                            │
                                             │  Original: "slams"         │
                                             │  Changed to: "criticized"  │
                                             │                            │
                                             │  Why: Rage verbs inflate   │
                                             │  conflict beyond facts     │
                                             └────────────────────────────┘
```

### 13.2 API Response Schema

```python
# GET /v1/stories/{id}/transparency

class TransparencyResponse(BaseModel):
    """Full transparency data for ntrl-view screen"""

    # Summary for header
    summary: TransparencySummary

    # Original vs neutralized text with highlights
    original_text: str
    neutralized_text: str

    # All changes with positions for highlighting
    changes: list[ChangeDetail]

    # Risk indicators
    epistemic_flags: list[EpistemicFlag]

    # Validation status
    validation: ValidationSummary

class TransparencySummary(BaseModel):
    total_changes: int
    by_category: dict[str, int]  # {"A": 3, "B": 5, "C": 2, "D": 4}
    by_severity: dict[int, int]  # {1: 2, 2: 3, 3: 4, 4: 2, 5: 1}
    manipulation_density: float  # changes per 100 words

class ChangeDetail(BaseModel):
    """Single change for UI rendering"""
    id: str

    # Taxonomy info for display
    type_id: str              # "B.2.2"
    category_name: str        # "Emotional & Affective"
    type_name: str            # "Rage verbs"

    # Position in original text (for highlighting)
    original_start: int
    original_end: int
    original_text: str

    # Position in neutralized text (for highlighting)
    neutral_start: int | None  # None if removed
    neutral_end: int | None
    neutral_text: str | None

    # Change details
    action: str               # "removed" | "replaced" | "rewritten"
    severity: int             # 1-5
    confidence: float         # 0-1
    rationale: str            # Human-readable explanation

class EpistemicFlag(BaseModel):
    """Warning about article quality"""
    flag_type: str            # "anonymous_source_heavy" | "missing_baseline" | etc.
    description: str          # "5+ anonymous sources cited"
    severity: str             # "info" | "warning" | "critical"
```

### 13.3 Severity Color Coding

```typescript
const SEVERITY_COLORS = {
  1: { bg: '#E8F5E9', text: '#2E7D32' },  // Green - mild
  2: { bg: '#FFF3E0', text: '#E65100' },  // Orange - moderate
  3: { bg: '#FFF8E1', text: '#F57F17' },  // Yellow - significant
  4: { bg: '#FFEBEE', text: '#C62828' },  // Red - high
  5: { bg: '#FCE4EC', text: '#AD1457' },  // Magenta - severe
};

const CATEGORY_ICONS = {
  'A': '👁️',  // Attention & Engagement
  'B': '💢',  // Emotional & Affective
  'C': '🧠',  // Cognitive & Epistemic
  'D': '📝',  // Linguistic & Framing
  'E': '📰',  // Structural & Editorial
  'F': '💰',  // Incentive & Meta
};
```

---

## Related Documents

- **Canonical Taxonomy & Filter Product Spec**: `/docs/technical/NTRL_Canonical_Taxonomy_and_Filter_Product_Spec_v1.pdf`
- **Current Architecture**: `/code/ntrl-api/app/services/neutralizer.py`
- **Frontend Design System**: `/code/ntrl-app/src/theme/`
