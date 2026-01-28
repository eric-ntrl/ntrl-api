# NTRL Product Overview

**Version**: 1.0
**Last Updated**: January 28, 2026
**Status**: Phase 1 POC Complete, Staging Deployed

---

## 1. Introduction & Mission

NTRL is a mobile application for iOS and Android that strips manipulative language from news articles and presents them in a calm, deterministic feed. There are no engagement metrics, no personalization algorithms, and no urgency mechanics. NTRL exists to remove distortion from information.

**Brand Manifesto**

> Neutrality is not passive. It is disciplined refusal to distort. NTRL protects clarity, trust, and equanimity by presenting information as it is, not as someone wants it to feel.

NTRL is a filter for information. It removes unnecessary language -- clickbait, hype, emotional triggers, selling, pressure, and agenda-driven framing -- so people can read about what matters to them without being worked up. NTRL does not add perspective or interpretation. It simply strips information back to its core signal: what happened, what is known, what is uncertain, and why it matters.

The problem NTRL addresses is structural. Modern news is optimized for attention capture, not comprehension. Headlines are written to provoke clicks, not to inform. Language is loaded to trigger emotional responses, not to convey facts. NTRL intervenes at the language layer, surgically removing manipulation while preserving the informational substance of every article.

---

## 2. Core Principles

NTRL is governed by five non-negotiable principles that shape every product decision.

| # | Principle | Description |
|---|-----------|-------------|
| 1 | **No Engagement** | No likes, saves, shares, comments -- ever. The app has zero social or engagement mechanics. |
| 2 | **No Urgency** | No "BREAKING", "JUST IN", or "TRENDING" labels. Nothing in the product conveys artificial time pressure. |
| 3 | **Calm UX** | Subtle animations, muted colors, no flashy effects. The interface is designed to reduce cognitive load, not increase it. |
| 4 | **Transparency** | Always show what was changed and what was removed. Users can inspect every neutralization decision the system makes. |
| 5 | **Determinism** | Same content for all users. There is no personalization, no algorithmic feed ranking, and no A/B testing of content presentation. Every user sees the same article rendered the same way. |

---

## 3. How It Works -- The Neutralization Pipeline

Every article that enters NTRL passes through a four-stage pipeline before it reaches a reader.

### Stage 1: INGEST

Source articles are ingested from upstream publishers and stored in their original form in S3. The original text is preserved verbatim and never modified. This original body (`original_body`) serves as the ground truth for all downstream processing and is always available to the reader in the Ntrl tab.

### Stage 2: CLASSIFY

Each article is assigned to one or more of 20 internal domains (see Section 6) for system-level routing, and mapped to one of 10 user-facing feed categories for display. Classification is deterministic -- the same article always receives the same categorization.

### Stage 3: NEUTRALIZE

The neutralization engine processes the original article text to produce two outputs:

- **Detail Full** (`detail_full`): The complete article with all manipulative language surgically removed or replaced with neutral equivalents. The informational content is preserved; only the rhetorical packaging is stripped.
- **Transparency Spans** (`spans`): A structured record of every manipulation detected in the original text, including its position, the category of manipulation, and the reason for flagging. Spans reference character positions in `original_body`, not in `detail_full`.

The neutralization engine is pluggable. The primary neutralizer is OpenAI gpt-4o-mini, with Gemini as a fallback and Anthropic as an additional option. spaCy handles structural NLP detection upstream of the LLM layer.

### Stage 4: BRIEF ASSEMBLE

From the neutralized full article, a brief summary is synthesized:

- **Detail Brief** (`detail_brief`): A 3-5 paragraph prose summary of the article, written in neutral language with no headers or bullet points. This is the default reading experience.

Additionally, feed-level content is generated:

- **Feed Title** (`feed_title`): A neutral headline of 6 words preferred, 12 maximum.
- **Feed Summary** (`feed_summary`): 1-2 sentences, designed to fit within 3 lines on screen.

---

## 4. The Reading Experience

### App Screens

