# ADR 001: Text Length Constraints Architecture

## Status
Accepted

## Context
UI text length (feed summaries, titles) appears to be a frontend concern but is actually controlled by backend LLM prompts. When users report text truncation ("...") or want different line counts, the fix requires:

1. Understanding that content length is set during neutralization, not display
2. Modifying LLM prompts with appropriate buffer for counting inaccuracy
3. Re-processing existing content

This was discovered during a feed summary adjustment from 2 lines to 3 lines, which required multiple iterations (175 -> 140 -> 115 -> 100 chars) due to LLM character counting inaccuracy.

## Decision

### Content Length Architecture
```
[RSS Feed] -> [Ingestion] -> [Neutralizer Prompts] -> [Database] -> [API] -> [App Display]
                                     ^
                         Length constraints live HERE
                         (not in React Native numberOfLines)
```

### Prompt Constraint Strategy
1. **State limit 15-20% lower than actual target** - LLMs overcount
2. **Provide multiple short examples** - LLMs follow examples more than instructions
3. **Include explicit "rewrite shorter" instruction** - Catches edge cases

### Example Prompt Pattern
```
STRICT CONSTRAINTS:
- MAXIMUM 100 characters (count EVERY character)
- Target 85-95 characters (leave buffer)

GOOD: "Short example here. Second sentence." (62 chars)
GOOD: "Another example. Also brief." (58 chars)
BAD: "This example is too long and will cause truncation..." (TOO LONG)

If over 100 characters, REWRITE SHORTER before outputting.
```

### Line Capacity Reference
- Mobile displays approximately 38-42 characters per line
- 2 lines: target 65 characters
- 3 lines: target 100 characters
- 4 lines: target 135 characters

## Consequences

### Positive
- Clear separation: backend controls content, frontend controls display
- Predictable text lengths across all articles
- Single point of change for length adjustments
- Deterministic output (same length rules for all users)

### Negative
- Requires re-processing content after prompt changes
- LLM inaccuracy requires trial-and-error for exact limits
- Changes require deployment (not just app update)
- Re-neutralization takes time (several minutes for full corpus)

### Mitigations
- Document the workflow in CLAUDE.md
- Create `/ui-length` skill for guided changes
- Use `force: true` flag for efficient re-processing
- Provide pass rate verification scripts

## Alternatives Considered

1. **Frontend truncation only**
   - Rejected: causes "..." and inconsistent UX
   - Users see cut-off sentences which feels broken

2. **Post-processing length enforcement**
   - Rejected: would require re-calling LLM or crude truncation
   - Expensive and still produces poor results

3. **Database constraints**
   - Rejected: doesn't control generation, only storage
   - Would just cause errors, not shorter content

4. **Dynamic frontend adjustment**
   - Rejected: different devices would show different content
   - Violates determinism principle

## References
- `app/services/neutralizer.py` - All prompt definitions (lines ~1095-1235)
- `docs/canon/content-spec-v1.md` - Content generation specifications
- `.claude/commands/ui-length.md` - Skill for guided length changes
- Feed summary iterations: 175 -> 140 -> 115 -> 100 chars (Jan 2026)
