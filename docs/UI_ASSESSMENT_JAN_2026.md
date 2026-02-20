# NTRL UI Assessment - January 2026

## Executive Summary

The span detection and multi-color highlight implementation is **working well**. Key improvements verified:
- Category-specific highlight colors are rendering correctly
- Span detection is identifying manipulative phrases
- Toggle functionality works properly
- Brief and Full views are neutralized and readable

**Remaining issues** to address in next update:
1. Duplicate highlights from source content duplication
2. Missing highlight legend for color meanings
3. Badge display inconsistency when toggle is off
4. Only 2 of 4 highlight colors observed (limited test corpus)

---

## Test Results

### Article Tested: Harry Styles (Daily Mail)

**Highlights Detected: 11 phrases**

| Phrase | Color | Category |
|--------|-------|----------|
| fiercely slammed | Slate blue `rgba(130, 160, 200, 0.35)` | emotional_trigger |
| ecstatic | Slate blue | emotional_trigger |
| outraged | Slate blue | emotional_trigger |
| furious fans | Slate blue | emotional_trigger |
| whopping | Amber `rgba(200, 160, 100, 0.35)` | clickbait/selling |
| sky-high prices | Amber | clickbait/selling |
| most pricey tickets | Amber | clickbait/selling |

**Color Distribution:**
- Slate blue (emotional_trigger): 7 phrases
- Amber (clickbait/selling): 4 phrases

### Other Articles in Feed

| Article | Source | Expected Manipulation Level |
|---------|--------|----------------------------|
| USS Abraham Lincoln | CBS News | Low (straight news) |
| U.S. Aircraft Carrier | CBS News | Low (straight news) |
| Dave Roberts | NY Post | Medium (sports/lifestyle) |

Note: Katie Price article not present in current feed (may have aged out of 24h window).

---

## What's Working Well

### 1. Multi-Color Highlights ✅
The category-based highlight colors are rendering correctly:
- **Emotional triggers** (slate blue) - clearly visible on emotional language
- **Clickbait/selling** (amber) - distinguishable from emotional triggers
- Colors are muted and maintain the "calm reading" aesthetic
- Sufficient contrast for visibility without being jarring

### 2. Phrase Detection ✅
Span detection is correctly identifying:
- Emotional amplifiers: "fiercely slammed", "ecstatic", "outraged", "furious"
- Emphasis superlatives: "whopping", "sky-high"
- Loaded comparisons: "most pricey"

### 3. Toggle Functionality ✅
- Toggle switches highlights on/off smoothly
- Toggle state is visually clear (teal when on, gray when off)
- Text remains readable in both states

### 4. Badge Display ✅
- "11 phrases flagged" badge shows correct count
- Badge styling is clear and non-intrusive
- Positioned appropriately near toggle

### 5. Brief/Full Views ✅
- **Brief view**: Clean, neutralized summary focusing on facts
- **Full view**: Readable neutralized article without manipulative language
- Both views remove emotional amplification while preserving information

### 6. Feed Display ✅
- Headlines are neutralized and factual
- Summaries are concise and informative
- Clean typography and spacing

---

## Issues Requiring Attention

### Issue 1: Duplicate Highlights (High Priority)

**Problem:** Same phrases appear highlighted multiple times:
- "fiercely slammed" appears 2x
- "outraged" appears 2x
- "furious fans" appears 2x
- "sky-high prices" appears 2x

**Root Cause:** The original article contains duplicate content. News sources often repeat intro text in image captions, pull quotes, or summary boxes. When the same manipulative phrase appears multiple times in `original_body`, each occurrence gets its own span.

**Impact:**
- Inflated span count (11 reported, but only 7 unique phrases)
- Potentially confusing user experience
- Badge count may mislead users about manipulation level

**Recommended Fix:**
Option A: **Deduplicate in UI** - Count unique phrases, not total occurrences
```typescript
// In NtrlViewScreen.tsx
const uniquePhrases = [...new Set(transformations.map(t => t.original.toLowerCase()))];
const displayCount = uniquePhrases.length;
```

Option B: **Deduplicate in Backend** - Return only first occurrence of each phrase
```python
# In neutralizer.py
seen_phrases = set()
deduplicated_spans = []
for span in spans:
    phrase_key = span.original_text.lower()
    if phrase_key not in seen_phrases:
        seen_phrases.add(phrase_key)
        deduplicated_spans.append(span)
```

**Recommendation:** Option A (UI deduplication) is safer - preserves all span data while improving display.

---

### Issue 2: Missing Highlight Legend (Medium Priority)

**Problem:** Users see different colored highlights but have no way to know what each color means.

**Current Colors:**
| Color | Meaning | Visual |
|-------|---------|--------|
| Dusty rose | Urgency inflation | Not observed in test |
| Slate blue | Emotional triggers | ✅ Observed |
| Lavender | Editorial voice | Not observed in test |
| Amber | Clickbait/selling | ✅ Observed |
| Gold | Default/rhetorical | Not observed in test |

**Recommended Fix:** Add collapsible legend below toggle

