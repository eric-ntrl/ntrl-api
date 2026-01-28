# NTRL — Editorial Policy

> **Last Updated:** 2026-01-28
> **Version:** 1.0
> **Owner:** Eric Brown

This document defines NTRL's editorial approach: what our neutralization process is, what it is not, how we select and process content, and the commitments we make to our readers regarding transparency and integrity.

---

## 1. Purpose

NTRL exists to remove manipulative language from news so that readers can engage with factual information without emotional interference. Our editorial approach is grounded in a single principle: **people deserve to read the news without being manipulated by the language it is written in.**

We do not take sides. We do not curate narratives. We do not decide what matters. We remove the linguistic tools — clickbait, hype, emotional triggers, agenda framing — that are designed to tell you how to feel before you have had the chance to think.

This editorial policy governs every article that passes through the NTRL system.

---

## 2. What Neutralization Is

Neutralization is the systematic identification and removal of manipulative language from news articles while preserving all factual content, direct quotes, and journalistic substance.

NTRL's neutralization engine detects and addresses **14 categories of linguistic manipulation:**

1. **Clickbait & Sensationalism** — Headlines and language engineered to provoke clicks through shock, curiosity gaps, or exaggeration.
2. **Emotional Trigger Language** — Words and phrases designed to provoke fear, outrage, anxiety, or other strong emotional reactions.
3. **Hype & Exaggeration** — Superlatives, absolutist claims, and inflated language that overstates significance.
4. **Agenda Framing** — Language that frames information to favor a particular viewpoint, ideology, or narrative.
5. **Urgency Manufacturing** — Artificial urgency ("breaking," "just in," "developing") applied to non-urgent information.
6. **Loaded Descriptors** — Adjectives and characterizations that carry implicit judgment (e.g., "controversial," "embattled," "slammed").
7. **False Equivalence Language** — Framing that implies equal validity between unequal positions.
8. **Minimization & Dismissal** — Language that downplays the significance of events or claims.
9. **Appeal to Authority Framing** — Language that leverages unnamed or vague authority to add unearned weight.
10. **Speculative Presentation as Fact** — Presenting speculation, opinion, or prediction as established fact.
11. **Passive Obfuscation** — Use of passive voice or vague attribution to obscure responsibility.
12. **Tribal Signaling** — Language that signals in-group/out-group dynamics or partisan identity.
13. **Narrative Injection** — Editorializing or narrative framing inserted into what is presented as straight reporting.
14. **Anchoring & Priming** — Language positioned to set expectations or influence interpretation of subsequent information.

For each detection, the neutralization engine:
- Identifies the specific text containing manipulation.
- Classifies it by manipulation category.
- Generates a neutral replacement that preserves the factual content.
- Records the original text, replacement text, category, and reasoning for full transparency.

---

## 3. What Neutralization Is NOT

It is essential that readers, reviewers, and the public understand the boundaries of what NTRL does. Neutralization is **not** any of the following:

### 3.1 Not Fact-Checking
NTRL does not verify whether claims in articles are true or false. An article containing factual errors will have its manipulative language removed, but its inaccurate claims will remain. We address **how** things are said, not **whether** what is said is true.

### 3.2 Not Opinion Classification
NTRL does not label articles as "opinion," "analysis," or "straight news." We do not classify the intent or genre of a piece. We process the language uniformly.

### 3.3 Not Viewpoint Balancing
NTRL does not add opposing viewpoints, counterarguments, or alternative perspectives. We do not attempt to "balance" an article by supplementing it with information from other sources. We work within the text as published.

### 3.4 Not Bias Labeling
NTRL does not assign bias scores, political leanings, or reliability ratings to articles or sources. We do not tell readers whether a source is "left," "right," "center," or otherwise positioned.

### 3.5 Not Sentiment Scoring
NTRL does not score articles on a positivity/negativity scale or assign emotional valence. Our system identifies specific instances of manipulative language — it does not characterize the overall tone or sentiment of a piece.

---

## 4. The Canon Rules

NTRL's neutralization operates under a strict set of priority rules — the Neutralization Canon — that govern every transformation. These rules are applied in order of priority:

### Rule A: Preserve Facts Above All
No transformation may alter, omit, or misrepresent a factual claim present in the original text. If removing manipulative language risks distorting a fact, the original language is preserved. Facts are sacred.

### Rule B: Maintain Meaning and Context
Every transformation must preserve the original meaning and context of the passage. The reader of the neutralized version must come away with the same factual understanding as a reader of the original — minus the emotional manipulation.

### Rule C: Remove Manipulation, Not Substance
Neutralization targets the manipulative layer of language — the adjectives, framing devices, rhetorical techniques, and editorial insertions that color factual reporting. The journalistic substance underneath must remain intact.

### Rule D: Transparency Over Perfection
Every transformation is recorded and made visible. If there is doubt about whether a passage is manipulative, the system errs on the side of preservation and flags the passage for review. We prefer to under-neutralize rather than to silently alter meaning.

**Priority order:** A > B > C > D. In any conflict between rules, the higher-priority rule governs.

---

## 5. Source Selection Criteria

### 5.1 RSS Feed Sources

NTRL ingests content exclusively from public RSS feeds published by news organizations. Source selection is based on:

- **Public availability:** The RSS feed must be publicly accessible without authentication or special access.
- **Established editorial operation:** Sources must be recognized news organizations with professional editorial staff and published editorial standards.
- **Diversity of perspective:** The source set must include organizations across the ideological and geographic spectrum. NTRL does not favor sources aligned with any particular viewpoint.
- **Regular publication cadence:** Sources must publish regularly to contribute meaningfully to the feed.

