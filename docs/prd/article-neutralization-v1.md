# PRD: Article Neutralization v1.0

**Status**: active
**Author**: Lawrence
**Created**: 2025-01-12
**Canon Version**: NTRL Neutralization Canon v1.0
**Content Spec Version**: NTRL Backend Content Spec v1.0

## Overview

Implement full article neutralization producing 6 distinct outputs per article. The NTRL filter is our IP and moat - it must be applied consistently across all outputs with transparency metadata proving the work.

## Problem Statement

### Current State
- Only produces `neutral_headline` (Feed Title) and `neutral_summary` (Feed Summary)
- No Article Detail outputs (Title, Brief, Full)
- No ntrl view transparency for full articles
- Structured fields (`what_happened`, etc.) don't match content spec

### Required State
- 6 distinct outputs per article, each serving a different cognitive purpose
- Full canon compliance across all outputs
- ntrl view metadata proving all transformations in Detail Full

## Required Outputs

| # | Output | Field Name | Purpose | Constraints |
|---|--------|------------|---------|-------------|
| 1 | Feed Title | `feed_title` | Fast scanning in feed | ≤6 words preferred, 12 max |
| 2 | Feed Summary | `feed_summary` | Lightweight context | 1-2 sentences, ≤3 lines |
| 3 | Detail Title | `detail_title` | Precise article headline | Neutral, complete, factual |
| 4 | Detail Brief | `detail_brief` | THE CORE PRODUCT | 3-5 paragraphs, prose, no headers |
| 5 | Detail Full | `detail_full` | Filtered full article | Preserves structure, removes manipulation |
| 6 | ntrl view | `transparency_spans` | Proof of work | Spans for all changes in Detail Full |

## Technical Architecture

### Generation Strategy: 3 Specialized Calls

```
CALL 1: Filter & Track
  Input:  Original article body
  Output: detail_full + transparency_spans
  Task:   Preserve structure, remove manipulation, track all changes

CALL 2: Synthesize
  Input:  Original article
  Output: detail_brief
  Task:   Create 3-5 paragraph prose (grounding→context→knowledge→uncertainty)

CALL 3: Compress
  Input:  Original article + detail_brief (for alignment check)
  Output: feed_title, feed_summary, detail_title
  Task:   Distill to constrained lengths
```

### Shared Filter DNA

All 3 calls share the same system prompt containing:
- NTRL Neutralization Canon rules (A1-D4)
- NTRL Content Spec constraints
- Manipulation patterns to remove

Task-specific user prompts define the output shape.

### Schema Changes

```python
class StoryNeutralized(Base):
    # Feed outputs
    feed_title: Text           # Renamed from neutral_headline
    feed_summary: Text         # Renamed from neutral_summary

    # Detail outputs (NEW)
    detail_title: Text
    detail_brief: Text         # 3-5 paragraphs, prose
    detail_full: Text          # Filtered full article

    # Remove deprecated fields
    # what_happened, why_it_matters, what_is_known, what_is_uncertain

    # Transparency (existing, expand coverage)
    spans: List[TransparencySpan]  # Now covers detail_full
```

## Grading Strategy

### Development Phase (LLM + Deterministic)

Use LLM scoring to iterate on prompts. When LLM identifies failure patterns, add rules to deterministic grader.

### Production Phase (Deterministic Only)

| Output | Deterministic Checks |
|--------|---------------------|
| feed_title | Word count ≤12, no questions, banned tokens, canon A-D |
| feed_summary | Sentence count 1-2, length check, completeness, canon A-D |
| detail_title | Neutrality checks, canon A-D |
| detail_brief | Paragraph count 3-5, no headers/bullets, canon A-D |
| detail_full | Canon A-D, structure preservation |
| transparency_spans | Spans exist, valid positions, valid reasons |

### Quality Threshold

All outputs must achieve average LLM quality score ≥ 8.5 during development before locking prompts.

## Implementation Phases

### Phase 1: Foundation (Stories 1.1-1.5)
- Integrate deterministic grader
- Create LLM quality scorer
- Store canon + content spec in repo
- Set up 10-article test corpus
- Schema migration for new fields

### Phase 2: Detail Full + ntrl view (Stories 2.1-2.4)
- THE IP - filtering while preserving structure
- System prompt with canon rules
- Filter prompt for full articles
- ntrl view span generation
- Iterate until quality ≥ 8.5

### Phase 3: Detail Brief (Stories 3.1-3.3)
- Synthesis with same filter DNA
- Brief-specific prompt
- Iterate until quality ≥ 8.5

### Phase 4: Feed Outputs (Stories 4.1-4.3)
- Compression with same filter DNA
- Feed-specific prompts
- Iterate until quality ≥ 8.5

### Phase 5: Integration (Stories 5.1-5.3)
- Wire 3 calls into pipeline
- End-to-end testing
- Performance optimization

## Acceptance Criteria

### Per Output
- [ ] Passes all deterministic grader rules
- [ ] LLM quality score ≥ 8.5 on test corpus
- [ ] No canon violations

### System Level
- [ ] All 6 outputs generated for each article
- [ ] ntrl view spans accurate for all detail_full transformations
- [ ] Pipeline completes in < 30 seconds per article
- [ ] Existing tests pass
- [ ] API returns all 6 outputs

## Dependencies

- Deterministic grader (from ChatGPT-generated code)
- NTRL Neutralization Canon v1.0
- NTRL Backend Content Spec v1.0
- 10-article test corpus

## Out of Scope

- User preferences / personalization
- Multi-language support
- Real-time streaming
- Brief-specific ntrl view (only Full gets transparency)

## Success Metrics

- All 6 outputs pass deterministic grader: 100%
- Average LLM quality score across corpus: ≥ 8.5
- No regressions on existing feed_title/feed_summary quality

## References

- `docs/canon/neutralization-canon-v1.md` - Canon rules
- `docs/canon/content-spec-v1.md` - Output specifications
- `app/services/grader.py` - Deterministic grader
- `app/data/grader_spec_v1.json` - Grader rule definitions
