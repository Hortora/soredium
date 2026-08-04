#!/bin/bash
# PreToolUse hook for Write/Edit: block direct writes to lifecycle files.
# These must be written by scaffold.py, plan_manager.py, or epic_manager.py.

FILE_PATH=$(cat | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)

BASENAME=$(basename "$FILE_PATH" 2>/dev/null)

case "$BASENAME" in
  .meta|.plan|.slot)
    echo "BLOCK: $BASENAME must be written by scaffold.py or plan_manager.py, not directly. Direct writes bypass validation and worklog recording." >&2
    exit 2
    ;;
  lifecycle.py|pre_push_hook.py)
    echo "BLOCK: $BASENAME is lifecycle infrastructure. Editing it bypasses the state machine and push gates that enforce work-end. Propose changes as a separate issue." >&2
    exit 2
    ;;
esac

exit 0
