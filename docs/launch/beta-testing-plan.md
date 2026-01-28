# NTRL Beta Testing Plan

> Last updated: January 2026
> Status: Draft. Timeline and tooling decisions marked [TBD] require founder input.

---

## 1. Beta Strategy

NTRL will use the native beta distribution platforms for both iOS and Android:

| Platform | Distribution | Limit | Notes |
|----------|-------------|-------|-------|
| **iOS** | Apple TestFlight | Up to 10,000 external testers | Requires App Store Connect setup, beta app review |
| **Android** | Google Play Internal/Closed Testing | No hard limit | Requires Play Console setup, signed APK/AAB |

**Why native platforms:**
- No additional infrastructure required
- Users get a near-production experience
- Automatic update distribution
- Crash reporting built in (TestFlight analytics, Play Console vitals)
- Familiar to testers — low friction to join

---

## 2. Beta Phases

### Phase A: Alpha (Internal Testing)

| Detail | Value |
|--------|-------|
| **Testers** | 5-10 people (founder, close collaborators, trusted friends) |
| **Duration** | [TBD — founder input needed. Suggested: 1-2 weeks] |
| **Goal** | Catch critical bugs, validate core experience, confirm pipeline output quality |
| **Entry criteria** | App builds successfully for iOS and Android, staging backend stable, pipeline running on schedule |
| **Exit criteria** | No P0/P1 bugs open, all 10 categories populated, transparency view functional, basic navigation works |

**Alpha testing checklist:**
- [ ] App installs and launches without crash (iOS + Android)
- [ ] All 10 feed categories display articles
- [ ] Articles load and display correctly (title, source, date, body)
- [ ] Transparency view shows color-coded highlights
- [ ] Highlights legend is accessible and accurate
- [ ] Original source link works
- [ ] Dark mode displays correctly
- [ ] Pull-to-refresh works
- [ ] Navigation between screens is smooth (TodayScreen, SectionsScreen, ArticleDetailScreen)
- [ ] No personally identifiable information exposed in UI or network traffic
- [ ] App handles network errors gracefully (airplane mode, poor signal)

### Phase B: Closed Beta (Invited Users)

| Detail | Value |
|--------|-------|
| **Testers** | 50-100 invited users |
| **Duration** | [TBD — founder input needed. Suggested: 2-4 weeks] |
| **Goal** | Validate content quality with real users, identify UX friction, stress-test with more device diversity |
| **Entry criteria** | Alpha exit criteria met, feedback mechanism in place |
| **Exit criteria** | NPS baseline established, no P0/P1 bugs, content quality feedback is positive or actionable |

**Tester recruitment sources:**
- [TBD] Personal network
- [TBD] Media literacy communities
- [TBD] Twitter/X followers, newsletter subscribers
- [TBD] Reddit communities (r/media_criticism, r/journalism, r/technology)
- [TBD] Product Hunt "coming soon" page waitlist

**Closed beta feedback areas:**
- Content quality: "Does the neutralized version feel accurate and fair?"
- Reading experience: "Is the app pleasant to read? Is the design calming?"
- Comprehension: "Do you understand what NTRL does after using it for 5 minutes?"
- Transparency view: "Is the highlight system clear and useful?"
- Missing content: "Are there categories or sources you expected but did not see?"
- Bugs: Device-specific rendering issues, performance problems

### Phase C: Open Beta (Public)

| Detail | Value |
|--------|-------|
| **Testers** | 500+ (open enrollment via TestFlight public link / Play Store open testing) |
| **Duration** | [TBD — founder input needed. Suggested: 2-4 weeks] |
| **Goal** | Scale testing, validate infrastructure under load, build pre-launch community |
| **Entry criteria** | Closed beta exit criteria met, subscription billing ready or explicitly deferred |
| **Exit criteria** | Retention metrics meet target, performance stable at scale, App Store submission ready |

**Open beta distribution:**
- TestFlight public link (shareable URL)
- Play Store open testing track
- Landing page with signup
- Social media announcement
- Product Hunt "coming soon" → "launching" transition

---

## 3. Testing Focus Areas

### 3.1 Content Quality (Neutralization Accuracy)

This is the most critical test area. If users do not trust the neutralized content, nothing else matters.

