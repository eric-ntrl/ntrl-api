# NTRL Filter v2 Pipeline

This document describes the two-phase NTRL Filter v2 architecture: detection (ntrl-scan) and rewriting (ntrl-fix).

## Pipeline Overview

```mermaid
flowchart TD
    subgraph Input
        ARTICLE[Article Body + Title]
    end

    subgraph Detection["Detection Phase (~400ms total, parallel)"]
        direction TB
        ARTICLE --> LEX["Lexical Detector<br/>~20ms"]
        ARTICLE --> STR["Structural Detector<br/>~80ms"]
        ARTICLE --> SEM["Semantic Detector<br/>~300ms"]
    end

    LEX --> MERGE[Merge & Dedupe<br/>overlap_threshold=0.5]
    STR --> MERGE
    SEM --> MERGE

    MERGE --> SCAN_RESULT[MergedScanResult<br/>DetectionInstance list]

    subgraph Fixing["Fix Phase (~800ms total, parallel)"]
        direction TB
        SCAN_RESULT --> FULL["DetailFullGenerator<br/>~300-400ms"]
        SCAN_RESULT --> BRIEF["DetailBriefGenerator<br/>~300-400ms"]
        SCAN_RESULT --> FEED["FeedOutputsGenerator<br/>~100-200ms"]
    end

    FULL --> VAL{RedLineValidator<br/>10 Invariance Checks}
    VAL -->|Pass| OUT[FixResult]
    VAL -->|Fail| RETRY[Retry with<br/>conservative settings]
    RETRY --> VAL
    RETRY -->|Max retries| FALLBACK[Fallback to<br/>original]
    FALLBACK --> OUT

    BRIEF --> OUT
    FEED --> OUT
```

## Detection Phase: ntrl-scan

Three complementary detectors run in parallel, each with different strengths:

### Detector Comparison

| Detector | Latency | Method | Strengths | Detects |
|----------|---------|--------|-----------|---------|
| **Lexical** | ~20ms | Regex patterns | Fast, predictable | Loaded language, sensationalism, obvious bias markers |
| **Structural** | ~80ms | spaCy NLP | Grammar-aware | Passive voice, rhetorical questions, attribution patterns |
| **Semantic** | ~300ms | LLM-based | Context-aware | Subtle manipulation, inference, connotation |

### Lexical Detector

```mermaid
flowchart LR
    TEXT[Input Text] --> TOKENIZE[Tokenize]
    TOKENIZE --> PATTERNS["Match 80+ patterns<br/>(quote-aware)"]
    PATTERNS --> EXEMPT{Inside Quote?}
    EXEMPT -->|Yes| SKIP[Skip/Annotate]
    EXEMPT -->|No| DETECT[Create DetectionInstance]
    SKIP --> RESULT[ScanResult]
    DETECT --> RESULT
```

**Key features:**
- Quote-aware: Patterns inside direct quotes are exempted
- Pattern library: 80+ regex patterns from manipulation taxonomy
- Categories: A (Attention), B (Emotional), D (Linguistic)

### Structural Detector

```mermaid
flowchart LR
    TEXT[Input Text] --> SPACY["Parse with spaCy<br/>(en_core_web_sm)"]
    SPACY --> POS[POS Tagging]
    SPACY --> DEP[Dependency Parse]
    POS --> PASSIVE[Detect Passive Voice]
    DEP --> RHETORICAL[Detect Rhetorical Questions]
    DEP --> ATTRIBUTION[Check Attribution Patterns]
    PASSIVE --> RESULT[ScanResult]
    RHETORICAL --> RESULT
    ATTRIBUTION --> RESULT
```

**Key features:**
- Grammar-based: Uses dependency parsing and POS tags
- Structural patterns: Passive voice, sentence structure
- Attribution analysis: Who-said-what patterns

### Semantic Detector

```mermaid
flowchart LR
    TEXT[Input Text] --> LLM["LLM Call<br/>(Claude/GPT-4)"]
    LLM --> PARSE[Parse JSON Response]
    PARSE --> VALIDATE[Validate Spans]
    VALIDATE --> RESULT[ScanResult]
```

**Semantic types detected (9 categories):**
1. Implied causation (unstated cause-effect)
2. Connotation manipulation (positive/negative framing)
3. Selective emphasis (cherry-picking facts)
4. False balance (both-sides-ism)
5. Loaded presupposition (hidden assumptions)
6. Appeal to emotion (fear, outrage, pity)
7. Vague attribution ("critics say")
8. Implied consensus ("everyone knows")
9. Strategic omission (missing key context)

### Merge & Dedupe

When spans from multiple detectors overlap:

```mermaid
flowchart TD
    SPANS[All Detected Spans] --> SORT[Sort by position]
    SORT --> CHECK{Overlap > 0.5?}
    CHECK -->|No| KEEP[Keep both spans]
    CHECK -->|Yes| SAME_TYPE{Same type_id?}
    SAME_TYPE -->|Yes| HIGHER_CONF[Keep higher confidence]
    SAME_TYPE -->|No| OVERLAP_90{Overlap > 0.9?}
    OVERLAP_90 -->|No| KEEP
    OVERLAP_90 -->|Yes| HIGHER_SEV[Keep higher severity<br/>add other as secondary]
    HIGHER_CONF --> MERGED[Merged Spans]
    KEEP --> MERGED
    HIGHER_SEV --> MERGED
```

**Segment multipliers** adjust severity based on article location:
- Title: 1.5x (highest impact)
- Deck: 1.3x
- Lede: 1.2x
- Body: 1.0x (baseline)
- Pullquote: 0.6x (quotes get lower weight)

