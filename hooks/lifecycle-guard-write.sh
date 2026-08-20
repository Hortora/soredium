#!/bin/bash
# PreToolUse hook for Write/Edit: guard direct writes to lifecycle files.
# .plan/.meta/.slot: warn but allow (user may direct edits explicitly).
# lifecycle.py/pre_push_hook.py: hard block (infrastructure, never edit in-session).

FILE_PATH=$(cat | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)

BASENAME=$(basename "$FILE_PATH" 2>/dev/null)

case "$BASENAME" in
  .meta|.plan|.slot)
    echo "⚠️  Direct write to $BASENAME — normally managed by scaffold.py/plan_manager.py." >&2
    exit 0
    ;;
  lifecycle.py|pre_push_hook.py)
    echo "BLOCK: $BASENAME is lifecycle infrastructure. Editing it bypasses the state machine and push gates that enforce work-end. Propose changes as a separate issue." >&2
    exit 2
    ;;
esac

exit 0
