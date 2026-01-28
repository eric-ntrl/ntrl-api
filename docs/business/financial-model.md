# NTRL Financial Model

> Last updated: January 2026
> Status: Framework — ALL financial projections marked [TBD] require founder input and validation before use in any external-facing materials.

---

## 1. Revenue Model

NTRL's revenue strategy is phased to match product maturity and market validation.

### Phase 1: Consumer Subscription (Launch)

| Item | Detail |
|------|--------|
| Model | Monthly / annual subscription |
| Price range | $5-10/month (annual discount TBD) |
| Target | Individual consumers (B2C) |
| Free tier | [TBD — founder input needed: Is there a freemium tier? Limited articles/day? Time-limited trial?] |

**Pricing considerations:**
- $4.99/month positions below most individual news subscriptions ($10-17/month for NYT, WSJ, etc.)
- $9.99/month positions as a premium product that replaces multiple subscriptions
- [TBD — founder input needed: Target price point and justification]

### Phase 2: B2B API Licensing

| Item | Detail |
|------|--------|
| Model | API usage-based pricing (per article or per 1,000 API calls) |
| Target | Publishers, platforms, newsrooms, research institutions |
| Price range | [TBD — founder input needed] |
| Timeline | [TBD — post-consumer product validation] |

**Potential B2B customers:**
- News aggregators wanting to offer neutralized views
- Social media platforms for content moderation
- Educational institutions for media literacy programs
- Corporate communications teams
- Research organizations studying media manipulation

### Phase 3: Platform Expansion

| Item | Detail |
|------|--------|
| Browser extension | Freemium with subscription upsell |
| White-label | Enterprise licensing for organizations |
| Enterprise dashboard | Seat-based pricing for newsrooms |
| Timeline | [TBD] |

---

## 2. Unit Economics

[TBD — founder input needed for all figures below. Framework provided for modeling.]

| Metric | Target | Current Estimate | Notes |
|--------|--------|-----------------|-------|
| **Customer Acquisition Cost (CAC)** | [TBD] | [TBD] | No paid acquisition data yet |
| **Lifetime Value (LTV)** | [TBD] | [TBD] | Depends on churn and price |
| **LTV:CAC Ratio** | >3:1 | [TBD] | Industry benchmark for healthy SaaS |
| **Monthly Churn Rate** | [TBD] | [TBD] | News app benchmark: 5-10% monthly |
| **Payback Period** | [TBD] | [TBD] | Target: <6 months |
| **Gross Margin** | [TBD] | [TBD] | Driven by API costs per article |

**LTV modeling framework:**

```
LTV = ARPU x (1 / monthly churn rate) x gross margin

Example at $7/month, 5% churn, 80% margin:
LTV = $7 x (1/0.05) x 0.80 = $112

Example at $7/month, 10% churn, 80% margin:
LTV = $7 x (1/0.10) x 0.80 = $56
```

[TBD — founder input needed: What churn rate is realistic for a news app? What are comparable benchmarks?]

---

## 3. Infrastructure Costs

### Current Costs (Staging / Pre-Launch)

| Service | Monthly Cost | Notes |
|---------|-------------|-------|
| **Railway (hosting)** | ~$20-50/month | Staging environment. Production will increase. |
| **OpenAI API (gpt-4o-mini)** | Variable | Primary LLM for classification + neutralization |
| **Google Gemini API** | Variable | Fallback LLM (lower cost than OpenAI) |
| **AWS S3** | Minimal (<$5/month) | Article body storage |
| **Domain / DNS** | ~$15/year | [TBD — current domain] |
| **Apple Developer Account** | $99/year | Required for App Store |
| **Google Play Developer** | $25 one-time | Required for Play Store |

### Projected Production Costs

| Service | Estimated Monthly Cost | At Scale |
|---------|----------------------|----------|
| **Railway (production)** | $50-200/month | Scales with traffic |
| **OpenAI API** | [TBD — see cost per article below] | Scales linearly with articles processed |
| **Gemini API (fallback)** | Lower than OpenAI | Used when OpenAI fails or is rate-limited |
| **AWS S3** | $5-20/month | Scales with article volume |
| **CDN / edge caching** | [TBD] | Needed at scale |
| **Monitoring / logging** | [TBD] | Sentry, Datadog, or similar |
| **Email / transactional** | [TBD] | User notifications, password reset |

---

## 4. Cost Per Article

This is the critical unit cost for NTRL. Every article passes through the 4-stage pipeline.

### Pipeline Cost Breakdown

| Stage | Operation | Estimated Cost Per Article | Notes |
|-------|-----------|---------------------------|-------|
| **INGEST** | RSS fetch + body scrape + S3 store | ~$0.0001 | Compute + minimal storage |
| **CLASSIFY** | gpt-4o-mini classification | ~$0.001 | Short prompt, structured output |
| **NEUTRALIZE** | gpt-4o-mini neutralization | ~$0.01-0.05 | Longer prompt, full article rewrite |
| **BRIEF ASSEMBLE** | Summary generation | ~$0.005-0.01 | Per-category brief compilation |
| **Total per article** | End-to-end pipeline | **~$0.015-0.06** | Varies by article length |

### Token Cost Estimates (gpt-4o-mini)

| Model | Input Cost | Output Cost |
|-------|-----------|-------------|
| gpt-4o-mini | $0.15 per 1M input tokens | $0.60 per 1M output tokens |

