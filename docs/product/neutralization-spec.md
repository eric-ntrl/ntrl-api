# NTRL Neutralization Specification v1.0

**Status:** CANONICAL / LOCKING DOCUMENT
**Last Updated:** January 2026
**Scope:** Defines what neutralization is, how it works, and what it produces. This is the single authoritative reference for the NTRL neutralization system.

---

## 1. Purpose & Scope

Neutralization is the core transformation that NTRL applies to news content. It removes language pressure --- urgency framing, emotional amplification, agenda signaling, clickbait, editorial voice --- while preserving meaning, uncertainty, and attribution.

Neutralization is applied to every article that enters the NTRL pipeline. The result is content that a reader can absorb without being pushed toward a reaction. The reader still gets the full picture: what happened, who said what, what is known, and what is not.

This specification consolidates two foundational documents:

- **Neutralization Canon v1.0** --- the rule set that defines correctness.
- **Content Generation Specification v1.0** --- the output formats and constraints.

Together they govern the entire neutralization surface: what the system must do, what it must never do, and what it produces.

---

## 2. Canon Rules

The canon is the rule set against which every neutralized article is evaluated. All rules must pass. One failure means the article does not ship.

### Priority Structure

Canon rules are organized into four priority tiers. When rules conflict, higher priority wins.

| Priority | Tier | Principle |
|----------|------|-----------|
| 1 (highest) | **A --- Meaning Preservation** | Never distort the truth to sound calmer. |
| 2 | **B --- Neutrality Enforcement** | Remove all language pressure. |
| 3 | **C --- Attribution & Agency Safety** | Never infer ownership, intent, or affiliation. |
| 4 (lowest) | **D --- Structural Constraints** | Grammar, formatting, and mechanical rules. |

A always overrides B. If removing emotional language would change the factual meaning, the meaning wins. B always overrides C. C always overrides D.

---

### A. Meaning Preservation

Meaning preservation is the highest-priority concern. No neutralization operation may alter what is factually true about the source material.

| Rule | Statement |
|------|-----------|
| **A1** | No new facts may be introduced. The neutralized output must not contain information that was not present in the source. |
| **A2** | Facts may not be removed if doing so changes meaning. A fact may be omitted only if its removal does not alter the reader's understanding of the article's claims. |
| **A3** | Factual scope and quantifiers must be preserved exactly. "Some" must not become "many." "Several states" must not become "states." |
| **A4** | Compound factual terms are atomic. Terms like "domestic abuse," "sex work," "climate change," and "mass shooting" are factual descriptors, not editorial language. They must not be decomposed, softened, or replaced. |
| **A5** | Epistemic certainty must be preserved exactly. If the source says "may cause," the output must not say "causes." If the source says "is linked to," the output must not say "leads to." Uncertainty is factual. |
| **A6** | Causal facts are not motives. A statement that X caused Y is a factual claim. It must not be rewritten as though it implies intent or motive unless the source explicitly states motive. |

---

### B. Neutrality Enforcement

Neutrality enforcement removes language that pressures the reader toward a particular emotional state, urgency level, or ideological position.

| Rule | Statement |
|------|-----------|
| **B1** | Remove urgency framing. Words and constructions that create artificial time pressure ("BREAKING," "JUST IN," "scrambling," "racing to") must be removed or replaced with neutral alternatives. |
| **B2** | Remove emotional amplification. Language designed to heighten emotional response ("shocking," "devastating," "slams," "tears apart") must be removed or replaced. |
| **B3** | Remove agenda or ideological signaling unless quoted and attributed. Phrases like "radical left," "extremist agenda," or "common-sense reform" must be removed unless they appear inside a direct quote with clear attribution. |
| **B4** | Remove conflict theater language. Framing that presents events as battles, wars, or showdowns ("Democrats and Republicans clash," "fired back," "in the crosshairs") must be replaced with factual descriptions of disagreement or opposition. |
| **B5** | Remove implied judgment. Language that signals approval or disapproval without stating it explicitly ("finally," "as expected," "predictably") must be removed. |

