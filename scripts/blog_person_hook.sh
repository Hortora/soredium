#!/bin/bash
# Claude Code PreToolUse hook for Bash — checks blog files for person references
# before git commit. Reads the command from $CLAUDE_TOOL_INPUT (JSON).
#
# Install: add to settings.json PreToolUse[Bash].hooks
# Only fires for git commit commands; passes through everything else silently.

# Parse the command from tool input
COMMAND=$(echo "$CLAUDE_TOOL_INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("command",""))' 2>/dev/null)

# Only check git commit commands (not git commit --allow-empty, amend, etc. that are infrastructure)
case "$COMMAND" in
    *"git commit"*"--allow-empty"*) exit 0 ;;
    *"git commit"*)                 ;;
    *)                              exit 0 ;;
esac

# Extract repo path from git -C <path> or use CWD
REPO_PATH="."
if echo "$COMMAND" | grep -q 'git -C'; then
    REPO_PATH=$(echo "$COMMAND" | sed -n 's/.*git -C \([^ ]*\).*/\1/p')
fi

# Run the check
RESULT=$(python3 "$(dirname "$0")/blog_person_check.py" "$REPO_PATH" 2>/dev/null)
RC=$?

if [ $RC -eq 1 ]; then
    echo "BLOCK: Blog person-reference gate — review required before commit."
    echo "$RESULT" | grep "^FLAG="
    echo ""
    echo "These sentences may reference identifiable persons."
    echo "Review each and confirm they belong in a technical record."
    exit 1
fi

exit 0
