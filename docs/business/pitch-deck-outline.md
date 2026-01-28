# NTRL Pitch Deck Outline

Slide-by-slide content guide for investor presentations.
Updated: January 2026

---

## Slide 1: Title

**NTRL**
*Neutral News*

A calm, deterministic news feed that strips manipulative language and delivers what actually happened.

[Logo/Visual]

---

## Slide 2: The Problem

**Headlines are engineered to hijack your attention.**

Modern news is optimized for clicks, not clarity. Every headline, every lede, every push notification is tuned to provoke an emotional reaction before you have a chance to think.

**The damage is real:**
- 70% of Americans "worn out" by news (Pew Research)
- News avoidance has doubled since 2017
- Trust in media at historic lows across every demographic
- Rising anxiety, polarization, and disengagement from civic life

**The worst part:** Even people who know they are being manipulated cannot unsee the framing. The only defense is to change the content itself.

**Visual:** Before/after headline comparison

---

## Slide 3: The Solution

**NTRL is a filter for information, not a filter for opinion.**

We algorithmically detect and remove manipulative language so people can understand what happened without being told how to feel about it.

**We identify and neutralize 14 categories of manipulation:**
- Clickbait and curiosity gaps ("You won't believe...")
- Urgency inflation ("BREAKING", "JUST IN")
- Emotional amplifiers ("slams", "destroys", "stunned")
- Agenda signaling ("Finally", "controversial")
- Speculative framing, fear appeals, tribal cues, and more

**What stays:** Facts, context, what is known, what is uncertain, and the reader's own judgment.

---

## Slide 4: Before & After Demo

**The transformation is immediate and obvious:**

| Before | After |
|--------|-------|
| AI startup SHAKES UP the industry with game-changing model | AI startup releases a new model with performance improvements |
| Markets PANIC as stocks plunge in terrifying selloff | Stocks decline amid investor concern over rate outlook |
| Crime wave as city spirals out of control | Police report increase in incidents across several districts |
| BREAKING: Lawmakers SLAM controversial new bill | Lawmakers debate proposed legislation |

**Visual:** App screenshot showing the 3-tab article view -- Brief / Full / Ntrl -- with category-specific highlight colors marking every change

---

## Slide 5: How It Works

**4-Stage Pipeline: Ingest --> Classify --> Neutralize --> Deliver**

1. **Ingest** -- Pull from 10 curated feed categories (US, World, Business, Tech, Science, Health, Sports, Entertainment, Environment, Opinion). 200+ articles per run across diverse sources.

2. **Classify** -- AI scans every article and flags manipulative language across 14 manipulation categories. Each span is tagged by type (clickbait, urgency, emotional, speculative, etc.) with confidence scores.

3. **Neutralize** -- Flagged content is rewritten to preserve factual meaning while removing manipulative framing. 95+ articles neutralized per pipeline run. Every change is tracked at span level.

4. **Deliver** -- Clean content served to the app with full transparency. Users see three views of every article (Brief / Full / Ntrl) and 250 stories assembled into a daily brief. Highlights are color-coded by manipulation category (4 color groups).

**Key technical properties:**
- LLM-powered classification and neutralization (GPT-4o-mini)
- Span-level change tracking with manipulation-type metadata
- Deterministic output (same input produces same result)
- Category-specific highlight colors so users can see patterns at a glance

---

## Slide 6: Product Demo

**Screenshots:**
1. **Feed view** -- Calm, organized sections across 10 categories. No red banners, no urgency cues, no engagement bait.
2. **Article view** -- 3-tab interface: Brief (key facts), Full (complete neutralized article), Ntrl (transparency view showing what changed and why).
3. **Transparency view** -- Category-specific highlight colors mark every manipulation that was removed, with before/after comparisons inline.

**Design principles:**
- No likes, shares, or engagement metrics
- No personalization or algorithmic "for you" feeds
- No breaking alerts or manufactured urgency
- No ads, no tracking, no dark patterns
- Information density over attention capture

---

## Slide 7: Market Opportunity

**Target Users:**
- News-fatigued professionals who want to stay informed without the noise
- Mental health-conscious consumers actively reducing media anxiety
- Parents seeking safe, factual news for families
- Educators and researchers who need clean source material
- Anyone who has quit the news and wants a reason to come back

**Market Size:**
- [TBD -- TAM: Total news consumption market]
- [TBD -- SAM: Subscription news and aggregator market]
- [TBD -- SOM: Target early adopters in first 2 years]

---

## Slide 8: Competitive Landscape

| Feature | NTRL | Apple News | Ground News | AllSides | SmartNews | 1440 |
|---------|------|------------|-------------|----------|-----------|------|
| Removes manipulative language | Yes | No | No | No | No | No |
| Shows what was changed | Yes | No | No | No | No | No |
| No engagement mechanics | Yes | No | No | No | No | Yes |
| No personalization algorithm | Yes | No | Partial | Partial | No | Yes |
| Bias/framing awareness | Yes (implicit) | No | Yes | Yes | No | No |
| Multi-view article reading | Yes (3 tabs) | No | No | No | No | No |
| Daily brief | Yes | No | No | No | Yes | Yes |

**How they differ:**
- **Ground News / AllSides** show you that bias exists. NTRL removes it.
- **SmartNews** uses AI for personalization and engagement. NTRL uses AI for neutralization.
- **1440** delivers a clean daily brief but does not transform source articles or provide transparency into framing.
- **Apple News** is a distribution platform, not a trust layer.