| Test | Method | Success Criteria |
|------|--------|-----------------|
| Neutralization preserves meaning | Tester reads original + neutralized, confirms same information | >90% of testers agree meaning is preserved |
| Manipulative language removed | Tester identifies emotional/biased language in original, confirms removal | >85% of flagged items are addressed |
| No new bias introduced | Tester checks neutralized version for new political/emotional slant | <5% of testers report introduced bias |
| Classification accuracy | Spot-check highlighted spans against 14 categories | Matches align with category definitions |
| Long article handling | Test articles >8,000 characters | Known limitation — document user perception |

### 3.2 UI/UX (Calm Design, Readability, Dark Mode)

| Test | Method | Success Criteria |
|------|--------|-----------------|
| Calm reading experience | Tester rates "how does reading NTRL feel?" on 1-5 scale | Average >= 4.0 |
| Dark mode correctness | Test all screens in dark mode | No white flashes, no unreadable text, no missing elements |
| Font readability | Test across device sizes | Text legible on smallest supported device |
| Navigation clarity | Tester finds specific content within 3 taps | >90% success rate |
| Transparency view usability | Tester explains what highlights mean after first use | >80% can explain correctly |

### 3.3 Performance

| Test | Method | Success Criteria |
|------|--------|-----------------|
| Initial load time | Measure time from app open to content visible | <3 seconds on 4G |
| Feed refresh time | Measure pull-to-refresh completion | <2 seconds |
| Article detail load | Measure tap-to-content time | <1 second |
| Transparency view load | Measure time for highlights to render | <2 seconds |
| Memory usage | Monitor via Xcode Instruments / Android Profiler | No memory leaks, <200MB peak |
| Battery impact | Monitor during 30-minute reading session | No abnormal battery drain |

### 3.4 Feed Category Coverage

| Category | Test |
|----------|------|
| Top Stories | Articles present and recent (<24 hours) |
| U.S. | Articles present and relevant |
| World | Articles present with geographic diversity |
| Business | Articles present |
| Technology | Articles present |
| Science | Articles present (may be lower volume) |
| Health | Articles present |
| Sports | Articles present |
| Entertainment | Articles present |
| Environment | Articles present (may be lower volume) |

**Goal:** All 10 categories have at least 3 articles at any given time. If a category is persistently empty, investigate source coverage.

### 3.5 Transparency View

| Test | Method | Success Criteria |
|------|--------|-----------------|
| Highlights render correctly | Visual inspection across devices | Colors visible, text readable beneath highlights |
| Legend displays all categories | Open legend, count categories | All 14 categories listed with descriptions |
| Tap-to-reveal works | Tap highlighted text, verify category popup | Correct category shown |
| Color accessibility | Test with color blindness simulator | Distinguishable patterns for common color blindness types |
| Performance with many highlights | Load article with 50+ highlighted spans | No lag or rendering issues |

---

## 4. Feedback Methodology

### Feedback Collection Tools

[TBD — founder input needed. Select one primary tool for structured feedback.]

| Option | Pros | Cons | Cost |
|--------|------|------|------|
| **Typeform** | Beautiful forms, branching logic | Limited free tier | Free tier or ~$25/month |
| **Google Forms** | Free, simple, familiar | Less polished, no branching | Free |
| **Tally** | Free, modern, branching logic | Newer/less known | Free |
| **In-app feedback (custom)** | Lowest friction, device info auto-attached | Requires development time | Dev time only |
| **TestFlight feedback** | Built into iOS TestFlight | iOS only, limited structure | Free |

### Feedback Cadence

| Phase | Feedback Request |
|-------|-----------------|
| Alpha | Daily check-in via group chat (Slack/Discord/iMessage) |
| Closed Beta | Survey at Day 1, Day 7, Day 14. Plus open feedback channel. |
| Open Beta | Survey at Day 1, Day 7. In-app feedback prompt at Day 3. |

### Survey Structure

**Day 1 Survey (First Impressions):**
1. Did the app install and launch without issues? (Y/N)
2. How would you describe NTRL to a friend in one sentence? (Open text — tests comprehension)
3. Rate your first reading experience (1-5 scale)
4. Was the purpose of the Transparency view clear? (Y/N)
5. Any bugs or issues? (Open text)

