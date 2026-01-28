# NTRL Support Playbook

> Last updated: January 2026
> Status: Pre-launch draft. Placeholders marked [TBD] require decisions before public launch.

---

## 1. Support Channels

| Channel | Status | Notes |
|---------|--------|-------|
| **Support email** | [TBD — support email address needed, e.g., support@ntrl.news] | Primary channel for beta and launch |
| **In-app feedback** | Planned (Phase 2) | Button in settings to submit feedback with device info |
| **App Store reviews** | Active upon launch | Monitor daily; respond within 48 hours |
| **Play Store reviews** | Active upon launch | Monitor daily; respond within 48 hours |
| **Social media** | [TBD — Twitter/X, Threads, or other] | Public-facing support for visibility |
| **Bug reporting** | [TBD — form or email] | Structured format for reproducible issues |

### Response Time Targets

| Channel | Target Response Time |
|---------|---------------------|
| Support email | Within 24 hours |
| App Store / Play Store reviews | Within 48 hours |
| Critical bug reports | Within 4 hours (during business hours) |
| Social media mentions | Within 12 hours |

---

## 2. Common Issues & Responses

### Issue: "Article content seems wrong or inaccurate"

**Context:** Users may perceive neutralized content as "wrong" because it differs from the original article. NTRL removes manipulative language — it does NOT fact-check or verify claims.

**Response template:**

> Thank you for reporting this. NTRL neutralizes manipulative language (emotionally loaded words, sensationalism, framing bias, etc.) but does not fact-check or alter the factual claims in articles. The information in the neutralized version comes directly from the original source.
>
> You can always view the original article by tapping the source link at the top of the article. If you believe the original source itself contains factual errors, we recommend checking with other news sources.
>
> If you think our neutralization changed the meaning of a passage, we would love to hear the details so we can improve. Please reply with the article title and the specific passage that seems incorrect.

**Key points:**
- NTRL neutralizes language, not facts
- Always direct to original source
- Invite specific feedback for improvement

---

### Issue: "Why is this phrase highlighted?"

**Context:** Users viewing the Transparency view see color-coded highlights and want to understand why a specific phrase was flagged.

**Response template:**

> Great question! NTRL detects 14 categories of manipulative language. Each highlight color corresponds to a category. You can tap any highlight to see which category it belongs to, and tap the legend icon to see all categories with explanations.
>
> The 14 categories include: emotionally loaded language, sensationalism, partisan framing, false equivalence, appeal to fear, appeal to authority, weasel words, unsupported superlatives, inflammatory language, leading language, and others.
>
> If you believe a specific phrase was incorrectly flagged, we appreciate the feedback — it helps us improve our detection accuracy. Please share the article title and the phrase in question.

**Key points:**
- Direct to the in-app legend
- Name some of the 14 categories
- Invite correction feedback

---

### Issue: "Missing category / a section is empty"

**Context:** One of the 10 feed categories shows no articles or very few articles.

**Response template:**

> Thank you for letting us know. Feed categories depend on the availability of articles from our news sources' RSS feeds. Some categories (like Science or Environment) may have fewer articles than others (like Top Stories or U.S.) on any given day.
>
> Our pipeline refreshes every 4 hours, so new articles will appear as sources publish them. If a category has been empty for more than 24 hours, that is unusual — please let us know and we will investigate.
>
> Which category are you seeing as empty? That will help us check the underlying sources.

**Key points:**
- Categories depend on RSS source availability
- Pipeline refreshes every 4 hours (cron: 0 */4 * * *)
- Empty for >24 hours is unusual and warrants investigation

---

### Issue: "App is slow or not loading"

**Context:** Performance issues, slow load times, or content not appearing.

**Response template:**

> We are sorry you are experiencing slow performance. Here are a few things to try:
>
> 1. Check your internet connection — NTRL requires an active connection to load articles.
> 2. Force-close the app and reopen it.
> 3. If available, try switching between Wi-Fi and cellular data.
> 4. Make sure you are running the latest version of the app.
>
> If the issue persists, could you let us know:
> - Your device model (e.g., iPhone 15, Pixel 8)
> - Your operating system version
> - What you see on screen (blank, loading spinner, error message)
>
> This will help us diagnose the issue quickly.

**Key points:**
- Basic troubleshooting first
- Collect device info for debugging
- Do NOT mention clearing cache unless app has cache-clear functionality

---

### Issue: "Highlights don't appear in the transparency view"

**Context:** User opens the transparency/redline view but sees no colored highlights on the text.

**Response template:**

> The transparency view shows highlighted changes when our pipeline has detected and neutralized manipulative language in the article. There are a few reasons highlights might not appear:
>
> 1. **The article may have minimal manipulation** — If the original article used mostly neutral language, there may be few or no changes to highlight.
> 2. **Transparency data may still be loading** — Please wait a moment and try scrolling or reopening the article.
> 3. **Pipeline timing** — Very recently published articles may not have completed the full neutralization pipeline yet.
>
> If you believe the article should have highlights (e.g., you read the original and noticed strong language), please share the article title and we will investigate.

**Key points:**
- Some articles genuinely have minimal manipulation
- Loading/timing may be a factor
- Invite specific feedback

---

### Issue: "Article not fully neutralized / some parts still seem biased"

**Context:** User notices manipulative language that was not caught or neutralized.

**Response template:**