### 5.2 No Editorial Filtering of Stories

NTRL does not editorially select which stories to include or exclude. All articles from configured RSS sources that meet technical ingestion criteria (parseable content, supported language, within length parameters) are processed and made available. The feed is a **complete, unfiltered representation** of what configured sources publish.

### 5.3 Source Addition and Removal

Sources may be added to expand coverage or diversity. Sources are removed only for technical reasons (feed becomes unavailable, format changes break ingestion) or if the organization ceases to meet the established editorial operation criterion. Sources are never removed because of the viewpoints they represent.

---

## 6. Transparency Commitment

### 6.1 The Ntrl View

Every article in NTRL includes a third tab — the Ntrl view — that provides full transparency into the neutralization process. This view displays:

- **Color-coded highlights** showing every passage that was modified.
- **The original text** that was replaced.
- **The neutralized replacement** that now appears.
- **The manipulation category** assigned to each detection.
- **The reasoning** behind each transformation.

No transformation is hidden. Readers can evaluate every decision the system made and form their own judgment about whether the neutralization was appropriate.

### 6.2 Source Attribution

Every article in the App clearly identifies:

- The original source publication.
- The original author, when available.
- The original publication date.
- A direct link to the original source article.

Readers are always one tap away from the unmodified original.

---

## 7. Content We Do Not Modify

The following elements are preserved exactly as they appear in the source article, without modification:

- **Direct quotes** — Quoted speech attributed to identified individuals is never altered. Quotes are presented exactly as published, even if they contain manipulative language, because they represent the words of the quoted person.
- **Proper nouns** — Names of people, organizations, places, legislation, products, and other proper nouns are never changed.
- **Factual claims** — Statements of fact (including disputed facts) are preserved as stated.
- **Numbers and statistics** — All quantitative data, dates, figures, percentages, and measurements are preserved exactly.
- **Statements of uncertainty** — When the original text appropriately conveys uncertainty ("may," "could," "according to," "alleged"), these qualifiers are preserved.
- **Technical and domain-specific terminology** — Specialized vocabulary appropriate to the subject matter is not simplified or replaced.

---

## 8. Algorithmic Transparency

### 8.1 Deterministic Feed

Every user of NTRL sees the same feed of articles. The feed is ordered by publication recency within each category. There is no personalization, no recommendation engine, and no algorithmic curation.

### 8.2 No Personalization

NTRL does not adjust content, ordering, or presentation based on:

- Individual reading history.
- Inferred interests or preferences.
- Demographics or location.
- Engagement patterns.
- Any user-specific signal.

Topic category selection (which of the 10 categories a user enables) is the only user-controlled filter, and it operates as a simple inclusion/exclusion — not a ranking signal.

### 8.3 No Engagement Optimization

NTRL does not employ any mechanism designed to increase time spent in the app, article consumption volume, or return frequency. There are:

- No push notifications engineered for re-engagement.
- No infinite scroll mechanics.
- No "recommended for you" suggestions.
- No streaks, badges, or gamification.
- No social proof indicators (trending, popular, most-read).
- No urgency cues designed to drive immediate action.

---

## 9. Human Oversight

### 9.1 Accuracy Testing

The neutralization engine is evaluated against a gold standard corpus — a set of articles with expert-annotated manipulation instances. This corpus is used to measure:

- **Precision:** Of the passages flagged as manipulative, what percentage are truly manipulative (avoiding false positives).
- **Recall:** Of the manipulative passages present, what percentage are detected (avoiding false negatives).
- **Meaning preservation:** Whether neutralized output preserves the factual meaning of the original.

### 9.2 Prompt Iteration

The prompts and instructions governing the AI neutralization model are iteratively refined based on accuracy testing, edge case analysis, and identified failure patterns. Changes to the neutralization prompt are versioned, tested against the gold standard corpus, and reviewed before deployment.

### 9.3 False Positive Filtering

The system includes mechanisms to reduce false positives — instances where non-manipulative language is incorrectly flagged and modified. False positive patterns identified through testing and review are addressed through prompt refinement and, where appropriate, explicit exclusion rules.

---

## 10. Known Limitations

We believe transparency requires honesty about what we cannot yet do well. The following limitations are known and actively being addressed:

### 10.1 Long-Form Content
Articles exceeding approximately 8,000 characters may experience reduced detection accuracy. The AI model's attention across very long texts is a known constraint. We are investigating chunking strategies and multi-pass approaches to improve coverage.

### 10.2 Recall Rate
Current recall — the percentage of manipulative passages that are correctly detected — is approximately 77%. This means roughly 23% of manipulative language may pass through undetected. We are working to improve this through prompt refinement, model evaluation, and expanded training data.

### 10.3 Language Model Limitations
NTRL's neutralization engine is powered by a large language model (currently OpenAI gpt-4o-mini). As such, it is subject to the general limitations of LLM-based systems, including:

- Sensitivity to prompt phrasing.
- Inconsistency across semantically similar inputs.
- Difficulty with implicit or culturally contextual manipulation.
- The possibility, however rare, of introducing subtle meaning shifts.

### 10.4 Cultural and Contextual Nuance
Manipulation can be deeply contextual — language that is neutral in one cultural or political context may be manipulative in another. The system's ability to recognize context-dependent manipulation is limited and is an area of ongoing improvement.

### 10.5 English Language Only
The current system processes English-language content only. Support for additional languages is not available at this time.

---

## 11. Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-28 | Initial editorial policy |

---

*This policy is a living document. As NTRL's capabilities evolve and as we learn from our users and our own evaluation processes, this policy will be updated to reflect our current practices and commitments. All changes will be recorded in the version history above.*
