#!/bin/bash
#
# Ralph Loop for NTRL Article Neutralization
# Spawns fresh Claude CLI sessions to work through prd.json stories
#
# Usage: ./scripts/ralph.sh [max_iterations]
#

set -e

MAX_ITERATIONS=${1:-50}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=== NTRL Ralph Loop ==="
echo "Max iterations: $MAX_ITERATIONS"
echo "Project: $PROJECT_DIR"
echo ""

# Check for incomplete stories
check_complete() {
    local incomplete=$(jq '[.userStories[] | select(.passes != true)] | length' prd.json)
    echo "$incomplete"
}

# The prompt for each iteration
PROMPT='You are working on the NTRL Article Neutralization project.

## Your Task
Work on the NEXT incomplete story from prd.json (where passes != true).

## Process
1. Read prd.json to find the next incomplete story (lowest priority number where passes=false)
2. Read the story s acceptance criteria carefully
3. Implement the required changes
4. Run tests: pipenv run python -m pytest tests/ -v
5. If tests pass AND acceptance criteria met:
   - Update prd.json to set passes=true for this story
   - Commit changes with message: "Story X.X: <title>"
   - Append learnings to progress.txt
6. If tests fail or criteria not met:
   - Fix the issues
   - Do NOT mark as passes=true until fully working

## Key Files
- prd.json: Story definitions and status
- progress.txt: Learnings log
- docs/canon/neutralization-canon-v1.md: Canon rules
- docs/canon/content-spec-v1.md: Output specifications
- app/services/grader.py: Deterministic grader

## Quality Bar
- All 6 outputs must pass deterministic grader
- LLM quality score >= 8.5 for iteration stories (2.4, 3.3, 4.3)

## When Done
After completing ONE story, output: <story_complete>X.X</story_complete>
If blocked, output: <blocked>reason</blocked>'

for i in $(seq 1 $MAX_ITERATIONS); do
    echo ""
    echo "=========================================="
    echo "ITERATION $i / $MAX_ITERATIONS"
    echo "=========================================="

    # Check if all stories complete
    incomplete=$(check_complete)
    if [ "$incomplete" -eq 0 ]; then
        echo ""
        echo "=== ALL STORIES COMPLETE ==="
        echo "<promise>COMPLETE</promise>"
        exit 0
    fi

    echo "Incomplete stories: $incomplete"
    echo "Spawning Claude... $(date +%H:%M:%S)"
    echo ""

    # Spawn fresh Claude session
    time claude --dangerously-skip-permissions --print --verbose --debug -p "$PROMPT"

    # Verify tests actually pass
    echo ""
    echo "--- Verifying tests... ---"
    if pipenv run python -m pytest tests/ -q; then
        echo "✓ Tests passed"
    else
        echo "✗ Tests FAILED - Claude claimed complete but verification failed"
    fi

    # Brief pause between iterations
    echo ""
    echo "Iteration $i complete. Pausing 3 seconds..."
    sleep 3
done

echo ""
echo "=== MAX ITERATIONS REACHED ==="
echo "Completed $MAX_ITERATIONS iterations"
incomplete=$(check_complete)
echo "Remaining incomplete stories: $incomplete"

# Final verification
echo ""
echo "=== Final Verification ==="
if pipenv run python -m pytest tests/ -q; then
    echo "✓ All tests pass"
    exit 0
else
    echo "✗ Tests FAILED - stories may be incorrectly marked as complete"
    exit 1
fi