## Fix Phase: ntrl-fix

Three generators run in parallel, each producing a different output:

### Generator Responsibilities

| Generator | Output Field | Purpose |
|-----------|--------------|---------|
| **DetailFullGenerator** | `detail_full` | Full neutralized article text |
| **DetailBriefGenerator** | `detail_brief` | Condensed summary for Brief tab |
| **FeedOutputsGenerator** | `feed_title`, `feed_summary` | Neutralized headline and deck |

```mermaid
flowchart TD
    subgraph Inputs
        BODY[original_body]
        TITLE[original_title]
        SPANS[Detected Spans]
    end

    subgraph DetailFull["DetailFullGenerator"]
        DF_PROMPT[Span-guided prompt:<br/>- Keep facts<br/>- Rewrite flagged spans<br/>- Preserve quotes]
        DF_LLM[LLM Call]
        DF_OUT[detail_full]
    end

    subgraph DetailBrief["DetailBriefGenerator"]
        DB_PROMPT[Synthesis prompt:<br/>- Extract key facts<br/>- 100-150 words<br/>- Neutral tone]
        DB_LLM[LLM Call]
        DB_OUT[detail_brief]
    end

    subgraph FeedOutputs["FeedOutputsGenerator"]
        FO_PROMPT[Title/summary prompt:<br/>- Short, neutral headline<br/>- Factual summary]
        FO_LLM[LLM Call]
        FO_OUT[feed_title, feed_summary]
    end

    BODY --> DF_PROMPT --> DF_LLM --> DF_OUT
    SPANS --> DF_PROMPT
    BODY --> DB_PROMPT --> DB_LLM --> DB_OUT
    SPANS --> DB_PROMPT
    BODY --> FO_PROMPT --> FO_LLM --> FO_OUT
    TITLE --> FO_PROMPT
```

### RedLine Validator

Validates `detail_full` against `original_body` using 10 invariance checks:

```mermaid
flowchart TD
    ORIGINAL[original_body] --> CHECK[10 Invariance Checks]
    REWRITTEN[detail_full] --> CHECK

    CHECK --> C1[1. Entity Invariance<br/>Names, orgs, places]
    CHECK --> C2[2. Number Invariance<br/>All numbers exact]
    CHECK --> C3[3. Date Invariance<br/>All dates preserved]
    CHECK --> C4[4. Attribution Invariance<br/>Who said what]
    CHECK --> C5[5. Modality Invariance<br/>Certainty not upgraded]
    CHECK --> C6[6. Causality Invariance<br/>Cause-effect unchanged]
    CHECK --> C7[7. Risk Invariance<br/>Warnings preserved]
    CHECK --> C8[8. Quote Integrity<br/>Quotes verbatim]
    CHECK --> C9[9. Scope Invariance<br/>Quantifiers unchanged]
    CHECK --> C10[10. Negation Integrity<br/>Negations preserved]

    C1 --> RESULT{All Passed?}
    C2 --> RESULT
    C3 --> RESULT
    C4 --> RESULT
    C5 --> RESULT
    C6 --> RESULT
    C7 --> RESULT
    C8 --> RESULT
    C9 --> RESULT
    C10 --> RESULT

    RESULT -->|Yes| PASS[Validation Passed]
    RESULT -->|No| FAIL[Retry or Fallback]
```

**Critical checks** (failures always block):
- Entity Invariance
- Number Invariance
- Quote Integrity
- Negation Integrity

**Non-strict mode** allows warnings for:
- Attribution Invariance
- Causality Invariance
- Scope Invariance

## Output: FixResult

```python
@dataclass
class FixResult:
    detail_full: str          # Full neutralized article
    detail_brief: str         # Brief summary
    feed_title: str           # Neutralized headline
    feed_summary: str         # Neutralized deck
    changes: list[ChangeRecord]  # What was changed and why
    validation: ValidationResult # Validation status
    processing_time_ms: float
```

## Performance Summary

| Phase | Component | Latency | Notes |
|-------|-----------|---------|-------|
| Detection | Lexical | ~20ms | Regex patterns |
| Detection | Structural | ~80ms | spaCy NLP |
| Detection | Semantic | ~300ms | LLM call |
| Detection | **Total** | **~400ms** | Parallel execution |
| Fix | DetailFull | ~300-400ms | LLM call |
| Fix | DetailBrief | ~300-400ms | LLM call |
| Fix | FeedOutputs | ~100-200ms | LLM call |
| Fix | **Total** | **~800ms** | Parallel execution |
| **Pipeline** | **Total** | **~1.2s** | Detection + Fix |

## Key Files

| Component | Location |
|-----------|----------|
| NTRLScanner | `app/services/ntrl_scan/scanner.py` |
| LexicalDetector | `app/services/ntrl_scan/lexical_detector.py` |
| StructuralDetector | `app/services/ntrl_scan/structural_detector.py` |
| SemanticDetector | `app/services/ntrl_scan/semantic_detector.py` |
| NTRLFixer | `app/services/ntrl_fix/fixer.py` |
| DetailFullGenerator | `app/services/ntrl_fix/detail_full_gen.py` |
| DetailBriefGenerator | `app/services/ntrl_fix/detail_brief_gen.py` |
| FeedOutputsGenerator | `app/services/ntrl_fix/feed_outputs_gen.py` |
| RedLineValidator | `app/services/ntrl_fix/validator.py` |
| Manipulation Taxonomy | `app/taxonomy.py` |
