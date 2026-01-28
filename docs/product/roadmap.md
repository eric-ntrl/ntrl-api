# NTRL Product Roadmap

> Last updated: January 2026
> Status: Living document. Dates marked [TBD] require timeline decisions.

---

## Overview

NTRL's product development is organized into four phases, progressing from proof-of-concept through public launch, B2B expansion, and full-scale platform. Each phase builds on validated learnings from the previous one.

**Current status:** Phase 1 (POC & Launch) — core pipeline and mobile app operational in staging.

---

## Phase 1: Proof of Concept & Launch (Current)

**Objective:** Validate the core product — AI neutralization pipeline + mobile reading experience — and ship to App Store / Play Store.

### Completed

- [x] **4-stage pipeline operational** — INGEST, CLASSIFY, NEUTRALIZE, BRIEF ASSEMBLE running end-to-end on Railway
- [x] **React Native app (iOS/Android)** — Built with Expo, calm neutral design, dark mode support
- [x] **10 feed categories** — Top Stories, U.S., World, Business, Technology, Science, Health, Sports, Entertainment, Environment
- [x] **14 manipulation categories** — Comprehensive taxonomy for detecting and classifying manipulative language
- [x] **Transparency view** — Color-coded highlights showing what was changed and which manipulation category applies, with interactive legend
- [x] **Staging deployed on Railway** — Full backend running with PostgreSQL, S3, OpenAI integration
- [x] **96% precision, 86% F1 accuracy** — Validated across test corpus with production pipeline
- [x] **Full codebase audit completed** — 25 items identified and addressed (January 2026)
- [x] **RSS source diversity** — Wire services, broadsheets, tabloids, tech/business sources

### In Progress / Remaining

- [ ] **App Store submission** — Requires: privacy policy, terms of service, app review guidelines compliance, screenshots, App Store listing copy
- [ ] **Beta testing program** — TestFlight (iOS) + Google Play Internal Testing (Android). See [beta-testing-plan.md](/docs/launch/beta-testing-plan.md)
- [ ] **Privacy policy & terms of service finalized** — [TBD — needs legal review]
- [ ] **App Store listing assets** — Screenshots, description, keywords, category selection
- [ ] **Onboarding screen** — First-launch experience explaining what NTRL does
- [ ] **Error handling polish** — Empty states, network error messages, loading states
- [ ] **Performance baseline** — Establish load time benchmarks before public launch

### Technical Prerequisites for Phase 2
- App Store / Play Store approval
- Beta feedback incorporated
- Privacy policy and terms of service live
- Stable production deployment on Railway

---

## Phase 2: Public Launch & Growth

**Objective:** Launch publicly, add user accounts and retention features, implement subscription billing.

**Timeline:** [TBD — needs timeline + decisions. Depends on App Store approval and beta feedback cycle.]

### Features

- [ ] **User accounts & authentication** — Email/password and social login (Apple, Google). Required for saved articles, preferences, and billing.
- [ ] **Saved articles & reading history (server-side)** — Persist across devices. Currently no user state is saved.
- [ ] **Push notifications** — "Your daily brief is ready" notification. Configurable frequency (daily, breaking only, off).
- [ ] **Onboarding flow** — Multi-screen walkthrough: what is NTRL, how neutralization works, category selection, notification preferences.
- [ ] **Subscription billing** — RevenueCat or similar for App Store / Play Store in-app purchases. Free trial period [TBD].
- [ ] **Analytics (privacy-respecting)** — No personal data tracking. Aggregate metrics: articles read, categories popular, retention rates. Tool: [TBD — PostHog, Mixpanel, or custom].
- [ ] **Performance optimization** — Chunked neutralization for long articles (>8,000 characters). Pagination for large feeds. Image caching.
- [ ] **Category preferences** — Let users choose which of the 10 categories appear in their feed.
- [ ] **Share functionality** — Share neutralized article link or comparison view.
- [ ] **Offline reading** — Cache articles for offline access.

### Technical Prerequisites for Phase 3
- Stable user account system
- Billing operational with revenue flowing
- Analytics providing actionable data on usage patterns
- Performance handles 10,000+ concurrent users

---

## Phase 3: B2B & Platform Expansion

**Objective:** Monetize the neutralization engine beyond the consumer app. Open the platform to third parties.

**Timeline:** [TBD — needs timeline + decisions. Depends on consumer product achieving product-market fit.]

### Features

