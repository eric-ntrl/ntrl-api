# NTRL Backend Content Generation Specification v1.0

**Scope**: Feed + Article Detail (Title, Brief, Full)
**Audience**: Backend / ML / Content Processing
**Status**: Phase 1 - Authoritative Content Contract

## 1. Overview

NTRL intentionally generates multiple distinct content artifacts from a single ingested article.
These artifacts are **not variations of the same text**. Each serves a different cognitive purpose and must be generated independently.

## 2. Required Outputs Per Article

| # | Output | Field |
|---|--------|-------|
| 1 | Feed Title | `feed_title` |
| 2 | Feed Summary | `feed_summary` |
| 3 | Article Detail Title | `detail_title` |
| 4 | Article Detail Brief | `detail_brief` |
| 5 | Article Detail Full | `detail_full` |
| 6 | ntrl view metadata | `transparency_spans` |

## 3. Output Specifications

### 3.1 Feed Title

**Purpose**: Fast scanning and orientation in the feed.

| Constraint | Value |
|------------|-------|
| Length | ≤6 words preferred; 12 words maximum (hard cap) |
| UI | Must fit within 2 lines. Must not truncate mid-thought |
| Content | Factual, neutral, descriptive |
| Avoid | Emotional language, urgency, clickbait, questions, teasers |

### 3.2 Feed Summary

**Purpose**: Lightweight context without delivering full understanding.

| Constraint | Value |
|------------|-------|
| Length | 1-2 complete sentences |
| UI | Must fully complete within 3 lines. No truncation or ellipses |
| Fallback | If 2 sentences cannot fit cleanly, generate a single shorter sentence |

### 3.3 Article Detail Title

**Purpose**: Precise headline on article page.

| Constraint | Value |
|------------|-------|
| Length | May be longer and more precise than Feed Title |
| Content | Neutral, complete, factual |
| Avoid | Urgency framing, sensational language |
| Independence | Not auto-derived from Feed Title |

### 3.4 Article Detail Brief (Core NTRL Product)

**Purpose**: The reading experience. This is the product.

| Constraint | Value |
|------------|-------|
| Length | 3-5 short paragraphs maximum |
| Format | No section headers, bullets, dividers, or calls to action |
| Tone | Must read as a complete, calm explanation |
| Structure | Implicit flow: grounding → context → state of knowledge → uncertainty |

**Quotes in Brief**:
- Direct quotations allowed when the wording itself is the news
- Quotes must be: short, embedded in prose, immediately attributed, non-emotional

### 3.5 Article Detail Full (Filtered Article)

**Purpose**: The original article with manipulation removed.

| Constraint | Value |
|------------|-------|
| Preserve | Full article content, structure, quotes, factual detail |
| Remove | Manipulative language, urgency inflation, editorial framing, publisher UI artifacts |

### 3.6 ntrl view (Verification Layer)

**Purpose**: Proof of work - tracks and exposes all language transformations.

| Constraint | Value |
|------------|-------|
| Applies to | Detail Full only |
| Tracks | All language transformations and removals |
| Note | Brief content is not redlined |

## 4. Backend Line-Length Heuristics

1. Prefer short, declarative sentences over compound clauses
2. Avoid pushing key meaning to the final words of a sentence
3. Assume ~35-40 characters per line on mobile when estimating fit
4. Fail gracefully by shortening content rather than truncating

## 5. Backend Validation Checklist

- [ ] Are Feed Titles ≤12 words and ≤2 lines?
- [ ] Do Feed Summaries fully complete within 3 lines?
- [ ] Is the Article Detail Brief 3-5 paragraphs with no headers or bullets?
- [ ] Are quotes used only when wording is essential?
- [ ] Is Full article content free of publisher cruft and emotional framing?
- [ ] Is ntrl view metadata available for all Full articles?
