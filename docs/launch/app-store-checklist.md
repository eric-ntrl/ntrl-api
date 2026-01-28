# NTRL — App Store Submission Checklist

> **Status:** Pre-submission
> **Last Updated:** 2026-01-28
> **Owner:** Eric Brown

This checklist covers all requirements for submitting NTRL to the Apple App Store (via App Store Connect) and Google Play Store (via Google Play Console).

---

## 1. Pre-Submission Requirements

### Build & Configuration
- [ ] EAS Build configured and producing stable release builds
- [ ] Bundle identifier registered: `[TBD — e.g., com.ntrl.app]`
- [ ] Android package name registered: `[TBD — e.g., com.ntrl.app]`
- [ ] App version set (e.g., `1.0.0`)
- [ ] Build number / version code incremented for each submission
- [ ] `app.json` / `app.config.js` metadata finalized
- [ ] Expo updates / OTA configuration reviewed (ensure compliant with store policies)

### Assets
- [ ] App icon — 1024x1024 PNG, no transparency (iOS), 512x512 PNG (Google Play)
- [ ] Adaptive icon configured for Android (foreground + background layers)
- [ ] Splash screen configured and rendering correctly on all screen sizes
- [ ] No placeholder or development imagery in production build

### Technical
- [ ] Production API endpoint configured (Railway)
- [ ] All debug/dev toggles disabled in release build
- [ ] Crash-free launch confirmed on physical iOS and Android devices
- [ ] Deep linking / universal links configured (if applicable)
- [ ] No HTTP (non-HTTPS) network requests — App Transport Security compliance

---

## 2. iOS App Store Requirements

### App Store Connect Setup
- [ ] Apple Developer Program membership active ($99/year)
- [ ] App record created in App Store Connect
- [ ] Bundle ID registered in Apple Developer portal
- [ ] Signing certificates and provisioning profiles configured via EAS

### Screenshots
- [ ] **6.7-inch display** (iPhone 15 Pro Max / iPhone 16 Pro Max) — minimum 3, recommended 5–8
- [ ] **5.5-inch display** (iPhone 8 Plus) — minimum 3, recommended 5–8
- [ ] Screenshots show core user flows: feed view, Brief tab, Full tab, Ntrl tab (transparency view), category selection
- [ ] No device bezels required (optional but recommended for marketing)
- [ ] Screenshots are **1290 x 2796 px** (6.7") and **1242 x 2208 px** (5.5")
- [ ] Optional: iPad screenshots if iPad layout is supported

### App Information
- [ ] **App Name:** NTRL - Neutral News
- [ ] **Subtitle:** News without manipulation
- [ ] **Description:** See Section 4 below
- [ ] **Keywords:** See Section 6 below
- [ ] **Category:** News
- [ ] **Secondary Category:** [TBD — consider Reference or Education]
- [ ] **Privacy Policy URL:** [TBD — must be live URL before submission]
- [ ] **Support URL:** [TBD]
- [ ] **Marketing URL:** [TBD]
- [ ] **Copyright:** [TBD — e.g., 2026 NTRL]

### Privacy & Compliance
- [ ] App Privacy questionnaire completed in App Store Connect
  - Data types collected: **None** linked to user identity (Phase 1)
  - Usage data: reading preferences stored locally only
- [ ] App does NOT use IDFA — ATT prompt not required
- [ ] No third-party tracking SDKs
- [ ] Privacy Nutrition Label reflects local-only data storage

### Age Rating
- [ ] Age rating questionnaire completed
- [ ] Expected rating: **12+** (news content may include references to violence, politics)
- [ ] No mature content, gambling, or restricted categories

### Review Guidelines Compliance
- [ ] 4.2 — Minimum functionality: app provides clear utility (neutralized news reading)
- [ ] 5.2.1 — No hidden features or functionality
- [ ] 5.1.1 — Privacy policy URL is live and accessible
- [ ] 1.2 — User-generated content: NOT applicable (no UGC in Phase 1)
- [ ] 3.1.1 — In-app purchases: NOT applicable (free, Phase 1)

---

## 3. Google Play Requirements

### Google Play Console Setup
- [ ] Google Play Developer account active ($25 one-time fee)
- [ ] App record created in Google Play Console
- [ ] App signing key configured (Google Play App Signing recommended)
- [ ] AAB (Android App Bundle) format used for upload

### Store Listing Assets
- [ ] **Feature Graphic:** 1024 x 500 px (JPEG or PNG, required)
- [ ] **App Icon:** 512 x 512 px (PNG, 32-bit with alpha)
- [ ] **Screenshots:** minimum 2, recommended 5–8 per device type
  - Phone screenshots: 16:9 or 9:16 aspect ratio
  - Show core user flows: feed, article tabs, category selection, ntrl-view
- [ ] **Short Description:** max 80 characters — `"News stripped of clickbait, hype, and manipulation. Just the facts."`
- [ ] **Full Description:** max 4000 characters — See Section 4 below

### Privacy & Compliance
- [ ] **Privacy Policy URL:** [TBD — must be live URL]
- [ ] Data Safety section completed
  - App does not collect or share user data (Phase 1)
  - Local preferences only — not transmitted
- [ ] Content rating questionnaire (IARC) completed
- [ ] Expected rating: suitable for general audiences / Teen equivalent
- [ ] Target audience and content declarations completed
  - App is NOT designed for children under 13
  - Target audience: general / adults