- [ ] **Public API for neutralization** — RESTful API allowing third parties to submit text and receive neutralized output with manipulation classifications. Usage-based pricing.
- [ ] **Browser extension** — Chrome/Firefox extension that neutralizes articles in-place on any news website. Freemium model (limited articles free, unlimited with subscription).
- [ ] **Enterprise dashboard** — Web-based dashboard for organizational customers: usage analytics, team management, API key management, billing.
- [ ] **White-label option** — Allow publishers and platforms to embed NTRL neutralization under their own brand. Custom pricing.
- [ ] **Social media content filtering** — Extend neutralization to social media posts, comments, and threads. API endpoint for platforms.
- [ ] **Bulk processing API** — Batch endpoint for processing large volumes of articles (research institutions, archives).
- [ ] **Webhook notifications** — Real-time notifications when new neutralized content is available in specified categories.

### Technical Prerequisites for Phase 4
- API rate limiting and authentication production-ready
- Multi-tenant architecture for B2B customers
- SLA monitoring and uptime guarantees
- Legal framework for B2B contracts

---

## Phase 4: Scale & Expansion

**Objective:** Expand NTRL's reach globally, deepen the platform, and establish partnerships.

**Timeline:** [TBD — needs timeline + decisions. 18-36 months post-launch, contingent on funding and traction.]

### Features

- [ ] **Multi-language support** — Neutralization pipeline for Spanish, French, German, Portuguese, and other high-demand languages. Requires language-specific manipulation taxonomies.
- [ ] **Real-time neutralization API** — Sub-second neutralization for live content (breaking news, social feeds). Requires model optimization and edge deployment.
- [ ] **Custom source management** — Users submit their own RSS feeds for neutralization. Content processed on-demand.
- [ ] **Advanced analytics for publishers** — Publishers can see how their content is classified across the 14 manipulation categories. Anonymized, aggregate insights to help newsrooms reduce manipulative language.
- [ ] **Research partnerships** — Collaborate with universities and media research organizations. Anonymized dataset access for studying manipulation patterns in news.
- [ ] **Content comparison tool** — Side-by-side comparison of how different outlets cover the same story, with manipulation levels quantified.
- [ ] **Newsroom integration** — Plugin for CMS platforms (WordPress, Arc, etc.) that flags manipulative language before publication.
- [ ] **Accessibility improvements** — VoiceOver/TalkBack optimization, large text support, high contrast mode, screen reader-friendly transparency view.

### Technical Prerequisites
- Multi-region infrastructure
- <200ms API response times
- Language-specific ML models or fine-tuned LLMs
- Data partnerships with research institutions

---

## Cross-Cutting Concerns (All Phases)

These items span multiple phases and are continuously improved:

| Concern | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---------|---------|---------|---------|---------|
| **Security** | HTTPS, env vars, no PII stored | Auth, token management, encrypted storage | API keys, rate limiting, DDoS protection | SOC 2, penetration testing |
| **Privacy** | No user tracking | Privacy-respecting analytics | Data processing agreements (B2B) | GDPR/CCPA full compliance |
| **Testing** | Pytest, Playwright | CI/CD pipeline, integration tests | Load testing, API contract tests | Chaos engineering |
| **Monitoring** | Railway logs, /v1/status | Sentry, uptime monitoring | SLA dashboards, alerting | Full observability stack |
| **Documentation** | CLAUDE.md files, internal docs | User-facing help center | API documentation, developer portal | Multi-language docs |

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| Jan 2026 | Playwright recommended over Maestro for UI testing | Better integration with existing tooling |
| Jan 2026 | Full codebase audit (25 items) completed | Pre-launch quality gate |
| [TBD] | Pricing decision | [TBD — awaiting market research / beta feedback] |
| [TBD] | Free tier vs. paid-only decision | [TBD — impacts growth strategy] |
| [TBD] | Analytics tool selection | [TBD — privacy vs. feature tradeoff] |
| [TBD] | Authentication provider | [TBD — Firebase Auth, Auth0, Supabase, or custom] |

---

## Open Questions

- [TBD — needs timeline + decisions] When is the target date for App Store submission?
- [TBD — needs timeline + decisions] What is the minimum beta testing duration before public launch?
- [TBD — needs timeline + decisions] Should Phase 2 features be shipped incrementally (rolling launch) or as a single release?
- [TBD — needs timeline + decisions] At what user count / revenue does Phase 3 (B2B) become a priority?
- [TBD — needs timeline + decisions] Is multi-language support contingent on external funding?