---

### C. Attribution & Agency Safety

Attribution and agency rules prevent the system from making inferences about people, organizations, or their relationships that are not explicitly stated in the source.

| Rule | Statement |
|------|-----------|
| **C1** | No inferred ownership or affiliation. The system must not describe a person as belonging to a group, party, or organization unless the source explicitly states the affiliation. |
| **C2** | No possessive constructions involving named individuals unless explicit. "Trump's economy" or "Biden's border crisis" must not appear unless the source contains an explicit claim of responsibility with attribution. |
| **C3** | No inferred intent or purpose. The system must not state why someone did something unless the source contains an explicit statement of intent, attributed to the actor or a credible source. |
| **C4** | Attribution must be preserved. If the source attributes a claim to a specific person or organization, the neutralized output must maintain that attribution. Removing attribution makes a claim appear to be established fact. |

---

### D. Structural & Mechanical Constraints

Structural rules govern grammar, formatting, and presentation.

| Rule | Statement |
|------|-----------|
| **D1** | Grammar must be intact. Every sentence must be grammatically complete and correct. Neutralization must not produce sentence fragments, dangling modifiers, or broken syntax. |
| **D2** | No ALL-CAPS emphasis except acronyms. Words in all capitals for emphasis ("BREAKING," "JUST IN," "EXPOSED") must be converted to standard case. Legitimate acronyms (NATO, FBI, GDP) are unaffected. |
| **D3** | Headlines must be 12 words or fewer. This applies to both feed_title and detail_title. |
| **D4** | Neutral tone throughout. The overall reading experience must feel calm, informational, and uninflected. No sentence should push the reader toward alarm, outrage, excitement, or dismissal. |

---

## 3. The Final Principle

> "If an output feels calmer but is less true, it fails. If it feels true but pushes the reader, it fails."

This is the governing test. Both conditions must be satisfied simultaneously. Calmness at the expense of truth is distortion. Truth at the expense of calm is manipulation. Neither is acceptable.

Pass/fail is binary. All canon rules must pass. One failure means the article does not ship.

---

## 4. Content Output Specifications

Every neutralized article produces six outputs. Each has its own constraints and purpose.

### 4.1 Feed Title (`feed_title`)

The title shown in the main feed. Optimized for scannability.

| Constraint | Value |
|------------|-------|
| Preferred length | 6 words or fewer |
| Hard cap | 12 words |
| Display limit | Must fit within 2 lines; no truncation mid-thought |
| Tone | Factual, neutral, descriptive |
| Prohibited | Emotional language, urgency words, clickbait, questions, teasers, ALL-CAPS emphasis |

### 4.2 Feed Summary (`feed_summary`)

The short description shown below the feed title.

| Constraint | Value |
|------------|-------|
| Length | 1--2 complete sentences |
| Display limit | Must fully complete within 3 lines |
| Fallback rule | If 2 sentences cannot fit cleanly, generate a single shorter sentence |
| Tone | Neutral, informational |

### 4.3 Detail Title (`detail_title`)

The title shown on the article detail screen. May carry more specificity than the feed title.

| Constraint | Value |
|------------|-------|
| Length | Up to 12 words |
| Relationship to feed_title | Independent. Not auto-derived from feed_title. May be longer and more precise. |
| Tone | Factual, neutral |

### 4.4 Detail Brief (`detail_brief`)

The core NTRL product. A calm, self-contained explanation of the article written from scratch by the neutralization system.

| Constraint | Value |
|------------|-------|
| Length | 3--5 short paragraphs maximum |
| Structure | No section headers, no bullets, no dividers, no calls to action |
| Reading experience | Must read as a complete, calm explanation |
| Implicit flow | Grounding -> Context -> State of knowledge -> Uncertainty |
| Quotes | Only when the wording itself is the news. Must be short, embedded in prose, attributed, and non-emotional. |

