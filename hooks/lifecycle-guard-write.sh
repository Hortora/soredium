#!/bin/bash
# PreToolUse hook for Write/Edit: block direct writes to lifecycle files.
# Use the plan_manager.py API instead:
#   append   — add issues to queue
#   set-state — update state fields
#   defer    — add deferred items
#   inject-tasks — add tasks to batches

FILE_PATH=$(cat | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)

BASENAME=$(basename "$FILE_PATH" 2>/dev/null)

case "$BASENAME" in
  .meta|.plan|.slot)
    echo "BLOCK: Use plan_manager.py API instead of editing $BASENAME directly. Commands: append, set-state, defer, inject-tasks, check-task, detect." >&2
    exit 2
    ;;
  lifecycle.py|pre_push_hook.py)
    echo "BLOCK: $BASENAME is lifecycle infrastructure. Propose changes as a separate issue." >&2
    exit 2
    ;;
esac

exit 0
