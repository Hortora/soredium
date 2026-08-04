#!/bin/bash
# PreToolUse hook for Bash: block rogue lifecycle operations.
# Detects branch merges to main and artifact moves done outside work-end scripts.
#
# Trivial changes on main (no active lifecycle) are allowed — the guards
# only fire when .meta exists, meaning a work-start created a branch with
# lifecycle state that work-end must close.

CMD=$(cat | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)

# No .meta = no active lifecycle. Allow everything.
# Check via wksp/ symlink (two-repo) or local design/.meta (single-repo).
HAS_META=no
if [ -f "wksp/design/.meta" ] 2>/dev/null || [ -f "design/.meta" ] 2>/dev/null; then
  HAS_META=yes
fi
if [ "$HAS_META" = "no" ]; then
  exit 0
fi

# Pattern 1: git merge to main/master (direct merge bypasses work-end)
if echo "$CMD" | grep -qE 'git\s+((-C\s+\S+\s+)?merge|(-C\s+\S+\s+)?rebase)\s' && echo "$CMD" | grep -qE '\bmain\b|\bmaster\b'; then
  if echo "$CMD" | grep -qE 'land_branch\.py|merge_slot|slot_manager\.py|rebase_exec\.py'; then
    exit 0
  fi
  echo "BLOCK: Merging to main must go through work-end scripts (land_branch.py). Direct git merge/rebase to main bypasses lifecycle state, squash analysis, and stamp verification." >&2
  exit 2
fi

# Pattern 2: git checkout main followed by git push (push after rogue merge)
if echo "$CMD" | grep -qE 'git\s+(-C\s+\S+\s+)?push\s+\S+\s+main\b'; then
  if echo "$CMD" | grep -qE 'land_branch\.py|merge_slot|slot_manager\.py'; then
    exit 0
  fi
  echo "BLOCK: Pushing to main must go through work-end scripts (land_branch.py push). Direct push bypasses artifact promotion stamp check and fork-first delivery." >&2
  exit 2
fi

# Pattern 3: cp/mv of workspace artifacts outside close_artifacts.py
if echo "$CMD" | grep -qE '(cp|mv)\s+' && echo "$CMD" | grep -qE '(specs/|blog/|adr/|plans/|snapshots/)'; then
  if echo "$CMD" | grep -qE 'close_artifacts\.py|artifact_promote\.py|blog_dest\.py'; then
    exit 0
  fi
  echo "BLOCK: Artifact promotion must go through close_artifacts.py. Manual cp/mv of specs, blog, adr, or plans bypasses routing, verification, and the .artifacts-promoted stamp." >&2
  exit 2
fi

# Pattern 4: writing .meta, .plan, or .slot directly (should use scaffold.py / plan_manager.py)
if echo "$CMD" | grep -qE "(cat|echo|printf|tee)\s.*>(>)?\s*\S*(\.meta|\.plan|\.slot)\b"; then
  echo "BLOCK: Lifecycle files (.meta, .plan, .slot) must be written by scaffold.py or plan_manager.py. Direct writes bypass validation and worklog recording." >&2
  exit 2
fi

exit 0