The detail brief is not a summary. It is a rewrite that explains the situation to someone encountering it for the first time. It grounds the reader, provides context, states what is known, and acknowledges what is not.

### 4.5 Detail Full (`detail_full`)

The full article content with manipulative language removed.

| Constraint | Value |
|------------|-------|
| Scope | Full article --- all original structure, quotes, and factual detail preserved |
| Removed | Manipulative language, urgency inflation, editorial framing, publisher UI artifacts |
| Relationship to source | Structurally faithful to the original. Readers should recognize the article. |

### 4.6 NTRL View / Transparency Spans (`transparency_spans`)

A transparency layer that tracks every language transformation applied to the detail full output.

| Constraint | Value |
|------------|-------|
| Scope | Applies to `detail_full` only. The brief is not redlined. |
| Purpose | Shows the reader exactly what was changed and why |
| Data | Character-level span positions, original text, replacement text, category, action |

---

## 5. How Neutralization Works

### 5.1 Processing Modes

The system uses two approaches to neutralization, with an automatic fallback chain.

**Primary: Synthesis Mode**
The LLM rewrites the full article neutrally. Input is the source article text. Output is plain text (not JSON). This produces the cleanest results because the LLM can restructure sentences naturally rather than performing word-level surgery.

**Secondary: JSON-Based Filter Prompt**
The LLM identifies manipulative phrases and returns structured JSON with replacement suggestions and span tracking data. This mode attempts to preserve the original text as closely as possible while tracking transformations for the transparency layer.

**Fallback Chain:**
1. Attempt JSON-based filter prompt.
2. If filtering fails (garbled output, broken JSON, excessive span count), fall back to synthesis prompt with pattern-based span detection.
3. If synthesis also fails, the article is marked as failed and excluded from the user-facing feed.

### 5.2 Why Synthesis Exists

LLMs are unreliable at character counting and positional editing. Removing individual words in-place frequently breaks grammar, produces awkward phrasing, or creates factual distortion. Synthesis --- rewriting the article as a whole --- avoids these failure modes. The tradeoff is that span tracking must be reconstructed after the fact rather than captured during transformation.

### 5.3 Editorial Content Handling

A `ContentTypeClassifier` analyzes each article for editorial signals. If three or more editorial signals are detected, the system routes directly to full synthesis mode. Editorial content (opinion columns, analysis pieces, commentary) contains manipulation distributed throughout the text rather than concentrated in isolated phrases, making the filter approach ineffective.

Additionally, if the filter approach produces more than 15 spans, the system switches to editorial synthesis as a fallback. High span counts indicate pervasive editorial language that is better handled by full rewrite.

---

## 6. Span Detection & Transparency

### 6.1 The Span Detection Pipeline

Transparency spans are generated through a multi-step pipeline:

1. **LLM Analysis:** The LLM analyzes the article and returns `{"phrases": [...]}` containing the manipulative phrases it identified.
2. **Position Mapping:** `find_phrase_positions()` maps each phrase string to its character-level start and end positions in the original article body.
3. **Quote Filtering:** `filter_spans_in_quotes()` removes any phrases that fall inside quoted speech. Quoted language is attributed to the speaker, not the publisher, and is therefore exempt from neutralization per rule B3.
4. **False Positive Filtering:** `filter_false_positives()` removes known false positive phrases that the LLM tends to flag incorrectly.
5. **Result:** A set of spans with accurate character positions, suitable for UI highlighting in the NTRL View.

### 6.2 Quote Handling

Quote filtering must account for:

- Straight quotes (`"`, `'`)
- Curly/smart quotes (Unicode `\u201c`, `\u201d`, `\u2018`, `\u2019`)
- Contractions within quotes (`won't`, `it's`, `shouldn't`) --- these must not break quote boundary detection

