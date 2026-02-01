# Evaluation System Reference

> Quick reference for the teacher LLM evaluation and auto-optimization system.

## Overview

NTRL uses a "teacher LLM" (Claude Opus 4.5) to evaluate and improve pipeline outputs. The system grades neutralization quality, span detection accuracy, and can auto-optimize prompts.

## Slash Commands

| Command | Purpose |
|---------|---------|
| `/evaluate` | Run teacher LLM evaluation |
| `/evaluate auto-optimize` | Run eval + auto-improve prompts |
| `/evaluate <n>` | Evaluate n articles (default: 5) |

## Quality Metrics

### Span Detection

| Metric | Question | Target |
|--------|----------|--------|
| **Precision** | When we flag a phrase, is it manipulative? | 99% |
| **Recall** | Did we find all manipulative phrases? | 99% |

**Analogy**: Finding red balls in a pit of red and blue balls.
- **Precision** = When you grab a ball, is it actually red?
- **Recall** = Did you find all the red balls?

### Precision-Recall Tradeoff
- More cautious → Precision ↑, Recall ↓
- More aggressive → Recall ↑, Precision ↓

### Neutralization Quality

| Metric | What It Measures |
|--------|------------------|
| Factual preservation | No facts added or removed |
| Tone neutrality | No editorial voice |
| Readability | Clear, grammatical output |
| Coherence | Logical flow maintained |

## Auto-Optimization Loop

```
1. Select sample articles
2. Run current prompts
3. Teacher LLM grades outputs
4. Identify:
   - Missed phrases (false negatives)
   - Incorrect flags (false positives)
   - Quality issues
5. Generate prompt improvements
6. Test improved prompts
7. If better → save new version
8. Rollback if degraded
```

## Evaluation Workflow

### Quick Evaluation
```
/evaluate 5
```
Runs teacher evaluation on 5 random articles, reports precision/recall and quality scores.

### Full Evaluation with Optimization
```
/evaluate auto-optimize
```
Runs evaluation + attempts to improve prompts automatically.

### After Prompt Changes
```
/classify force → /brief rebuild → /evaluate
```

## Evaluation Output Format

```
Quality Check (5 articles)
─────────────────────────
Classification: 80% (+5% vs last)
Neutralization: 7.8/10 (+0.2)
Span Precision: 72% (stable)
Span Recall:    45% (-3%)  ⚠️

Top Missed: "careens toward", "key player"
Recommendations: 2 prompts flagged for optimization
```

## Key Files

| File | Purpose |
|------|---------|
| `services/prompt_optimizer.py` | Auto-optimization logic |
| `services/teacher_evaluator.py` | Teacher LLM grading |
| `.claude/commands/evaluate.md` | Slash command definition |

## Rollback Procedure

If prompt changes degrade quality:

1. Check current prompt version: `/prompt show <name>`
2. List versions: `/prompt versions <name>`
3. Rollback: `/prompt rollback <name> <version>`
4. Re-evaluate: `/evaluate`

## Tips

- Always evaluate after prompt changes
- Use 5-10 articles for quick checks
- Use 20+ articles for comprehensive evaluation
- Monitor precision/recall trends over time
- Auto-optimize is conservative — won't deploy risky changes
