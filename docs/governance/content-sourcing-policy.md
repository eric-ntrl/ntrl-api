# NTRL Content Sourcing Policy

> Last updated: January 2026
> Status: Internal policy document. Legal sections marked [TBD] require attorney review.

---

## 1. Source Selection Principles

NTRL aggregates and neutralizes news content from third-party sources. The following principles govern which sources are included:

### 1.1 Diversity of Perspective
NTRL deliberately includes sources from across the political and editorial spectrum. This is not an accident — it is a core design principle. The product's value comes from neutralizing *all* manipulative language regardless of source, not from curating only "good" sources.

### 1.2 Established Editorial Standards
Sources must have an identifiable editorial organization — a newsroom, editorial staff, or established publication history. Individual blogs, anonymous outlets, and social media accounts are not included as primary sources.

### 1.3 Publicly Available RSS Feeds
NTRL only ingests content from sources that publish public RSS/Atom feeds. We do not scrape proprietary or paywalled feed endpoints. If a source removes or restricts its RSS feed, NTRL will deactivate that source.

### 1.4 Deliberate Inclusion of High-Manipulation Sources
Some sources are included *specifically because* they use manipulative language heavily. This is intentional. NTRL's pipeline is designed to detect and neutralize manipulation — tabloid and partisan sources provide valuable test cases and demonstrate the product's capabilities. Excluding them would undermine the product's purpose.

---

## 2. Current Source Categories

### Wire Services
- **Associated Press (AP)** — Global wire service, generally considered high-factual, low-manipulation baseline.
- **Reuters** — Global wire service, similar profile to AP.

**Role in NTRL:** Provide factual baseline content. Often require minimal neutralization, which demonstrates that the pipeline does not "over-correct" neutral content.

### Broadsheets / Major Outlets
- **The New York Times (NYT)** — US broadsheet, center-left editorial perspective.
- **BBC News** — UK public broadcaster, global coverage.
- **The Guardian** — UK broadsheet, left-leaning editorial perspective.

**Role in NTRL:** High-quality journalism that may still contain framing bias, emotionally loaded language, or editorial slant in news coverage (distinct from opinion pieces).

### Tabloids
- **Daily Mail** — UK tabloid, right-leaning, high sensationalism.
- **New York Post** — US tabloid, right-leaning, high sensationalism.
- **The Sun** — UK tabloid, high sensationalism.

**Role in NTRL:** Deliberately included for high-manipulation content. These sources frequently use emotionally loaded language, sensationalism, inflammatory headlines, and other manipulation techniques. They are critical for demonstrating NTRL's neutralization capabilities and ensuring the pipeline performs well on the most challenging content. Their inclusion is a feature, not an oversight.

### Technology / Business
- **TechCrunch** — Technology news, generally moderate.
- **Bloomberg** — Business and financial news, generally moderate.

**Role in NTRL:** Coverage for the Technology and Business feed categories. May contain industry hype, promotional language, or market sensationalism.

### Source Expansion (Planned)
Additional sources will be added over time to improve category coverage and geographic diversity. Priority areas:
- Additional US sources across the political spectrum
- International English-language sources (India, Australia, South Africa, etc.)
- Science and health-focused outlets
- Sports-focused outlets
- Environment and climate outlets

---

## 3. RSS Feed Requirements

All sources must meet the following technical requirements:

| Requirement | Detail |
|-------------|--------|
| **Public accessibility** | Feed URL must be accessible without authentication |
| **SSL/TLS** | Feed must be served over HTTPS |
| **Valid format** | Must be valid RSS 2.0, Atom 1.0, or compatible variant |
| **Parseable** | Feed must be parseable by standard RSS libraries (feedparser) |
| **Content sufficient** | Feed items must include at minimum: title, link, publication date |
| **Update frequency** | Feed should update at least daily for inclusion in active rotation |
| **Stable URL** | Feed URL should not change frequently (breaks ingestion) |

### Feed Validation Process
Before adding a new source:
1. Verify feed URL is accessible and returns valid XML
2. Parse feed and confirm required fields are present
3. Verify article body is scrapeable from the linked URL
4. Test 5-10 articles through the full pipeline (INGEST through BRIEF ASSEMBLE)
5. Review neutralization quality on test articles
6. Add via POST /v1/sources API with appropriate category mapping

---

## 4. Fair Use Position

> **IMPORTANT: This section outlines NTRL's intended legal position. It is NOT legal advice and has NOT been reviewed by an attorney. [TBD — needs legal counsel before public launch.]**

### How NTRL Uses Source Content

| Step | What Happens |
|------|-------------|
| **Ingestion** | NTRL reads publicly available RSS feeds (titles, summaries, links). This is equivalent to what any RSS reader does. |
| **Body retrieval** | NTRL follows the public article URL and extracts the article body text. This is equivalent to what a web browser does when a user visits the page. |
| **Neutralization** | NTRL's AI pipeline rewrites sentences that contain manipulative language, producing a new version of the article with the same factual information but neutral tone. |
| **Attribution** | Every NTRL article displays the source name prominently and includes a direct link to the original article. |
| **No full reproduction** | NTRL does not reproduce articles verbatim. The neutralized version is a derivative work with substantial transformation. |

### Transformative Use Argument

NTRL's position is that neutralized articles constitute **transformative use** under fair use doctrine (17 U.S.C. Section 107) because:

1. **Purpose and character of use:** NTRL's purpose (removing manipulative language for reader well-being) is fundamentally different from the original purpose (informing while engaging readers). The transformation adds new meaning — making manipulation visible and removing it.

2. **Nature of the copyrighted work:** News articles are factual works. Fair use provides broader latitude for factual works than creative works.