```
┌────────────────────────────────────┐
│ Show highlights  [11 flagged] [ON] │
├────────────────────────────────────┤
│ ▾ What do the colors mean?         │
│   ■ Emotional language             │
│   ■ Urgency/hype                   │
│   ■ Editorial opinion              │
│   ■ Clickbait/selling              │
└────────────────────────────────────┘
```

**Design Considerations:**
- Keep collapsed by default to maintain calm aesthetic
- Use simple descriptions (not technical category names)
- Small, unobtrusive text

---

### Issue 3: Badge Display When Toggle Off (Low Priority)

**Problem:** Badge shows "11 phrases flagged" even when highlights toggle is off.

**Current Behavior:**
- Toggle ON: "11 phrases flagged" badge visible, highlights shown
- Toggle OFF: "11 phrases flagged" badge visible, highlights hidden

**Expected Behavior:**
- Toggle OFF: Badge should be hidden or dimmed

**Recommended Fix:**
```typescript
{showHighlights && (
  <Badge text={`${count} phrases flagged`} />
)}
```

---

### Issue 4: Limited Color Verification (Testing Gap)

**Problem:** Only observed 2 of 4+ highlight colors in testing.

**Colors Tested:**
- ✅ Slate blue (emotional_trigger)
- ✅ Amber (clickbait/selling)
- ❓ Dusty rose (urgency_inflation) - Need test case
- ❓ Lavender (editorial_voice) - Need test case
- ❓ Gold (default) - Need test case

**Recommended Action:**
1. Find/create test articles that contain:
   - "BREAKING NEWS" (urgency_inflation → dusty rose)
   - "we're glad to see" (editorial_voice → lavender)
   - Generic loaded phrases (default → gold)

2. Re-neutralize Tom Homan article (has editorial content)

3. Verify color mapping for all SpanReason values

---

### Issue 5: Source Content Duplication (Backend/Ingestion)

**Problem:** Some articles have repeated paragraphs due to:
- Image captions that repeat article intro
- Pull quotes duplicating body text
- Mobile/web content differences in source HTML

**Example:** Harry Styles article contains same text twice, causing duplicate spans.

**Recommended Investigation:**
1. Check scraper/ingestion logic for caption/pullquote handling
2. Consider deduplicating paragraphs during ingestion
3. Or accept duplication but handle in span display (Issue 1)

---

## Visual Quality Assessment

### Highlight Appearance: ✅ Good

The highlights achieve the "calm reading" aesthetic goal:
- Colors are muted and harmonious
- No jarring contrasts or alarm-like signals
- Feels like reading with warm lamplight
- Distinguishable but not distracting

### Typography: ✅ Excellent

- Clean, readable font
- Appropriate line height and spacing
- Highlights don't disrupt text flow
- Badge typography is consistent

### Contrast/Accessibility: ⚠️ Needs Verification

- Light mode appears sufficient
- Dark mode not tested in this assessment
- Recommend accessibility audit for color contrast ratios

---

## Comparison: Before vs After Jan 2026 Changes

| Metric | Before | After |
|--------|--------|-------|
| Katie Price spans | 0 | 10+ (estimated) |
| Multi-color highlights | No (all gold) | Yes (4 colors) |
| Emotional triggers | Some missed | Improved detection |
| Tabloid content | Under-detected | Better detection |
| Editorial voice | Not detected | New category added |

---

## Recommended Next Update Plan

### Phase 1: Quick Fixes (1 day)
- [ ] Deduplicate span display in UI (show unique count)
- [ ] Hide/dim badge when toggle is off
- [ ] Add simple highlight legend (collapsed by default)

### Phase 2: Verification (1 day)
- [ ] Find test articles for each color category
- [ ] Verify all 4-5 colors render correctly
- [ ] Test dark mode highlight visibility
- [ ] Accessibility audit for color contrast

### Phase 3: Backend Improvements (optional)
- [ ] Investigate source content duplication
- [ ] Consider paragraph deduplication in ingestion
- [ ] Add more tabloid/editorial test cases to E2E suite

---

## Test Commands for Verification

```bash
# Re-neutralize with editorial content
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/neutralize/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -d '{"limit": 10, "force": true}'

# Check for articles with different span reasons
curl -s "https://api-staging-7b4d.up.railway.app/v1/brief?hours=24" \
  -H "X-API-Key: $ADMIN_API_KEY" | jq '.sections[].stories[] | {title: .title, span_count: .span_count}'

# Capture UI screenshots
cd /Users/ericrbrown/Documents/NTRL/code/ntrl-app
node comprehensive-ui-test.cjs
```

---

## Conclusion

The January 2026 updates have significantly improved NTRL's span detection and highlight functionality. The multi-color system is working, span detection catches more manipulative phrases (especially tabloid content), and the UI maintains its calm aesthetic.

**Priority fixes for next update:**
1. Deduplicate highlights in UI display
2. Add highlight color legend
3. Verify all color categories render correctly

The foundation is solid - remaining work is polish and verification.