> Thank you for the sharp eye. Our neutralization pipeline achieves 96% precision and 86% F1 accuracy, which means it catches the large majority of manipulative language — but not 100%.
>
> A few factors that can affect completeness:
> - **Long articles (over ~8,000 characters)** may not be fully processed due to model context limits. We are working on chunked processing to address this.
> - **Subtle manipulation** (e.g., strategic omission, implicit framing) is harder for AI to detect than overt emotional language.
> - **Our system improves over time** — feedback like yours directly helps us refine our detection.
>
> If you can share the article title and the specific passage that still seems manipulative, we will review it and use it to improve.

**Key points:**
- Acknowledge the limitation honestly
- Long articles are a known constraint
- Emphasize continuous improvement
- Always request specific examples

---

### Issue: "I want to cancel my subscription"

**Context:** User wants to cancel. (Applicable once subscription billing is live — Phase 2.)

**Response template:**

> We are sorry to see you go. You can cancel your subscription at any time through your device's subscription settings:
>
> **iOS:** Settings > Apple ID > Subscriptions > NTRL > Cancel
> **Android:** Play Store > Menu > Subscriptions > NTRL > Cancel
>
> Your access will continue until the end of your current billing period. We do not offer partial refunds, but Apple and Google may process refund requests through their standard policies.
>
> If there is something we could improve, we would genuinely appreciate hearing about it. Your feedback helps us build a better product.

---

## 3. Escalation Path

| Level | Who | When |
|-------|-----|------|
| **L1: Standard Support** | [TBD — founder or support person] | All initial inquiries |
| **L2: Technical Investigation** | [TBD — developer or founder] | Reproducible bugs, pipeline failures, data issues |
| **L3: Critical / Legal** | [TBD — founder + legal counsel if needed] | Security issues, legal threats, press inquiries, data breach |

### Escalation Triggers

Escalate immediately to L2/L3 for:
- Any report of personal data exposure
- Legal threats or cease-and-desist communications
- Press inquiries
- Reports of harmful or dangerous content in neutralized articles
- Pipeline completely down (no new articles for >8 hours)
- App crash affecting multiple users

---

## 4. Response Templates — Quick Reference

### Positive review response (App Store / Play Store)

> Thank you so much for the kind review! We are glad NTRL is helping you stay informed without the noise. If you ever have suggestions, we are always listening.

### Negative review response (App Store / Play Store)

> Thank you for the feedback. We are sorry NTRL did not meet your expectations. We are a small team working hard to improve, and we take every review seriously. If you are willing, please reach out to [TBD — support email] with details about your experience — we would love to make it right.

### Bug report acknowledgment

> Thank you for reporting this. We have logged the issue and will investigate. If we need more information, we will follow up. We appreciate your help making NTRL better.

### Feature request acknowledgment

> Thank you for the suggestion! We track all feature requests and prioritize based on community interest. While we cannot guarantee a timeline, your input directly shapes our roadmap.

---

## 5. App Store Review Response Guidelines

### Principles
1. **Respond to every review rated 3 stars or below** within 48 hours.
2. **Respond to positive reviews** (4-5 stars) when time permits — it builds community.
3. **Never be defensive.** Acknowledge, empathize, offer help.
4. **Never reveal technical details** in public responses (no API names, no infrastructure details).
5. **Move conversations to email** for complex issues.
6. **Thank users for feedback** regardless of tone.

### What NOT to say in public review responses
- Do not mention specific technologies (OpenAI, GPT, Railway, etc.)
- Do not promise specific features or timelines
- Do not argue about whether something is biased or manipulative
- Do not blame the user's device or connection
- Do not share internal metrics

---

## 6. FAQ for Users

### What is NTRL?
NTRL is a news app that uses AI to remove manipulative language from news articles. We take articles from trusted sources, detect 14 categories of manipulation (like emotionally loaded language, sensationalism, and partisan framing), and rewrite sentences to be factual and neutral — while preserving the original information.

### Does NTRL fact-check articles?
No. NTRL neutralizes *how* information is presented (removing manipulative language) but does not verify *what* is presented (factual claims). We always link to the original source so you can access the unmodified article.

### Where does NTRL get its news?
We aggregate content from publicly available RSS feeds across a diverse range of news sources, including wire services (AP, Reuters), broadsheets (NYT, BBC, Guardian), and other established outlets. Source names are displayed on every article.

### What are the 14 manipulation categories?
NTRL detects: emotionally loaded language, sensationalism, partisan framing, false equivalence, appeal to fear, appeal to authority, weasel words, unsupported superlatives, inflammatory language, leading language, and four additional categories. You can see all categories in the Transparency view legend within the app.

### How accurate is the neutralization?
Our pipeline achieves 96% precision and 86% F1 accuracy on our test corpus. This means the vast majority of manipulative language is correctly identified and neutralized. We continuously improve through user feedback and pipeline refinement.

### Is my data private?
[TBD — privacy policy needs to be finalized. Framework: NTRL does not track personal reading behavior. No personal data is sold. Minimal data collection.]

### How often is content updated?
Our pipeline runs every 4 hours, pulling in the latest articles from our sources. Content freshness depends on how frequently sources publish to their RSS feeds.

### Can I read the original article?
Yes. Every article includes a link to the original source. The Transparency view also lets you see exactly what was changed and why, with color-coded highlights.

### What devices are supported?
NTRL is available for iOS and Android. [TBD — minimum OS versions.]

### How much does NTRL cost?
[TBD — pricing not yet finalized. See financial model for planned pricing tiers.]