### App Content
- [ ] App category: News & Magazines
- [ ] App contains news content — comply with Google Play News policy
- [ ] No deceptive behavior declarations

---

## 4. App Metadata

### App Name
**NTRL - Neutral News**

### Subtitle (iOS only, max 30 characters)
**News without manipulation**

### Description — Draft

> **[TBD — Finalize before submission]**

```
NTRL strips manipulative language from the news so you can read the facts without emotional interference.

Every article passes through our neutralization engine, which identifies and removes clickbait headlines, emotional triggers, hype language, agenda framing, and other forms of linguistic manipulation — while preserving every fact, quote, and detail from the original reporting.

READ THREE WAYS
- Brief: A concise summary of the key facts.
- Full: The complete article with manipulative language removed.
- Ntrl: A transparency view showing exactly what was changed and why, with color-coded highlights.

10 TOPIC CATEGORIES
World, U.S., Local, Business, Technology, Science, Health, Environment, Sports, and Culture.

NO MANIPULATION OF YOU, EITHER
- No algorithmic feed — every user sees the same stories.
- No engagement tricks, no infinite scroll psychology, no push notification urgency.
- No personalization. No tracking. No ads.

NTRL does not fact-check, verify claims, or label opinions. We remove the language designed to manipulate your emotions, and let you decide what matters.
```

### Keywords (iOS, max 100 characters total)
```
neutral news,unbiased news,no clickbait,news filter,calm news,media literacy,news anxiety
```

> **Note:** iOS keywords are comma-separated, no spaces after commas, 100-character limit total. The above is 88 characters.

### Keyword Variations to Test
- `neutral news` — primary identity
- `unbiased news` — high search volume
- `news filter` — describes functionality
- `calm news` — emotional benefit
- `no clickbait` — pain-point search
- `news anxiety` — wellness angle
- `media literacy` — educational angle
- `fact-based news` — alternative if space permits
- `news without bias` — alternative phrasing

---

## 5. App Review Considerations

### Reviewer Notes (included with submission)

> **[TBD — Finalize before submission]**

Draft reviewer notes:

```
NTRL is a news reader that uses AI (OpenAI) to remove manipulative language
from publicly available news articles sourced via RSS feeds.

Key points for review:

1. CONTENT SOURCE: Articles are sourced from public RSS feeds of established
   news organizations. NTRL does not produce original reporting.

2. AI PROCESSING: The app uses OpenAI's API to identify and remove
   manipulative language (clickbait, emotional triggers, hype, agenda framing)
   while preserving factual content. This is visible in the "Ntrl" tab of
   each article, which shows all changes with color-coded highlights.

3. NO USER-GENERATED CONTENT: There are no comments, posts, reviews, or any
   form of user-contributed content. Users only read articles.

4. NO SOCIAL FEATURES: No sharing, no profiles, no friend lists, no
   messaging.

5. NO USER ACCOUNTS: Phase 1 does not include authentication or accounts.
   Preferences (topic selection, text size) are stored locally on the device.

6. NO MONETIZATION: Phase 1 is free. No in-app purchases, no subscriptions,
   no ads.

7. PRIVACY: The app collects no personal data. No analytics SDKs, no
   tracking, no advertising identifiers.
```

---

## 6. Keywords — Full Reference

### Primary Keywords (highest priority)
| Keyword | Rationale |
|---------|-----------|
| neutral news | Brand identity, low competition |
| unbiased news | High search volume |
| no clickbait | Direct pain point |
| news filter | Functional description |

### Secondary Keywords
| Keyword | Rationale |
|---------|-----------|
| calm news | Wellness positioning |
| news anxiety | Mental health search trend |
| media literacy | Educational angle |
| fact-based news | Alternative framing |
| news without bias | Long-tail variation |
| news detox | Wellness trend |

---

## 7. Post-Submission

### Monitoring
- [ ] Check App Store Connect / Google Play Console daily for review status updates
- [ ] Estimated review time: 24–48 hours (Apple), 1–7 days (Google, first submission)
- [ ] Monitor email for reviewer questions or rejection notices

### If Rejected
- [ ] Read rejection reason carefully — match to specific review guideline
- [ ] Document the rejection reason and resolution
- [ ] Common risks for NTRL:
  - **Content rights:** Be prepared to explain RSS sourcing and fair use / transformation
  - **Minimum functionality:** Ensure the app demonstrates clear value in review
  - **Privacy policy:** Must be live and accurate at time of review
- [ ] Resubmit with detailed resolution notes in the reviewer comments field

### Post-Approval
- [ ] Verify app listing appears correctly in both stores
- [ ] Confirm download and launch on fresh device
- [ ] Monitor crash reports (Expo, Sentry if configured)
- [ ] Monitor early user reviews and ratings

---

## 8. Outstanding Items — [TBD]

| Item | Status | Owner |
|------|--------|-------|
| Final app description (iOS + Android) | TBD | |
| Final keyword list (iOS) | TBD | |
| Privacy policy — live URL | TBD | |
| Support URL | TBD | |
| Marketing URL | TBD | |
| Screenshots — iPhone 6.7" | TBD | |
| Screenshots — iPhone 5.5" | TBD | |
| Screenshots — Android phone | TBD | |
| Feature graphic — Google Play | TBD | |
| Bundle ID / package name finalized | TBD | |
| App icon — final version | TBD | |
| Splash screen — final version | TBD | |
| Reviewer notes — finalized | TBD | |
| Legal review of description claims | TBD | |