**Day 7 Survey (Engagement):**
1. How many days this week did you open NTRL? (0-7)
2. Has NTRL changed how you think about news? (Open text)
3. Rate content quality (1-5)
4. Rate reading experience (1-5)
5. What is missing? (Open text)
6. How likely are you to recommend NTRL to a friend? (0-10 NPS scale)

**Day 14 Survey (Retention):**
1. Are you still using NTRL? (Y/N, if N — why not?)
2. Would you pay for NTRL? (Y/N, if Y — how much per month?)
3. What is the single most important improvement? (Open text)
4. NPS score (0-10)

---

## 5. Success Metrics

[TBD — founder input needed for specific targets. Suggested framework below.]

### Quantitative Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Day 1 retention** | [TBD — suggest >60%] | % of testers who open app on Day 2 |
| **Day 7 retention** | [TBD — suggest >30%] | % of testers who open app on Day 7 |
| **Day 14 retention** | [TBD — suggest >20%] | % of testers who open app on Day 14 |
| **NPS (Net Promoter Score)** | [TBD — suggest >30] | Average NPS from Day 7 + Day 14 surveys |
| **Crash-free rate** | >99% | TestFlight + Play Console crash reports |
| **Content quality rating** | >4.0/5.0 | Average from surveys |
| **Reading experience rating** | >4.0/5.0 | Average from surveys |

### Qualitative Metrics

| Signal | Good | Concerning |
|--------|------|-----------|
| Comprehension | Testers can explain NTRL in their own words | Testers confused about what NTRL does |
| Trust | Testers describe content as "fair" or "neutral" | Testers describe content as "wrong" or "biased the other way" |
| Habit | Testers report checking NTRL daily | Testers forget about the app |
| Evangelism | Testers ask for invite links to share | Testers do not mention NTRL to anyone |
| Transparency view | Testers find it "eye-opening" or "educational" | Testers find it "confusing" or "overwhelming" |

### Bug Severity Thresholds

| Severity | Definition | Beta Gate |
|----------|-----------|-----------|
| **P0 — Critical** | App crashes, data loss, security issue | Must fix before next phase |
| **P1 — Major** | Feature broken, incorrect content displayed | Must fix before public launch |
| **P2 — Moderate** | UI glitch, minor functionality issue | Track, fix before or shortly after launch |
| **P3 — Minor** | Cosmetic, edge case, nice-to-have | Log for future sprint |

**Phase gate rule:** No open P0 or P1 bugs to advance to the next phase.

---

## 6. Timeline

[TBD — founder input needed for all dates.]

| Milestone | Target Date | Prerequisites |
|-----------|-------------|---------------|
| TestFlight build ready | [TBD] | App builds, staging backend stable |
| Play Store internal testing build ready | [TBD] | App builds, staging backend stable |
| Alpha start | [TBD] | Builds distributed to 5-10 testers |
| Alpha complete | [TBD] | Exit criteria met |
| Closed beta start | [TBD] | Alpha exit, feedback tooling ready |
| Closed beta complete | [TBD] | Exit criteria met |
| Open beta start | [TBD] | Closed beta exit, public TestFlight link live |
| Open beta complete | [TBD] | Retention + quality targets met |
| App Store submission | [TBD] | All beta phases complete, legal docs finalized |

---

## 7. Logistics Checklist

### Pre-Alpha
- [ ] Apple Developer account active and configured
- [ ] Google Play Developer account active and configured
- [ ] App Store Connect app listing created (name, bundle ID, etc.)
- [ ] Play Console app listing created
- [ ] TestFlight build uploaded and processing
- [ ] Play Store internal testing track configured
- [ ] Staging backend stable and pipeline running on schedule
- [ ] Feedback collection tool selected and configured [TBD]
- [ ] Beta tester communication channel set up [TBD — Slack, Discord, email list]

### Pre-Closed Beta
- [ ] Alpha feedback reviewed and critical issues addressed
- [ ] Tester recruitment complete (50-100 invites sent)
- [ ] Day 1 survey prepared
- [ ] Onboarding messaging prepared (email or in-app explaining what to test)

### Pre-Open Beta
- [ ] Closed beta feedback reviewed and critical issues addressed
- [ ] TestFlight public link generated
- [ ] Play Store open testing track configured
- [ ] Landing page updated with beta signup
- [ ] Social media announcement drafted
- [ ] Day 1 + Day 7 surveys prepared
