# Fixes Log

> Append-only history of issues found and resolved. Add new entries at the bottom.

## Format

```
### Fix #N: [Title] (YYYY-MM-DD)

**Problem**: What was wrong
**Solution**: How it was fixed
**Files**: Changed files
```

---

### Fix #1: Alembic Multiple Heads Crash (2026-01-15)

**Problem**: Railway deployment crashed with "Multiple heads detected" error. Alembic migrations had diverged.

**Solution**: Created merge migration to linearize heads. Added check to CI.

**Files**: `migrations/versions/`

---

### Fix #2: Quote Filtering Unicode Corruption (2026-01-16)

**Problem**: Curly quote characters were getting corrupted when prompts were saved/loaded, breaking quote filtering.

**Solution**: Use Unicode escape sequences (`\u201c`, `\u201d`) instead of literal quote characters in code.

**Files**: `neutralizer/spans.py`

---

### Fix #3: MockNeutralizerProvider in Production (2026-01-17)

**Problem**: Mock provider was accidentally being used as fallback, producing garbage output.

**Solution**: Removed mock from provider chain. Mock is now test-only.

**Files**: `neutralizer/__init__.py`

---

### Fix #4: Topic Migration Override (2026-01-20)

**Problem**: `migrateTopics()` was running on every `getPreferences()` call, re-adding topics users had deselected.

**Solution**: Migration now only runs when old `tech` key is detected (actual migration case).

**Files**: `ntrl-app/src/storage/storageService.ts`

---

### Fix #5: FlatList onLayout Scroll Position (2026-01-22)

**Problem**: Category pills were incorrectly highlighting the last section during scroll. `onLayout` returns positions relative to visible window, not absolute scroll offset.

**Solution**: Switched to `onViewableItemsChanged` with 50% visibility threshold.

**Files**: `ntrl-app/src/screens/SectionsScreen.tsx`, `CategoryPills.tsx`

---

### Fix #6: Long Article Span Detection (2026-01-24)

**Problem**: Articles over ~8,000 characters were missing span highlights. LLM-returned phrases didn't match exact positions.

**Solution**: Documented as known limitation. Chunking planned for Phase 2.

**Files**: `docs/operations/monitoring-runbook.md` (documented)

---

### Fix #7: Span Position Field Separation (2026-01-25)

**Problem**: Title spans were incorrectly offset into body text positions.

**Solution**: Position adjustment now correctly separates spans by field (title/body) based on `---ARTICLE BODY---` marker.

**Files**: `neutralizer/spans.py`

---

### Fix #8: Classification Fallback Alert (2026-01-26)

**Problem**: No visibility into when keyword fallback was being used instead of LLM classification.

**Solution**: Added `CLASSIFY_FALLBACK_RATE_HIGH` alert when >1% of articles use keyword fallback.

**Files**: `services/alerts.py`, `services/llm_classifier.py`

---

## Adding New Entries

When fixing an issue:

1. Add new entry at the bottom with next number
2. Include date, problem, solution, files
3. Keep entries concise but complete
4. Reference related documentation if applicable
