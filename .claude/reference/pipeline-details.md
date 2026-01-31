# Pipeline Details Reference

Detailed technical reference for NTRL pipeline internals. See main CLAUDE.md for quick reference.

## Classification Pipeline

### Flow
```
StoryRaw → fetch body (first 2000 chars) → LLM classify → domain_mapper → update StoryRaw
```

### Reliability Chain (4 attempts)
1. gpt-4o-mini with full prompt (JSON mode)
2. gpt-4o-mini with simplified prompt
3. gemini-2.0-flash with full prompt
4. Enhanced keyword classifier (flagged as `keyword_fallback`)

### Enums

**Domain** (20 internal): `global_affairs`, `governance_politics`, `law_justice`, `security_defense`, `crime_public_safety`, `economy_macroeconomics`, `finance_markets`, `business_industry`, `labor_demographics`, `infrastructure_systems`, `energy`, `environment_climate`, `science_research`, `health_medicine`, `technology`, `media_information`, `sports_competition`, `society_culture`, `lifestyle_personal`, `incidents_disasters`

**FeedCategory** (10 user-facing): `world`, `us`, `local`, `business`, `technology`, `science`, `health`, `environment`, `sports`, `culture`

### Domain → Feed Category
- 15 domains map directly regardless of geography
- 5 domains are geography-dependent: `governance_politics`, `law_justice`, `security_defense`, `crime_public_safety`, `incidents_disasters`

## Span Detection

### How it Works
1. Title + body combined: `HEADLINE: {title}\n\n---ARTICLE BODY---\n\n{body}`
2. LLM returns `{"phrases": [...]}` with manipulative phrases
3. `find_phrase_positions()` maps phrase text to char positions
4. Position adjustment separates spans by field (title/body)
5. `filter_spans_in_quotes()` removes quoted speech
6. `filter_false_positives()` removes known FPs (crisis management, etc.)

### Manipulation Taxonomy (14 categories)
1. URGENCY INFLATION: BREAKING, scrambling
2. EMOTIONAL TRIGGERS: shocking, devastating, slams
3. CLICKBAIT: You won't believe
4. SELLING/HYPE: revolutionary, game-changer
5. AGENDA SIGNALING: radical left, extremist
6. LOADED VERBS: slammed, blasted, admits
7. URGENCY (subtle): Act now
8. AGENDA FRAMING: "the crisis at the border"
9. SPORTS/EVENT HYPE: brilliant, blockbuster
10. LOADED PERSONAL DESCRIPTORS: handsome, menacing
11. HYPERBOLIC ADJECTIVES: punishing, "of the year"
12. LOADED IDIOMS: came under fire, took aim at
13. CELEBRITY HYPE: romantic escape, A-list pair
14. EDITORIAL VOICE: we're glad, Border Czar, lunatic

### SpanReason enum values
`clickbait`, `urgency_inflation`, `emotional_trigger`, `selling`, `agenda_signaling`, `rhetorical_framing`, `editorial_voice`

### Quote Filtering
Uses Unicode escapes to avoid editor corruption:
```python
QUOTE_PAIRS = {
    '"': '"',           # Straight (U+0022)
    '\u201c': '\u201d', # Curly double (U+201C → U+201D)
    "'": "'",           # Straight (U+0027)
    '\u2018': '\u2019', # Curly single (U+2018 → U+2019)
}
```

## Debug Endpoints

### `/v1/stories/{id}/debug`
- `original_body`: First 500 chars from S3
- `detail_full`: First 500 chars neutralized
- `issues`: Detected problems
- `span_count`, `spans_sample`

### `/v1/stories/{id}/debug/spans`
- `llm_raw_response`: Raw JSON from LLM
- `pipeline_trace`: Position matching, quote filter, FP filter counts
- `final_spans`: Final spans with positions

## Cost-Efficient Testing

1. Use `story_ids` param: `{"story_ids": ["id1", "id2"], "force": true}`
2. Test via `/debug/spans` first (no DB save)
3. Pick 5-10 representative articles per prompt change
4. Target high-manipulation sources (The Sun, Daily Mail)

## Key Files

| File | Purpose |
|------|---------|
| `neutralizer/__init__.py` | Main service, synthesis fallback |
| `neutralizer/spans.py` | `find_phrase_positions()`, quote filtering |
| `llm_classifier.py` | Article classification |
| `domain_mapper.py` | Domain → feed_category mapping |
| `brief_assembly.py` | Groups by feed_category |

## Neutralization Status

| Status | Meaning |
|--------|---------|
| `success` | Displayed to users |
| `failed_llm` | LLM API failed |
| `failed_garbled` | Output unreadable |
| `failed_audit` | Failed quality check |
| `skipped` | Not processed |

## Highlight Colors (Frontend)

| Category | Color |
|----------|-------|
| emotional_trigger | Blue |
| urgency_inflation | Rose |
| editorial_voice | Lavender |
| default | Gold |