3. **Amount used:** NTRL uses the full text of articles but transforms it substantially. The factual information is preserved; the expression is rewritten.

4. **Effect on the market:** NTRL links back to original sources, driving traffic rather than replacing it. NTRL does not compete in the same market — it serves a different purpose (manipulation removal) for a different audience (news-fatigued consumers).

### Legal Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Copyright infringement claim from publisher | High impact, medium probability | Transformative use argument, attribution, linking. [TBD — attorney review needed] |
| DMCA takedown request | Medium impact, medium probability | Comply promptly, establish takedown process. [TBD — needs DMCA agent registration] |
| Terms of service violation (specific publisher) | Low-medium impact | Review ToS of each source. [TBD — systematic review needed] |
| Cease-and-desist from source | Medium impact | Negotiate or remove source. Deactivation process preserves data integrity. |

### Actions Required Before Launch

- [ ] [TBD] Retain intellectual property attorney for fair use opinion
- [ ] [TBD] Register DMCA agent with U.S. Copyright Office
- [ ] [TBD] Review terms of service for each current source
- [ ] [TBD] Establish content takedown procedure and response timeline
- [ ] [TBD] Draft response template for publisher inquiries
- [ ] [TBD] Consider proactive outreach to key publishers (AP, Reuters, NYT) to establish relationship

---

## 5. Source Diversity Standards

NTRL maintains diversity across three dimensions:

### Political Spectrum Coverage
NTRL must include sources from across the political spectrum. No single political perspective should dominate the feed.

| Perspective | Current Sources | Target |
|-------------|----------------|--------|
| Left-leaning | The Guardian | At least 2 sources |
| Center-left | NYT, BBC | At least 2 sources |
| Center | AP, Reuters, Bloomberg | At least 2 sources |
| Center-right | [TBD — source needed] | At least 1 source |
| Right-leaning | Daily Mail, NY Post | At least 2 sources |

[TBD — need to add center-right sources for balance. Consider: Wall Street Journal, Financial Times, The Economist.]

### Geographic Diversity
Sources should represent multiple countries and regions within the English-speaking world.

| Region | Current Sources | Target |
|--------|----------------|--------|
| United States | NYT, NY Post, AP, TechCrunch, Bloomberg | Represented |
| United Kingdom | BBC, Guardian, Daily Mail, The Sun, Reuters | Represented |
| Australia | None | [TBD — add at least 1 source] |
| Canada | None | [TBD — add at least 1 source] |
| India (English) | None | [TBD — add at least 1 source] |
| Other | None | [TBD — as sources are identified] |

### Topic Diversity
Sources should collectively cover all 10 feed categories. If a category is persistently underserved, additional specialized sources should be added.

| Category | Primary Sources | Adequacy |
|----------|----------------|----------|
| Top Stories | All sources | Adequate |
| U.S. | AP, NYT, NY Post | Adequate |
| World | Reuters, BBC, Guardian | Adequate |
| Business | Bloomberg, Reuters | Adequate |
| Technology | TechCrunch, Bloomberg | Adequate |
| Science | [General sources] | May need specialist source |
| Health | [General sources] | May need specialist source |
| Sports | [General sources] | May need specialist source |
| Entertainment | [General sources] | May need specialist source |
| Environment | [General sources] | May need specialist source |

---

## 6. Source Addition / Removal Process

### Adding a New Source

1. **Identify candidate source** — Must meet selection principles (Section 1) and RSS requirements (Section 3).
2. **Validate RSS feed** — Confirm feed is accessible, valid, and contains required fields.
3. **Test pipeline** — Run 5-10 articles through the full 4-stage pipeline. Review neutralization output quality.
4. **Category mapping** — Determine which of the 10 feed categories the source primarily serves.
5. **Add via API** — `POST /v1/sources` with source name, feed URL, category mapping, and active status.
6. **Monitor** — Watch for ingestion errors, scraping failures, or quality issues for the first 48 hours.
7. **Document** — Update this policy document with the new source.

### Removing / Deactivating a Source

**CRITICAL: Sources are deactivated, never deleted.** Deletion would break referential integrity for existing articles.

1. **Determine reason for removal** — Feed broken, legal request, quality concerns, editorial decision.
2. **Deactivate via API** — Set source to inactive status. Existing articles remain but no new content is ingested.
3. **Document reason** — Record why the source was deactivated and when.
4. **Consider replacement** — If removal creates a gap in political spectrum, geographic, or topic diversity, identify a replacement source.

### Emergency Source Removal

In the event a source publishes content that is dangerous, libelous, or otherwise creates immediate risk:
1. Deactivate source immediately
2. Review recent articles from that source in NTRL
3. If necessary, manually flag or remove specific articles
4. Document incident
5. [TBD — escalation to legal counsel if needed]

---

## 7. Transparency to Users

NTRL is transparent about its sources:

| Principle | Implementation |
|-----------|---------------|
| **Source attribution** | Source name is displayed prominently on every article in the app |
| **Original link** | Every article includes a direct link to the original source URL |
| **No hidden sources** | We do not obscure or anonymize where content comes from |
| **Neutralization visible** | The Transparency view shows exactly what was changed, making our editorial process fully auditable by any reader |

### What We Do Not Share
- Internal source selection criteria (this document is internal)
- Per-source manipulation statistics (could be perceived as attacking specific outlets)
- Source performance metrics (ingestion rates, failure rates)

---

## 8. Review Schedule

This policy should be reviewed:
- Quarterly (or when sources are added/removed)
- After any legal communication from a source
- Before any public launch milestone
- When expanding to new markets or languages
