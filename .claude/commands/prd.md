# /prd - Product Requirements Document Analyzer

## Purpose
Load a PRD, analyze it, and break it down into bite-sized stories with acceptance criteria that fit within a context window.

## Arguments
- `$ARGUMENTS` - Path to PRD file (e.g., `docs/prd/feature-name.md`) or "list" to show available PRDs

## Instructions

### If argument is "list" or empty:
1. List all PRD files in `docs/prd/`
2. Show their titles and status
3. Suggest which PRD to work on next

### If argument is a PRD path:

1. **Read the PRD file** at the specified path

2. **Analyze the PRD** and extract:
   - Feature name and description
   - User goals and pain points
   - Technical requirements
   - Success metrics
   - Dependencies and constraints

3. **Break down into stories** following these rules:
   - Each story must be completable in a single focused session
   - Each story must have clear, testable acceptance criteria
   - Stories should be ordered by dependency (foundational first)
   - Each story should touch no more than 3-5 files to stay within context
   - Stories should be atomic - either fully done or not started

4. **Generate story files** in `docs/stories/[prd-name]/`:
   - Create a story file for each identified story
   - Use the story template format
   - Number stories in recommended order (001, 002, etc.)

5. **Create a story index** showing:
   - Total number of stories
   - Estimated complexity per story (S/M/L)
   - Dependency graph
   - Recommended implementation order

6. **Output summary** with:
   - PRD analysis overview
   - Number of stories created
   - Suggested starting story
   - Any clarifying questions for ambiguous requirements

## Story Sizing Guidelines

**Small (S)**: Single function, straightforward logic, 1-2 files
**Medium (M)**: Multiple functions, some complexity, 2-3 files
**Large (L)**: New module/feature, significant logic, 3-5 files

If a story is larger than L, break it down further.

## Example Usage

```
/prd docs/prd/user-preferences.md
/prd list
```