| Screen | Purpose |
|--------|---------|
| **TodayScreen** | Session-filtered articles. Displays the NTRL brand mark. |
| **SectionsScreen** | All category sections with articles organized by feed category. |
| **ArticleDetailScreen** | The primary reading view with Brief/Full/Ntrl tabs. |
| **ProfileScreen** | User content, topics, and navigation to Settings. |
| **SettingsScreen** | Text size, appearance mode, and account settings. |
| **SearchScreen** | Article search. |
| **SavedArticlesScreen** | User's saved articles. |
| **HistoryScreen** | Previously read articles. |
| **SourceTransparencyScreen** | Transparency information about article sources. |
| **AboutScreen** | Information about NTRL. |

### The 3-Tab Content Architecture

The ArticleDetailScreen presents each article through three view modes, rendered inline with no navigation transitions:

| Tab | Content Source | Component | Description |
|-----|---------------|-----------|-------------|
| **Brief** | `detail_brief` | `ArticleBrief` | LLM-synthesized summary displayed in serif typography. This is the default view and the fastest way to understand an article. |
| **Full** | `detail_full` | -- | The complete LLM-neutralized article displayed in serif typography. Every sentence from the original is preserved; only manipulative language has been removed or replaced. |
| **Ntrl** | `original_body` + `spans` | `NtrlContent` | The original article text with manipulative phrases highlighted inline using category-specific colors. This is the transparency view. |

The tab system is designed so that readers can move fluidly between "what happened" (Brief), "the full neutral story" (Full), and "what was changed" (Ntrl) without leaving the article.

---

## 5. Transparency & the Ntrl View

Transparency is not an afterthought in NTRL -- it is a core product feature. The Ntrl tab exists so that every reader can inspect exactly what the system detected and removed.

### The 4-View Content Architecture (Backend)

The backend maintains four distinct views of every article:

| View | UI Location | Content Source | Description |
|------|-------------|---------------|-------------|
| **Original** | Ntrl tab (highlights OFF) | `original_body` | The original text as published, retrieved from S3. Unmodified. |
| **Ntrl View** | Ntrl tab (highlights ON) | `original_body` + `spans` | The same original text with manipulative phrases highlighted using category-colored inline markers. |
| **Full** | Article Detail (Full tab) | `detail_full` | The LLM-neutralized full article. |
| **Brief** | Article Detail (Brief tab) | `detail_brief` | The LLM-synthesized short summary. |

### How Spans Work

Transparency spans are structured references to positions within `original_body`. Each span includes:

- **Start and end positions**: Character offsets in the original text.
- **Category**: Which of the 14 manipulation categories the phrase falls under.
- **Reason**: A human-readable explanation of why the phrase was flagged.

Spans reference positions in `original_body`, not in `detail_full`. The Ntrl tab renders the original text with category-colored inline highlights overlaid on the flagged phrases.

### Category-Specific Highlight Colors

Each manipulation category is rendered with a specific muted highlight color to provide visual differentiation without visual noise.

| Manipulation Type | Color Name | Light Mode Value |
|-------------------|------------|-----------------|
| Urgency Inflation | Dusty rose | `rgba(200, 120, 120, 0.35)` |
| Emotional Triggers | Slate blue | `rgba(130, 160, 200, 0.35)` |
| Editorial Voice, Agenda Signaling | Lavender | `rgba(160, 130, 180, 0.35)` |
| Clickbait, Selling/Hype | Amber/tan | `rgba(200, 160, 100, 0.35)` |
| Default (all others) | Gold | `rgba(255, 200, 50, 0.50)` |

---

## 6. Content Taxonomy

NTRL maintains three layers of content classification: manipulation categories (what the system detects and removes), internal domains (how the system organizes content), and feed categories (what the reader sees).

### 14 Manipulation Categories

These are the categories of manipulative language that the neutralization engine detects and flags in transparency spans.

| # | Category | Examples |
|---|----------|----------|
| 1 | **Urgency Inflation** | BREAKING, JUST IN, scrambling |
| 2 | **Emotional Triggers** | shocking, devastating, slams |
| 3 | **Clickbait** | You won't believe, Here's what happened |
| 4 | **Selling / Hype** | revolutionary, game-changer |
| 5 | **Agenda Signaling** | radical left, extremist |
| 6 | **Loaded Verbs** | slammed, blasted, admits, claims |
| 7 | **Urgency Inflation (subtle)** | Act now, Before it's too late |
| 8 | **Agenda Framing** | "the crisis at the border" |
| 9 | **Sports / Event Hype** | brilliant, blockbuster, massive |
| 10 | **Loaded Personal Descriptors** | handsome, menacing |
| 11 | **Hyperbolic Adjectives** | punishing, "of the year" |
| 12 | **Loaded Idioms** | came under fire, in the crosshairs |
| 13 | **Entertainment / Celebrity Hype** | romantic escape, A-list pair |
| 14 | **Editorial Voice** | we're glad, as it should, Border Czar |

