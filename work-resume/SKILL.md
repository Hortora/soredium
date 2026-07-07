---
name: work-resume
description: >
  Use when returning to a paused branch — user says "work-resume", "resume",
  or "go back to that branch". Invoked from main to restore a previously
  paused work session. Handles multiple paused branches via stack.
---

# work-resume

Resumes a paused branch from the stack: lets the user pick, rebases the branch
onto the current project base branch (picking up any work that landed since it was paused), resets
the WIP commit to restore working state, removes the entry from the stack.

**Single-repo mode:** When no workspace exists (`SINGLE_REPO=yes` from ctx.py),
all operations apply to the project repo only — skip workspace-specific steps.
The pause stack lives at `$PROJECT/.pause-stack`.

---

## Path Resolution (run first, always)

Run the bundled context script — no shell variable assignments, no CLAUDE.md scanning:
```bash
python3 ~/.claude/skills/project/ctx.py
```

Use `WORKSPACE`, `PROJECT`, `BASE_BRANCH`, `CURRENT_BRANCH` from the output as concrete strings.
`BASE_BRANCH` defaults to `main` if not declared in the project CLAUDE.md.

---

## Step 0 — Resolve paths

Read `$PROJECT` and `$WORKSPACE` from CLAUDE.md (see Path Resolution above).

---

## Step 1 — Read pause stack

```bash
STACK_FILE="$WORKSPACE/design/.pause-stack"
[ -f "$STACK_FILE" ] || { echo "Nothing to resume — pause stack is empty."; exit 1; }
grep -q "^- branch:" "$STACK_FILE" || { echo "Nothing to resume — pause stack is empty."; exit 1; }
```

Parse all entries. Each entry has: `branch`, `issue`, `paused`, `wip_project`, `wip_workspace`.

---

## Step 2 — Pick branch (if stack depth > 1)

If only one entry: auto-select it, no prompt.

If multiple entries, show the stack (most recent last = shown at bottom):
```
Paused branches:
  1. issue-94-work-lifecycle   #94   paused 3 days ago   "WIP committed"
  2. issue-87-api-refactor     #87   paused 1 week ago   "WIP committed"

Resume which? (1 / 2)
```

Set `$RESUME_BRANCH`, `$RESUME_WIP_PROJECT`, `$RESUME_WIP_WORKSPACE` from selected entry.

---

## Step 3 — Verify branch exists

```bash
git -C "$PROJECT" rev-parse --verify "$RESUME_BRANCH" &>/dev/null || { echo "⚠️ $RESUME_BRANCH not found in project repo."; exit 1; }
git -C "$WORKSPACE" rev-parse --verify "$RESUME_BRANCH" &>/dev/null || { echo "⚠️ $RESUME_BRANCH not found in workspace repo."; exit 1; }
```

If missing from either:
- `[D]` Discard this stack entry and clean up
- `[A]` Abort — leave state as-is for manual investigation

---

## Step 4 — Switch both repos to branch

Checkout must succeed before popping the stack — if checkout fails, the stack
entry must remain so the branch can be retried.

```bash
OUTPUT=$(python3 ~/.claude/skills/work-resume/resume_exec.py checkout-branches "$PROJECT" "$WORKSPACE" branch="$RESUME_BRANCH")
echo "$OUTPUT"
echo "$OUTPUT" | grep -q "CHECKED_OUT=yes" || { echo "⚠️ Branch checkout failed."; exit 1; }
```

---

## Step 5 — Remove entry from stack (on workspace main)

Only after checkout succeeds (Step 4). Pop the entry and push atomically —
a second session seeing the stack entry will attempt its own checkout, which
is harmless since the branch is already checked out here.

```bash
git -C <WORKSPACE> checkout main
python3 ~/.claude/skills/project/stack.py pop <WORKSPACE>/design/.pause-stack <RESUME_BRANCH>
git -C <WORKSPACE> add design/.pause-stack
git -C <WORKSPACE> commit -m "chore: resume <RESUME_BRANCH> — pop from pause stack"
git -C <WORKSPACE> push
git -C <WORKSPACE> checkout <RESUME_BRANCH>
```

**If push fails:** warn but continue — the branch is already checked out and
work can proceed. The stale stack entry will be cleaned up on next resume or
work-end.

---

## Step 6 — Rebase branch onto current base branch

```bash
OUTPUT=$(python3 ~/.claude/skills/work-resume/resume_exec.py rebase "$PROJECT" "$WORKSPACE" base-branch="$BASE_BRANCH")
echo "$OUTPUT"

if echo "$OUTPUT" | grep -q "ERROR=rebase_conflict"; then
  echo "⚠️ Rebase conflict occurred. Conflicting files:"
  git -C "$PROJECT" diff --name-only --diff-filter=U
  echo ""
  echo "**Stop. Do not proceed.**"
  echo "Resolve conflicts, run 'git -C $PROJECT rebase --continue', then run work-resume again."
  exit 1
fi

echo "$OUTPUT" | grep -qE "REBASED=(yes|skipped)" || { echo "⚠️ Rebase failed."; exit 1; }
```

---

## Step 7 — Reset WIP commit

```bash
OUTPUT=$(python3 ~/.claude/skills/work-resume/resume_exec.py reset-wip "$PROJECT" "$WORKSPACE")
echo "$OUTPUT"

if echo "$OUTPUT" | grep -q "RESET=yes"; then
  echo "✅ WIP commit(s) reset — changes restored to working tree"
elif echo "$OUTPUT" | grep -q "RESET=no"; then
  echo "ℹ️  No WIP commits found to reset"
fi
```

The reset restores the working tree to exactly where it was when work was paused.

---

## Step 8 — Confirm

```
▶  Resumed: <branch-name>  Issue: #<N>
   Paused <duration> ago
   Rebased onto $PROJECT_BASE_BRANCH  (+N commits incorporated)
   WIP restored: project=<yes|no>  workspace=<yes|no>
   Stack remaining: <N> paused branch(es)
```

---

## Step 9 — Run pre-checks

Run Steps 0, 2, 3, 11 from work-start:
- **Step 0**: Path resolution (already done)
- **Step 2**: Platform coherence — re-read platform doc, run five coherence questions
- **Step 3**: Relevant protocols — scan and read applicable rules
- **Step 11**: IntelliJ MCPs — call both; hard stop if unavailable

Skip all branch creation steps — the branch already exists.

---

## Step 10 — Garden search

Run `forage SEARCH` for the domain to surface relevant garden entries before
resuming work. Derive the search term from the branch name or issue title
(e.g. `issue-94-work-lifecycle` → search for "work lifecycle"). This matches
the garden search that work-start performs for new branches — resumed branches
deserve the same context.

## Success Criteria

Work-resume is complete when:

- ✅ Paused branch selected and checked out in both repos
- ✅ WIP commit reset to restore working state
- ✅ Branch rebased onto current base (picks up work landed while paused)
- ✅ Stack entry removed
- ✅ Garden search performed for domain context

**Not complete until** the branch is active and the WIP commit is unwound.

## Skill Chaining

**Invoked by:** `work` — routing skill, when user selects a paused branch
from the stack picker or says "work resume"

**Invokes:** `work-start` (partial) — Steps 0, 2, 3, 11 only for pre-checks
after branch restoration

**Complements:**
- `work` — routing entry point
- `work-pause` — paired operation (pause saves, resume restores)
- `work-start` — runs partial pre-checks from work-start (not full branch creation)

**Reads from:** `.pause-stack` (paused branches list), branch metadata,
WIP commit state
