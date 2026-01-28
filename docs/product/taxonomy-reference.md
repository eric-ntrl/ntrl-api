# NTRL Content Taxonomy Reference

This document is the canonical reference for every taxonomy, enum, and mapping used across the NTRL platform. It covers manipulation detection categories, span classification, content domains, feed categories, and the full pipeline that connects them.

---

## Table of Contents

1. [Manipulation Detection: 14 Categories](#1-manipulation-detection-14-categories)
2. [SpanReason Enum (7 Values)](#2-spanreason-enum-7-values)
3. [SpanAction Enum](#3-spanaction-enum)
4. [Category Cascade: 14 Detection → 7 SpanReason → 5 Highlight Colors](#4-category-cascade-14-detection--7-spanreason--5-highlight-colors)
5. [Category-Specific Highlight Colors (Frontend)](#5-category-specific-highlight-colors-frontend)
6. [115 Manipulation Types (NTRL Filter v2)](#6-115-manipulation-types-ntrl-filter-v2)
7. [20 Internal Domains](#7-20-internal-domains)
8. [10 User-Facing Feed Categories](#8-10-user-facing-feed-categories)
9. [Domain to Feed Category Mapping](#9-domain-to-feed-category-mapping)
10. [Classification Pipeline](#10-classification-pipeline)
11. [False Positive Handling](#11-false-positive-handling)

---

## 1. Manipulation Detection: 14 Categories

These categories are used in the span detection prompt to identify manipulative language in article text. The LLM is instructed to tag each detected span with one of these categories.

| # | Category | Examples |
|---|----------|----------|
| 1 | URGENCY INFLATION | BREAKING, JUST IN, scrambling |
| 2 | EMOTIONAL TRIGGERS | shocking, devastating, slams |
| 3 | CLICKBAIT | You won't believe, Here's what happened |
| 4 | SELLING/HYPE | revolutionary, game-changer |
| 5 | AGENDA SIGNALING | radical left, extremist |
| 6 | LOADED VERBS | slammed, blasted, admits, claims |
| 7 | URGENCY INFLATION (subtle) | Act now, Before it's too late |
| 8 | AGENDA FRAMING | "the crisis at the border" |
| 9 | SPORTS/EVENT HYPE | brilliant, blockbuster, massive, beautiful (events) |
| 10 | LOADED PERSONAL DESCRIPTORS | handsome, unfriendly face, menacing |
| 11 | HYPERBOLIC ADJECTIVES | punishing, soaked in blood, "of the year" |
| 12 | LOADED IDIOMS | came under fire, in the crosshairs, took aim at |
| 13 | ENTERTAINMENT/CELEBRITY HYPE | romantic escape, whirlwind romance, A-list pair |
| 14 | EDITORIAL VOICE | we're glad, as it should, Border Czar, lunatic |

**History:**
- Categories 1--8 are the original detection categories.
- Categories 9--12 added January 2026 to improve detection of sports hyperbole, personal descriptors, adjective inflation, and idiomatic loaded language.
- Categories 13--14 added January 2026 for tabloid/celebrity hype and editorial voice detection.

---

## 2. SpanReason Enum (7 Values)

The 14 detection categories collapse into 7 `SpanReason` enum values. These are the values stored on each `TransparencySpan` and surfaced to the frontend.

| SpanReason Value | Source Detection Categories |
|---|---|
| `clickbait` | Category 3 |
| `urgency_inflation` | Categories 1, 7 |
| `emotional_trigger` | Categories 2, 9, 10, 11 |
| `selling` | Category 4 |
| `agenda_signaling` | Categories 5, 8 |
| `rhetorical_framing` | Categories 6, 12 |
| `editorial_voice` | Category 14 |

**Note:** Category 13 (ENTERTAINMENT/CELEBRITY HYPE) maps contextually -- typically to `selling` or `emotional_trigger` depending on the specific span.

---

## 3. SpanAction Enum

Each manipulative span includes an action describing what the neutralization process did to it.

| SpanAction Value | Description |
|---|---|
| `removed` | Manipulative text removed entirely |
| `replaced` | Manipulative text replaced with a neutral equivalent |
| `softened` | Manipulative language toned down (reduced intensity) |

---

## 4. Category Cascade: 14 Detection → 7 SpanReason → 5 Highlight Colors

The full pipeline from detection to rendering follows a two-stage reduction:

```
14 Detection Categories
        |
        v  (many-to-one mapping)
7 SpanReason Enum Values
        |
        v  (many-to-one mapping)
5 Highlight Color Groups
```

**Stage 1: Detection → SpanReason**

```
URGENCY INFLATION (1) ────────────┐
URGENCY INFLATION, subtle (7) ────┴──► urgency_inflation

EMOTIONAL TRIGGERS (2) ───────────┐
SPORTS/EVENT HYPE (9) ────────────┤
LOADED PERSONAL DESCRIPTORS (10) ─┤
HYPERBOLIC ADJECTIVES (11) ───────┴──► emotional_trigger

CLICKBAIT (3) ────────────────────────► clickbait

SELLING/HYPE (4) ─────────────────────► selling

AGENDA SIGNALING (5) ─────────────┐
AGENDA FRAMING (8) ───────────────┴──► agenda_signaling

LOADED VERBS (6) ─────────────────┐
LOADED IDIOMS (12) ───────────────┴──► rhetorical_framing

EDITORIAL VOICE (14) ─────────────────► editorial_voice
```

**Stage 2: SpanReason → Highlight Color**

```
urgency_inflation ─────────────────────► Dusty Rose
emotional_trigger ─────────────────────► Slate Blue
editorial_voice ───────────────────┐
agenda_signaling ──────────────────┴───► Lavender
clickbait ─────────────────────────┐
selling ───────────────────────────┴───► Amber/Tan
rhetorical_framing (+ any default) ───► Gold
```

---

## 5. Category-Specific Highlight Colors (Frontend)

These colors are used by the frontend to render highlighted spans in the transparency view.

| SpanReason(s) | Color Name | Light Mode RGBA |
|---|---|---|
| `urgency_inflation` | Dusty Rose | `rgba(200, 120, 120, 0.35)` |
| `emotional_trigger` | Slate Blue | `rgba(130, 160, 200, 0.35)` |
| `editorial_voice`, `agenda_signaling` | Lavender | `rgba(160, 130, 180, 0.35)` |
| `clickbait`, `selling` | Amber/Tan | `rgba(200, 160, 100, 0.35)` |
| Default (`rhetorical_framing`, etc.) | Gold | `rgba(255, 200, 50, 0.50)` |

**Note:** The default color (Gold) applies to `rhetorical_framing` and any span reason that does not have a specific color assignment. The Gold default uses a higher alpha (0.50) for visibility.

---

## 6. 115 Manipulation Types (NTRL Filter v2)

The v2 taxonomy (`taxonomy.py`) defines 115 detailed manipulation types in a hierarchical system. Type IDs follow the format `"A.1.1"`, `"B.2.3"`, etc.

This taxonomy is used by `ManipulationSpan` for rich, granular analysis. It is **separate** from the 14-category prompt used for `TransparencySpan` detection. The two systems serve different purposes:

| System | Used By | Granularity | Purpose |
|---|---|---|---|
| 14 Detection Categories | TransparencySpan | Coarse (14 → 7) | Real-time span detection and user-facing highlights |
| 115 Manipulation Types | ManipulationSpan | Fine (115 types) | Detailed analysis, auditing, and research |

---

## 7. 20 Internal Domains

These domains are used for editorial taxonomy and routing. They are system-only and never displayed directly to users. Populated by the CLASSIFY pipeline stage.

| # | Domain Key | Description |
|---|---|---|
| 1 | `global_affairs` | International relations, diplomacy, foreign policy |
| 2 | `governance_politics` | Government, elections, political parties, legislation |
| 3 | `law_justice` | Courts, legal proceedings, constitutional law |
| 4 | `security_defense` | Military, national security, defense policy |
| 5 | `crime_public_safety` | Crime reporting, policing, public safety |
| 6 | `economy_macroeconomics` | GDP, inflation, trade, economic indicators |
| 7 | `finance_markets` | Stock markets, banking, investment |
| 8 | `business_industry` | Corporate news, industry trends, mergers |
| 9 | `labor_demographics` | Employment, labor market, population trends |
| 10 | `infrastructure_systems` | Transportation, utilities, public works |
| 11 | `energy` | Oil, gas, renewables, energy policy |
| 12 | `environment_climate` | Climate change, conservation, ecology |
| 13 | `science_research` | Scientific discoveries, research, academia |
| 14 | `health_medicine` | Public health, healthcare, medical research |
| 15 | `technology` | Tech industry, software, AI, hardware |
| 16 | `media_information` | Journalism, social media, information ecosystems |
| 17 | `sports_competition` | Professional and amateur sports, athletics |
| 18 | `society_culture` | Arts, religion, social movements, demographics |
| 19 | `lifestyle_personal` | Food, travel, personal finance, wellness |
| 20 | `incidents_disasters` | Natural disasters, accidents, emergencies |

---

## 8. 10 User-Facing Feed Categories

These are displayed to users in the app feed. The order is fixed.

| # | Feed Category | Key |
|---|---|---|
| 1 | World | `world` |
| 2 | U.S. | `us` |
| 3 | Local | `local` |
| 4 | Business | `business` |
| 5 | Technology | `technology` |
| 6 | Science | `science` |
| 7 | Health | `health` |
| 8 | Environment | `environment` |
| 9 | Sports | `sports` |
| 10 | Culture | `culture` |

---

## 9. Domain to Feed Category Mapping

### Direct Mappings (15 domains, geography-independent)

These 15 internal domains always map to the same feed category regardless of the article's geographic context.

| Internal Domain(s) | Feed Category |
|---|---|
| `economy_macroeconomics`, `finance_markets`, `business_industry`, `labor_demographics` | `business` |
| `technology` | `technology` |
| `science_research` | `science` |
| `health_medicine` | `health` |
| `energy`, `environment_climate` | `environment` |
| `sports_competition` | `sports` |
| `society_culture`, `lifestyle_personal`, `media_information` | `culture` |
| `infrastructure_systems` | `us` (default) |
| `global_affairs` | `world` |

### Geography-Dependent Mappings (5 domains)

These 5 domains resolve to `world`, `us`, or `local` based on the geography tag assigned during classification.

| Internal Domain | Feed Category (varies) |
|---|---|
| `governance_politics` | `us` / `local` / `world` |
| `law_justice` | `us` / `local` / `world` |
| `security_defense` | `us` / `local` / `world` |
| `crime_public_safety` | `us` / `local` / `world` |
| `incidents_disasters` | `us` / `local` / `world` |

Geography is determined by the `classification_tags.geography` field output by the LLM classification step. Typical values: `"us"`, `"local"`, `"international"` (mapped to `world`).

---

## 10. Classification Pipeline

The CLASSIFY stage assigns domain, feed category, and metadata to each article.

### Model Fallback Chain

| Priority | Model | Prompt | Notes |
|---|---|---|---|
| Primary | `gpt-4o-mini` | Full prompt (JSON mode) | Default path |
| Fallback 1 | `gpt-4o-mini` | Simplified prompt | Used on parse/validation failure |
| Fallback 2 | `gemini-2.0-flash` | Full prompt | Used when OpenAI is unavailable |
| Last Resort | Enhanced keyword classifier | N/A (rule-based) | Flagged as `classification_method="keyword_fallback"` |

### Classification Output Fields

Each classified article receives the following fields:

| Field | Type | Description |
|---|---|---|
| `domain` | `String(40)` | Internal domain (one of the 20 values above) |
| `feed_category` | `String(32)` | User-facing category (one of the 10 values above) |
| `classification_tags` | `JSONB` | Structured metadata (see below) |
| `classification_confidence` | `Float` | Confidence score, range 0.0--1.0 |
| `classification_model` | `String(64)` | Model used, e.g. `"gpt-4o-mini"` |
| `classification_method` | `String(20)` | `"llm"` or `"keyword_fallback"` |
| `classified_at` | `DateTime` | Timestamp of when classification was performed |

### classification_tags Structure

```json
{
  "geography": "us",
  "geography_detail": "California",
  "actors": ["Congress", "EPA"],
  "action_type": "legislative",
  "topic_keywords": ["climate", "regulation", "emissions"]
}
```

---

## 11. False Positive Handling

The detection system maintains a list of known false positive phrases that are filtered out before spans are created. These fall into several categories:

- **Professional terminology:** crisis management, public relations
- **Medical terms:** bowel cancer, and other clinical language
- **Literal usage:** phrases like "car slammed into wall" where the verb is used literally rather than figuratively
- **Technical language:** domain-specific terms that overlap with manipulation vocabulary but carry no manipulative intent in context

False positive filtering occurs post-detection to avoid suppressing the LLM's ability to identify genuinely manipulative uses of the same words in different contexts.