### 20 Internal Domains (System-Only)

These domains are used internally for classification, routing, and analytics. They are not exposed to users.

| # | Domain Key | # | Domain Key |
|---|-----------|---|-----------|
| 1 | `global_affairs` | 11 | `energy` |
| 2 | `governance_politics` | 12 | `environment_climate` |
| 3 | `law_justice` | 13 | `science_research` |
| 4 | `security_defense` | 14 | `health_medicine` |
| 5 | `crime_public_safety` | 15 | `technology` |
| 6 | `economy_macroeconomics` | 16 | `media_information` |
| 7 | `finance_markets` | 17 | `sports_competition` |
| 8 | `business_industry` | 18 | `society_culture` |
| 9 | `labor_demographics` | 19 | `lifestyle_personal` |
| 10 | `infrastructure_systems` | 20 | `incidents_disasters` |

### 10 User-Facing Feed Categories

These are the categories visible to readers in the SectionsScreen and used for feed filtering.

| # | Category |
|---|----------|
| 1 | World |
| 2 | U.S. |
| 3 | Local |
| 4 | Business |
| 5 | Technology |
| 6 | Science |
| 7 | Health |
| 8 | Environment |
| 9 | Sports |
| 10 | Culture |

---

## 7. Content Outputs

Every article that passes through the NTRL pipeline produces six required outputs.

| # | Output | Field Key | Specification |
|---|--------|-----------|---------------|
| 1 | **Feed Title** | `feed_title` | Neutral headline. 6 words preferred, 12 maximum. |
| 2 | **Feed Summary** | `feed_summary` | 1-2 neutral sentences. Must fit within 3 lines on screen. |
| 3 | **Detail Title** | `detail_title` | Precise, neutral article headline for the detail view. |
| 4 | **Detail Brief** | `detail_brief` | 3-5 paragraphs of neutral prose. No headers, no bullet points. |
| 5 | **Detail Full** | `detail_full` | Complete article with all manipulative language removed. |
| 6 | **Transparency Spans** | `spans` | Structured records of what was changed, where, and why. |

### Before & After Examples

These examples illustrate the transformation from source headlines to NTRL feed titles.

| Original Headline | NTRL Feed Title |
|--------------------|----------------|
| AI startup SHAKES UP the industry with game-changing model | AI startup releases a new model with performance improvements |
| Markets PANIC as stocks plunge amid fears of collapse | Stocks decline amid investor concern over economic indicators |
| SHOCKING study changes everything you know about health | Study identifies correlation; researchers note limitations |
| Crime wave continues as city spirals out of control | Police report an increase in incidents compared to last year |

The pattern is consistent: remove urgency language, replace loaded verbs, eliminate hyperbole, and preserve the factual core of the information.

---

## 8. Design Philosophy

### Visual Target

The NTRL visual identity is anchored to a single reference feeling: **"A calm sunny morning with blue skies and coffee."**

This translates into a design system built around warmth, restraint, and readability.

### Design System Characteristics

- **Background**: Warm off-white, never harsh white.
- **Text**: Dark gray, never pure black.
- **Accents**: Muted tones that complement without competing for attention.
- **Dark mode**: Full dark mode support with equivalent calm tonality.

### Typography Scale

A defined typographic scale from 11px to 22px ensures consistent hierarchy across all screens. Article body text uses serif typography to evoke the reading experience of print journalism.

### Spacing System

| Token | Value (px) |
|-------|-----------|
| `xs` | 4 |
| `sm` | 8 |
| `md` | 12 |
| `lg` | 16 |
| `xl` | 20 |
| `xxl` | 24 |
| `xxxl` | 32 |

### UX Principles

- Animations are subtle and functional, never decorative.
- Transitions are smooth but fast. Nothing bounces, flashes, or draws unnecessary attention.
- The interface recedes. Content is the foreground; chrome is invisible.
- No badges, no notification dots, no unread counts. Nothing in the UI creates a sense of obligation.