**Our moat:** NTRL is the only product that transforms the content itself, shows users exactly what was changed, and explains why. Nobody else touches the text.

---

## Slide 9: Business Model

**Phase 1: Consumer App**
- Subscription: $5-10/month
- Target: 10,000 paying subscribers in Year 1
- [TBD -- Detailed financial projections]

**Phase 2: B2B API**
- License the neutralization pipeline to publishers and platforms
- Enterprise communications and internal news tools
- Compliance, audit, and media monitoring solutions

**Phase 3: Platform Expansion**
- Browser extension for in-page neutralization
- Social media filtering layer
- Real-time neutralization API for third-party integrations

---

## Slide 10: Traction

**Built, deployed, and running.**

| Metric | Status |
|--------|--------|
| Articles ingested per pipeline run | 200+ |
| Articles neutralized per run | 95+ |
| Stories assembled into daily brief | 250 |
| Feed categories | 10 |
| Manipulation categories detected | 14 |
| Classification precision (GPT-4o-mini) | 96% |
| Classification F1 score | 86% |
| Full codebase audit | Completed (25 items resolved) |
| Staging environment | Deployed |
| Mobile app (iOS/Android) | Built (React Native / Expo) |
| Backend API | Deployed on Railway |

**What this means:** The core product works. The pipeline ingests real articles from real sources, classifies manipulation with 96% precision, neutralizes the content, and delivers it to a working mobile app. This is not a prototype -- it is a functioning product in staging.

**Next Milestones:**
- [ ] Beta launch with first 100 users
- [ ] App Store / Google Play submission
- [ ] Iterate on neutralization quality with user feedback
- [ ] Scale pipeline to continuous runs

---

## Slide 11: Team

**Eric Brown** -- Founder & CEO
[TBD -- Background, relevant experience, why you are building this]

**Advisors / Key Hires:**
[TBD -- If applicable]

---

## Slide 12: Roadmap

**Phase 1 (Current) -- Foundation**
- Full pipeline operational: Ingest, Classify, Neutralize, Deliver
- Mobile app with 3-tab article view and category highlights
- 10 feed categories, 14 manipulation categories
- Codebase audit complete, staging deployed

**Phase 2 -- Public Beta**
- Beta launch, first 100-1,000 users
- App Store and Google Play submission
- Subscription model validation
- Continuous pipeline runs, expanded source coverage

**Phase 3 -- Scale**
- Scale to 10,000+ users
- B2B pilot programs with publishers
- Browser extension development
- Series A preparation

---

## Slide 13: The Ask

**Raising:** $[TBD]

**Use of Funds:**
- Engineering (50%) -- Full-time developers, infrastructure scaling
- Marketing (25%) -- User acquisition, content marketing, PR
- Operations (15%) -- Pipeline scaling, source licensing, cloud costs
- Legal/Other (10%) -- IP protection, compliance, app store fees

**Runway:** [TBD]

[TBD -- Detailed financial projections in appendix]

---

## Slide 14: Vision

**A world where information informs, not manipulates.**

The attention economy broke the news. NTRL fixes the output. We are building the trust layer between what is published and what people read -- a permanent, scalable filter that protects clarity, equanimity, and independent thought.

*Neutrality is not passive. It is disciplined refusal to distort.*

---

## Slide 15: Contact

**Eric Brown**
Founder, NTRL

[Email]
[Phone]
[LinkedIn]

[Website: ntrl.news]

---

## Appendix Slides

### A: Accuracy Metrics

**Classification Performance (GPT-4o-mini):**

| Metric | Score |
|--------|-------|
| Precision | 96% |
| F1 Score | 86% |
| Articles classified per run | 200+ |
| Manipulation categories | 14 |

**What this means:**
- 96% precision: When the system flags something as manipulative, it is correct 96% of the time. Very low false-positive rate.
- 86% F1: Strong balance between catching manipulation (recall) and avoiding false flags (precision). Production-grade performance.

**Manipulation categories detected:**
Clickbait, urgency inflation, emotional amplification, agenda signaling, speculative framing, fear appeals, tribal cues, authority appeals, false balance, sensationalism, loaded language, omission framing, cherry-picking signals, and narrative steering.

### B: Technical Architecture

**Pipeline:** Ingest --> Classify --> Neutralize --> Deliver

- **Ingest:** RSS/API aggregation across 10 feed categories (US, World, Business, Tech, Science, Health, Sports, Entertainment, Environment, Opinion)
- **Classify:** GPT-4o-mini with structured output; 14 manipulation categories; span-level tagging with confidence scores
- **Neutralize:** LLM rewriting with deterministic constraints; span-level change tracking; manipulation-type metadata preserved
- **Deliver:** Railway-hosted API; React Native / Expo mobile app; 3-tab article view (Brief / Full / Ntrl); category-specific highlight colors (4 color groups)

**Codebase audit:** 25-item audit completed covering pipeline reliability, error handling, API contracts, and mobile app stability.

### C: Detailed Financials

[TBD -- Revenue projections, unit economics, CAC/LTV assumptions]

### D: Neutralization Examples

Extended before/after samples across all 14 manipulation categories, demonstrating the range and precision of the system.

[Include 5-10 real examples from pipeline output, organized by manipulation type]
