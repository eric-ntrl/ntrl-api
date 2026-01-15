# /validate - Validate Acceptance Criteria

## Purpose
Rigorously validate that a story's acceptance criteria are met before marking it complete. This is the quality gate for self-optimization.

## Arguments
- `$ARGUMENTS` - Path to story file to validate, or empty for current in-progress story

## Instructions

1. **Load the story file**:
   - If no argument provided, find the story with status "in-progress"
   - Read the story and extract all acceptance criteria

2. **For EACH acceptance criterion**, perform validation:

   ### Code Criteria (e.g., "Function X exists", "Endpoint returns Y")
   - Read the relevant code files
   - Verify the code matches the criterion
   - Run the code if possible to confirm behavior

   ### Test Criteria (e.g., "Tests pass", "Coverage > X%")
   - Run the test suite: `pipenv run python -m pytest tests/ -v`
   - Check for failures
   - Verify coverage if required

   ### API Criteria (e.g., "Endpoint returns 200", "Response has field X")
   - If server is running, make actual API calls with curl
   - Verify response status and body

   ### Data Criteria (e.g., "Migration runs", "Schema updated")
   - Check migration files exist
   - Verify schema changes in models
   - Run migrations if safe to do so

3. **Generate validation report**:

   ```
   ## Validation Report: [Story Title]

   ### Criterion 1: [Description]
   - Status: PASS / FAIL
   - Evidence: [What was checked]
   - Notes: [Any observations]

   ### Criterion 2: [Description]
   ...

   ## Summary
   - Total Criteria: X
   - Passed: Y
   - Failed: Z
   - Overall: PASS / FAIL
   ```

4. **If any criteria FAIL**:
   - List specific failures
   - Suggest fixes for each failure
   - Do NOT mark story as done
   - Offer to fix the issues

5. **If ALL criteria PASS**:
   - Update story status to "done"
   - Record validation timestamp
   - Suggest next story to work on

## Validation Standards

- **Be strict** - ambiguous results are failures
- **Provide evidence** - show output, not just "it works"
- **Test edge cases** - if criterion says "handles errors", test error paths
- **Check regressions** - run full test suite, not just new tests

## Self-Optimization Loop

After validation, reflect on:
1. What took longer than expected?
2. What was unclear in the story?
3. What could improve the next story?

Add these observations to the story's "Retrospective" section.

## Example Usage

```
/validate docs/stories/user-preferences/001-add-preference-model.md
/validate
```
