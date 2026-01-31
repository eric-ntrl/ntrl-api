# /brief - Check Brief Status

## Purpose
View current brief section distribution and story counts.

## Arguments
- `$ARGUMENTS` - Optional: "rebuild" to trigger brief rebuild

Examples:
- `/brief` - Show current brief status
- `/brief rebuild` - Rebuild the brief and show new status

## Instructions

### View Brief Status
```bash
curl -s "https://api-staging-7b4d.up.railway.app/v1/brief" \
  -H "X-API-Key: staging-key-123"
```

Parse and display:

**Daily Brief Status**

| Section | Stories | Top Story |
|---------|---------|-----------|
| World | X | "Headline..." |
| U.S. | X | "Headline..." |
| Local | X | "Headline..." |
| Business | X | "Headline..." |
| Technology | X | "Headline..." |
| Science | X | "Headline..." |
| Health | X | "Headline..." |
| Environment | X | "Headline..." |
| Sports | X | "Headline..." |
| Culture | X | "Headline..." |

**Total: X stories across Y sections**

### Warnings
Flag issues:
- Empty sections (0 stories) - may need more ingestion or classification
- Very uneven distribution - possible classification issues
- Missing expected sections

### Rebuild Brief
If "rebuild" flag:
```bash
curl -s -X POST "https://api-staging-7b4d.up.railway.app/v1/brief/run" \
  -H "X-API-Key: staging-key-123"
```

Then show updated status.

## Section Order (Fixed)
1. World
2. U.S.
3. Local
4. Business
5. Technology
6. Science
7. Health
8. Environment
9. Sports
10. Culture

## Notes
- Brief groups stories by `feed_category` (10 categories)
- Stories without `feed_category` are skipped (run `/classify` first)
- Brief is cached for 15 minutes
- Use "rebuild" to force refresh after classification or neutralization