### 6.3 The 14 Manipulation Categories

Every detected span is classified into one of 14 manipulation categories:

| # | Category | Examples |
|---|----------|----------|
| 1 | **Urgency Inflation** | BREAKING, JUST IN, scrambling |
| 2 | **Emotional Triggers** | shocking, devastating, slams |
| 3 | **Clickbait** | You won't believe, Here's what happened |
| 4 | **Selling / Hype** | revolutionary, game-changer |
| 5 | **Agenda Signaling** | radical left, extremist |
| 6 | **Loaded Verbs** | slammed, blasted, admits, claims |
| 7 | **Urgency Inflation (Subtle)** | Act now, Before it's too late |
| 8 | **Agenda Framing** | "the crisis at the border" |
| 9 | **Sports / Event Hype** | brilliant, blockbuster, massive |
| 10 | **Loaded Personal Descriptors** | handsome, menacing |
| 11 | **Hyperbolic Adjectives** | punishing, "of the year" |
| 12 | **Loaded Idioms** | came under fire, in the crosshairs |
| 13 | **Entertainment / Celebrity Hype** | romantic escape, A-list pair |
| 14 | **Editorial Voice** | we're glad, as it should, Border Czar, lunatic |

### 6.4 Span Reason Enum

In the data model, the 14 categories are mapped to a reduced set of `SpanReason` values:

- `clickbait`
- `urgency_inflation`
- `emotional_trigger`
- `selling`
- `agenda_signaling`
- `rhetorical_framing`
- `editorial_voice`

### 6.5 Span Action Enum

Each span records the action taken:

- `removed` --- the phrase was deleted entirely
- `replaced` --- the phrase was substituted with a neutral alternative
- `softened` --- the phrase was moderated in intensity

---

## 7. Accuracy Metrics & Quality

### 7.1 Current Performance (gpt-4o-mini, January 2026)

| Metric | Measured | Target | Status |
|--------|----------|--------|--------|
| Precision | 96.43% | 80% | Exceeded |
| Recall | 77.14% | 85% | Approaching |
| F1 Score | 85.71% | 75% | Exceeded |

**Precision** measures how often the system is correct when it flags something. At 96.43%, nearly every flagged phrase is genuinely manipulative.

**Recall** measures how many manipulative phrases the system catches. At 77.14%, approximately one in four manipulative phrases is missed. This is a known gap and an active area of improvement.

**F1 Score** is the harmonic mean of precision and recall. At 85.71%, overall detection quality exceeds the target.

### 7.2 Quality Philosophy

NTRL prioritizes precision over recall. It is worse to falsely flag neutral language as manipulative (eroding reader trust in the transparency layer) than to miss a manipulative phrase (leaving some pressure in the text). The synthesis mode compensates for recall gaps by rewriting the full article, even when individual spans are missed by detection.

---

## 8. What Neutralization Is NOT

Neutralization is a specific, bounded operation. It is important to define its boundaries clearly to prevent scope creep and misapplication.

**Neutralization is not fact-checking.**
The system does not verify whether claims in the source article are true. If the source says "the unemployment rate fell to 3.2%," neutralization preserves that claim regardless of whether 3.2% is accurate. Fact-checking is a separate concern with different methods, infrastructure, and liability.

**Neutralization is not opinion classification.**
The system does not label articles as "left-leaning," "right-leaning," "centrist," or any other political classification. It removes manipulative language from all sources regardless of political orientation. An article from any outlet receives the same treatment.

**Neutralization is not sentiment scoring.**
The system does not assign a positivity or negativity score to articles. Some articles are about negative events (disasters, deaths, economic downturns). Neutralization does not make negative events sound positive. It removes the language that amplifies emotional response beyond what the facts warrant.

**Neutralization is not viewpoint balancing.**
The system does not inject "the other side" into an article. If an article quotes only one party in a dispute, neutralization does not add quotes from the opposing party. That would violate rule A1 (no new facts). Neutralization works within the boundaries of the source material.

