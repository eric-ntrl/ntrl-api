# /story - Work on a Story

## Purpose
Load a story, understand its acceptance criteria, implement it, and self-validate before marking complete.

## Arguments
- `$ARGUMENTS` - Path to story file (e.g., `docs/stories/feature/001-story.md`) or "next" for the next unstarted story

## Instructions

### If argument is "next" or empty:
1. Scan `docs/stories/` for stories with status "todo" or "in-progress"
2. Find the next story by number that has all dependencies completed
3. Load and start working on that story

### If argument is a story path:

1. **Read the story file** completely

2. **Parse the story** and extract:
   - Story title and description
   - Parent PRD reference
   - Acceptance criteria (each criterion)
   - Dependencies (other stories that must be done first)
   - Files likely to be modified

3. **Verify dependencies**:
   - Check that all dependency stories are marked "done"
   - If not, inform the user and suggest working on dependencies first

4. **Update story status** to "in-progress"

5. **Plan implementation**:
   - Read all files mentioned in "Files to Modify"
   - Identify the minimal changes needed
   - Create a todo list with specific tasks

6. **Implement the story**:
   - Make changes incrementally
   - Run tests after each significant change
   - Keep changes focused on acceptance criteria only
   - Avoid scope creep - if you see other improvements, note them but don't implement

7. **Self-validate against acceptance criteria**:
   - Go through EACH acceptance criterion
   - Verify it is met with evidence (test output, manual verification)
   - Document how each criterion was validated

8. **Run the validation skill**:
   - Use `/validate` to do a final check
   - Address any failures

9. **Update story status** to "done" only when ALL criteria pass

10. **Output completion summary**:
    - What was implemented
    - How each acceptance criterion was met
    - Any notes for future stories
    - Suggested next story

## Important Rules

- **Never skip acceptance criteria** - each one must be explicitly verified
- **Stay in scope** - only implement what the story asks for
- **Test as you go** - don't wait until the end to test
- **Update status accurately** - in-progress while working, done only when validated

## Example Usage

```
/story docs/stories/user-preferences/001-add-preference-model.md
/story next
```
