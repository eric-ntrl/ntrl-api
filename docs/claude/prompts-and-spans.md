# Prompts and Span Detection Reference

> Quick reference for LLM prompts and span detection. Full details in `../../.claude/reference/pipeline-details.md`.

## Prompt Management

Prompts are stored in the database with version history.

### Key Properties
- **Hot-reload**: Changes take effect without deploy
- **Versioned**: Full history retained
- **DB-backed**: Managed via `/v1/prompts` endpoints

### Slash Commands

| Command | Purpose |
|---------|---------|
| `/prompt` | View/update pipeline prompts |
| `/prompt list` | List all prompts |
| `/prompt show <name>` | Show prompt content |
| `/prompt update <name>` | Update prompt text |

### After Prompt Changes

```
/classify force → /brief rebuild → /evaluate
```

## Span Detection Pipeline

### How It Works

1. **Input**: Title + body combined
   ```
   HEADLINE: {title}

   ---ARTICLE BODY---

   {body}
   ```

2. **LLM Response**: `{"phrases": [...]}`

3. **Position Matching**: `find_phrase_positions()` maps text to char positions

4. **Field Separation**: Spans tagged as `field: "title"` or `field: "body"`

5. **Quote Filtering**: `filter_spans_in_quotes()` removes quoted speech

6. **FP Filtering**: `filter_false_positives()` removes known false positives

### 14 Manipulation Categories

| # | Category | Examples |
|---|----------|----------|
| 1 | Urgency Inflation | BREAKING, scrambling |
| 2 | Emotional Triggers | shocking, devastating, slams |
| 3 | Clickbait | You won't believe |
| 4 | Selling/Hype | revolutionary, game-changer |
| 5 | Agenda Signaling | radical left, extremist |
| 6 | Loaded Verbs | slammed, blasted, admits |
| 7 | Urgency (subtle) | Act now |
| 8 | Agenda Framing | "the crisis at the border" |
| 9 | Sports/Event Hype | brilliant, blockbuster |
| 10 | Loaded Personal Descriptors | handsome, menacing |
| 11 | Hyperbolic Adjectives | punishing, "of the year" |
| 12 | Loaded Idioms | came under fire, took aim at |
| 13 | Celebrity Hype | romantic escape, A-list pair |
| 14 | Editorial Voice | we're glad, Border Czar, lunatic |

### SpanReason Enum

```python
SpanReason = Literal[
    "clickbait",
    "urgency_inflation",
    "emotional_trigger",
    "selling",
    "agenda_signaling",
    "rhetorical_framing",
    "editorial_voice"
]
```

### Quote Filtering

Uses Unicode escapes to avoid editor corruption:

```python
QUOTE_PAIRS = {
    '"': '"',           # Straight (U+0022)
    '\u201c': '\u201d', # Curly double
    "'": "'",           # Straight (U+0027)
    '\u2018': '\u2019', # Curly single
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

### Slash Commands

| Command | Purpose |
|---------|---------|
| `/debug-spans <id>` | Debug span detection for article |
| `/check-spans` | Check span reasons distribution |

## Highlight Colors (Frontend)

| Category | Color |
|----------|-------|
| `urgency_inflation` | Dusty rose |
| `emotional_trigger` | Slate blue |
| `editorial_voice` | Lavender |
| `clickbait`, `selling` | Amber/tan |
| Default | Gold |

## Key Files

| File | Purpose |
|------|---------|
| `neutralizer/spans.py` | `find_phrase_positions()`, quote filtering |
| `taxonomy.py` | 115 manipulation types (v2 taxonomy) |
| `app/prompts/` | Prompt templates |