---

## 9. What NTRL Does Not Do

Defining what NTRL is not is as important as defining what it is. The following are deliberate exclusions, not missing features.

### NTRL does not fact-check.

NTRL does not verify the truth of claims made in articles. If a source reports incorrect information using neutral language, NTRL will present that information as-is. NTRL operates at the language layer, not the truth layer. Fact-checking requires editorial judgment; NTRL is a filter, not an editor.

### NTRL does not classify opinions.

NTRL does not label articles as "opinion," "editorial," or "analysis." It does not distinguish between reporting and commentary at a genre level. It detects and removes manipulative language regardless of the article's genre or intent.

### NTRL does not balance viewpoints.

NTRL does not present "both sides" of any issue. It does not add context, counterarguments, or alternative perspectives. It does not curate for ideological balance. It processes each article independently, removing manipulation from whatever text it receives.

### NTRL does not personalize.

There is no recommendation engine, no "for you" feed, no reading history-based suggestions, and no algorithmic ranking. Every user sees the same content in the same order. Determinism is a core principle, not a limitation.

### NTRL does not create urgency.

There are no push notifications for breaking news, no "trending" sections, no time-based sorting that privileges recency over relevance. The feed is calm by design.

---

## 10. Tech Stack Overview

### Backend

| Component | Technology |
|-----------|-----------|
| Framework | FastAPI (Python 3.11) |
| Database | PostgreSQL |
| ORM | SQLAlchemy |
| Migrations | Alembic |
| Object Storage | Amazon S3 (original article bodies) |

### Frontend

| Component | Technology |
|-----------|-----------|
| Framework | React Native 0.81.5 with Expo 54 |
| Language | TypeScript 5.9 |
| Platforms | iOS, Android (mobile-only) |

### AI / NLP

| Component | Technology |
|-----------|-----------|
| Primary Neutralizer | OpenAI gpt-4o-mini |
| Fallback Neutralizer | Google Gemini |
| Additional Neutralizer | Anthropic Claude |
| Structural NLP | spaCy |

The neutralization engine is designed with a pluggable architecture. The LLM provider can be swapped without changing the pipeline logic, and multiple providers can be evaluated against the same input for quality comparison.

---

## 11. Business Model Overview

NTRL's business model evolves across three phases, each building on the assets created by the previous phase.

### Phase 1: Consumer Subscription App

- **Model**: Monthly subscription at $5-10/month.
- **Value proposition**: A calm, manipulation-free news reading experience.
- **Target users**: Readers who are fatigued by sensationalized news and want factual information without emotional manipulation.

### Phase 2: B2B API

- **Model**: License the neutralization engine to publishers as an API service.
- **Value proposition**: Publishers can offer a "neutral mode" for their own content, improving trust and reader retention.
- **Target customers**: News publishers, content aggregators, media companies.

### Phase 3: Platform Expansion

- **Model**: Extend neutralization beyond the NTRL app.
- **Products**: Browser extension for real-time neutralization of any web content, social media filtering tools.
- **Value proposition**: Bring the NTRL neutralization capability to wherever people consume information.

---

## 12. Current Status

**As of January 2026:**

- **Phase 1 POC**: Complete. The core neutralization pipeline is functional, producing all six required outputs per article across the full taxonomy of 14 manipulation categories.
- **Staging environment**: Deployed. The mobile app is running on staging with live article ingestion, neutralization, and rendering across all three content tabs.
- **Pipeline**: The four-stage pipeline (Ingest, Classify, Neutralize, Brief Assemble) is operational with the primary OpenAI neutralizer.
- **Mobile app**: The React Native application with Expo is functional on both iOS and Android, implementing the full screen architecture including TodayScreen, SectionsScreen, ArticleDetailScreen with 3-tab content system, ProfileScreen, SettingsScreen, and supporting screens.
- **Transparency system**: Span detection and category-colored highlighting are implemented in the Ntrl tab.

The immediate roadmap focuses on neutralization quality refinement, expanding source coverage, and preparing for consumer beta.

---

*This document is the canonical NTRL product specification. All product, engineering, and design decisions should reference and remain consistent with the definitions established here.*