**Per-article token estimates:**
- Classification: ~500 input tokens, ~200 output tokens = ~$0.0002
- Neutralization: ~2,000 input tokens, ~2,000 output tokens = ~$0.0015
- Brief assembly: ~3,000 input tokens, ~500 output tokens = ~$0.0008

**Note:** These are estimates based on current gpt-4o-mini pricing. Actual costs depend on article length, prompt complexity, and retry rates.

### Volume Cost Projections

| Articles/Day | Daily Cost | Monthly Cost | Annual Cost |
|-------------|-----------|-------------|-------------|
| 100 | $1.50-6.00 | $45-180 | $540-2,160 |
| 500 | $7.50-30.00 | $225-900 | $2,700-10,800 |
| 1,000 | $15-60 | $450-1,800 | $5,400-21,600 |
| 5,000 | $75-300 | $2,250-9,000 | $27,000-108,000 |

[TBD — founder input needed: What is the target article volume at launch? At 10K users? At 100K users?]

### Gemini Fallback Cost Advantage

When OpenAI is unavailable or rate-limited, the pipeline falls back to Google Gemini, which is generally cheaper for comparable tasks. This provides both reliability and cost optimization.

---

## 5. Scaling Projections

[TBD — founder input needed for ALL figures in this section.]

### Year 1

| Metric | Target |
|--------|--------|
| Users (end of year) | [TBD] |
| Paying subscribers | [TBD] |
| Monthly revenue | [TBD] |
| ARR (annualized) | [TBD] |
| Monthly burn rate | [TBD] |
| Runway | [TBD] |

### Year 2

| Metric | Target |
|--------|--------|
| Users (end of year) | [TBD] |
| Paying subscribers | [TBD] |
| Monthly revenue | [TBD] |
| ARR (annualized) | [TBD] |
| B2B revenue contribution | [TBD] |

### Year 3

| Metric | Target |
|--------|--------|
| Users (end of year) | [TBD] |
| Paying subscribers | [TBD] |
| Monthly revenue | [TBD] |
| ARR (annualized) | [TBD] |
| B2B revenue contribution | [TBD] |
| Path to profitability | [TBD] |

---

## 6. Use of Funds

[TBD — founder input needed. Applicable if/when raising external capital.]

| Category | Allocation % | Purpose |
|----------|-------------|---------|
| **Engineering** | [TBD] | Backend scaling, frontend polish, infrastructure |
| **Marketing** | [TBD] | User acquisition, content marketing, PR |
| **Operations** | [TBD] | Hosting, API costs, tools, legal |
| **Legal** | [TBD] | Fair use counsel, privacy compliance, terms of service |
| **Hiring** | [TBD] | Key roles: [TBD] |
| **Reserve** | [TBD] | 6-month runway buffer |

### Priority Hires (if funded)

[TBD — founder input needed]
- [ ] Growth / marketing lead
- [ ] Mobile engineer (React Native)
- [ ] Backend engineer (Python / FastAPI)
- [ ] Designer (UX/UI)
- [ ] Content / editorial (source curation, quality assurance)

---

## 7. Key Assumptions

[TBD — founder input needed. All financial projections depend on these assumptions being validated.]

1. **Pricing assumption:** Consumers will pay $5-10/month for neutralized news. [Needs validation via beta testing and willingness-to-pay research.]
2. **Churn assumption:** Monthly churn will be [TBD]%. News apps historically have high churn; NTRL's unique value proposition may lower this. [Needs beta data.]
3. **API cost assumption:** OpenAI pricing remains stable or decreases. [Risk: price increases would compress margins.]
4. **Volume assumption:** [TBD] articles/day is sufficient for 10 categories. [Currently processing ~100-300/day in staging.]
5. **Conversion assumption:** [TBD]% of free users convert to paid. [Industry benchmark: 2-5% for freemium, higher for free trial.]
6. **Fair use assumption:** NTRL's transformative use of article content is legally defensible. [Risk: requires legal counsel. See content sourcing policy.]
7. **Market timing assumption:** Consumer demand for AI-neutralized news is strong enough to support a standalone product now, not just in the future.

---

## 8. Financial Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| OpenAI price increase | Margins compress | Gemini fallback, model optimization, caching |
| Low conversion rate | Revenue below target | Freemium optimization, onboarding improvement |
| High churn | LTV insufficient | Content quality focus, push notifications, habit loops |
| Legal challenge (fair use) | Existential | Legal counsel, source partnerships, licensing |
| Competition from Big Tech | Market share loss | First-mover advantage, transparency moat, community |
| Scaling costs exceed revenue | Cash burn | Usage-based pricing, article capping, tiered plans |

---

## 9. Break-Even Analysis

[TBD — founder input needed]

**Framework:**

```
Monthly fixed costs = Railway + S3 + tools + salaries
Monthly variable costs = (articles/day x 30 x cost per article)
Monthly revenue = subscribers x ARPU

Break-even subscribers = monthly fixed costs / (ARPU - variable cost per user)
```

**Illustrative example (NOT projections):**

```
Fixed costs: $5,000/month (hosting, tools, solo founder)
Variable cost per user: $1/month (estimated API costs per user)
ARPU: $7/month

Break-even = $5,000 / ($7 - $1) = 834 subscribers
```

[TBD — founder input needed: Actual fixed cost baseline and variable cost per user estimates.]
