# Story: Schema Migration for New Article Outputs

**Status**: done
**Completed**: 2025-01-12
**PRD**: docs/prd/article-neutralization-v1.md
**Story ID**: article-neutralization-v1/1.5
**Size**: M
**Created**: 2025-01-12

## Description

Migrate the database schema to support all 6 distinct article outputs. This involves renaming existing fields, adding new fields, and removing deprecated structured fields that don't match the content spec.

## Context

This is the final story in Phase 1 (Foundation). With the deterministic grader, LLM scorer, and test corpus in place, we now need the schema to support the new outputs before Phase 2 can begin building the actual neutralization pipeline.

## Dependencies

- [x] Story 1.1 - Integrate deterministic grader
- [x] Story 1.2 - Create /v1/grade endpoint
- [x] Story 1.3 - Create LLM quality scorer service
- [x] Story 1.4 - Create 10-article test corpus

## Acceptance Criteria

- [x] **AC1**: `StoryNeutralized` model has renamed fields: `feed_title` (was `neutral_headline`), `feed_summary` (was `neutral_summary`)
- [x] **AC2**: `StoryNeutralized` model has new fields: `detail_title`, `detail_brief`, `detail_full` (all nullable for gradual rollout)
- [x] **AC3**: Deprecated fields removed from model: `what_happened`, `why_it_matters`, `what_is_known`, `what_is_uncertain`
- [x] **AC4**: `DailyBriefItem` denormalized fields updated to match new naming
- [x] **AC5**: Pydantic schemas updated to reflect new field structure
- [x] **AC6**: Alembic migration created and runs successfully
- [x] **AC7**: Existing tests pass with updated field names

## Technical Notes

### Files to Modify
- `app/models.py` - Update StoryNeutralized and DailyBriefItem models
- `app/schemas/` - Update Pydantic schemas for neutralized stories
- `migrations/versions/` - New Alembic migration file

### Implementation Hints
- Use Alembic `op.alter_column` with `new_column_name` for renames
- New detail fields should be nullable initially (content generated in Phase 2-4)
- Keep model and schema in sync
- Watch for any routers that reference old field names

### Testing Approach
- Run `alembic upgrade head` on fresh DB
- Run existing test suite
- Verify renamed columns work in queries

## Out of Scope

- Generating content for new fields (Phase 2-4)
- Updating API response shapes (separate story)
- Data migration for existing rows (fields are nullable)

## Validation Checklist

- [x] AC1: PASS - `feed_title` and `feed_summary` fields in StoryNeutralized model (app/models.py:197-198)
- [x] AC2: PASS - `detail_title`, `detail_brief`, `detail_full` nullable fields added (app/models.py:201-203)
- [x] AC3: PASS - Deprecated fields removed from model (no longer in StoryNeutralized)
- [x] AC4: PASS - DailyBriefItem uses `feed_title`, `feed_summary` (app/models.py:317-318)
- [x] AC5: PASS - Pydantic schemas updated (app/schemas/stories.py, app/schemas/brief.py)
- [x] AC6: PASS - Migration runs successfully (migrations/versions/005_article_neutralization_v1_schema.py)
- [x] AC7: PASS - All schema-related tests pass (14 tests in test_neutralizer.py, test_api.py)