**Neutralization is not censorship.**
The system does not remove facts, claims, or topics. It removes the linguistic packaging --- the urgency, the emotional loading, the editorial voice --- that shapes how a reader processes those facts.

---

## 9. Implementation Notes

### 9.1 Neutralization Status Tracking

Every article's neutralization attempt is tracked with one of the following statuses:

| Status | Meaning |
|--------|---------|
| `success` | Neutralization completed and passed all checks. Article is eligible for the feed. |
| `failed_llm` | The LLM call failed (timeout, rate limit, malformed response). |
| `failed_garbled` | The LLM returned output that could not be parsed or was incoherent. |
| `failed_audit` | The neutralized output failed a canon rule during post-processing audit. |
| `skipped` | The article was not submitted for neutralization (e.g., duplicate, insufficient content). |

### 9.2 Failure Handling

- Failed articles are stored in the database with their failure status and reason.
- Failed articles are never shown to users.
- The system does not silently fall back to unneutralized content. If neutralization fails, the article is excluded.

### 9.3 Clean Articles

When the LLM returns an empty array (`[]`) for detected phrases, this means the article is clean --- it contains no manipulative language. This is a valid result, not an error. The article proceeds with zero spans.

### 9.4 MockNeutralizerProvider

A `MockNeutralizerProvider` exists in the codebase for testing purposes only. It produces low-quality output (~5% precision) and must never be used as a production fallback. It exists to enable integration testing of the pipeline without incurring LLM costs.

---

## 10. Before & After Examples

These examples illustrate the transformation that neutralization produces.

### Example 1: Urgency Inflation + Selling/Hype

**Before:**
> AI startup SHAKES UP the industry with game-changing model

**After (NTRL):**
> AI startup releases a new model with performance improvements

**What changed:** ALL-CAPS emphasis removed (D2). "SHAKES UP" replaced with factual verb (B2). "Game-changing" removed as hype language (B2). Factual content preserved: a startup released a model (A1).

### Example 2: Emotional Triggers + Urgency Inflation

**Before:**
> Markets PANIC as stocks plunge amid fears of collapse

**After (NTRL):**
> Stocks decline amid investor concern over economic indicators

**What changed:** "PANIC" removed as emotional amplification (B2, D2). "Plunge" softened to "decline" (B2). "Fears of collapse" replaced with "concern over economic indicators" --- preserving the directional sentiment (concern exists) while removing catastrophic framing (A5, B2).

### Example 3: Clickbait + Emotional Triggers

**Before:**
> SHOCKING study changes everything you know about health

**After (NTRL):**
> Study identifies correlation; researchers note limitations

**What changed:** "SHOCKING" removed (B2, D2). "Changes everything you know" removed as clickbait (B1). "About health" was vague in the original. The NTRL version replaces the hype with what the study actually found --- a correlation --- and includes the researchers' own caveats (A5). Epistemic certainty is preserved: a correlation is not a cause.

---

## 11. Versioning & Change Process

### Current Version

This document is **Neutralization Specification v1.0**, consolidating the Neutralization Canon v1.0 and Content Generation Specification v1.0 into a single reference.

### Change Policy

This is a locking document. Changes to canon rules (Sections 2--3) require:

1. A written proposal specifying the rule change and its rationale.
2. Review of impact on existing neutralized content.
3. Explicit approval before the change is merged.

Changes to implementation details (Sections 5--6, 9) may be updated as the system evolves, but must remain consistent with the canon rules. Implementation changes that would violate a canon rule require a canon amendment first.

Changes to content output specifications (Section 4) require review for downstream impact on the app UI and data model.

### Document History

| Version | Date | Change |
|---------|------|--------|
| 1.0 | January 2026 | Initial consolidated specification. Merges Neutralization Canon v1.0 and Content Generation Specification v1.0. Adds implementation details reflecting current system state. |
