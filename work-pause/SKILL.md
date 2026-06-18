---
name: work-pause
description: >
  Use when interrupting current branch work to switch to something else — user
  says "work-pause", "pause this work", or "switch to a different issue".
  Supports a stack of paused branches. Pair with work-resume to restore.
---

# work-pause

Commits all work-in-progress, pushes an entry onto the pause stack on workspace
main, and switches both repos to their base branch. Supports multiple paused branches.

Uncommitted changes are always committed as a `WIP:` commit on the branch —
no stash used. On resume, the WIP commit is reset so work continues cleanly.

---

## Path Resolution (run first, always)

Run the bundled context script — no shell variable assignments, no CLAUDE.md scanning:
```bash
python3 ~/.claude/skills/project-init/ctx.py
```

Use `WORKSPACE`, `PROJECT`, `BASE_BRANCH`, `CURRENT_BRANCH` from the output as concrete strings.
`BASE_BRANCH` defaults to `main` if not declared in the project CLAUDE.md.

---

## Step 0 — Resolve paths

Read `$PROJECT` and `$WORKSPACE` from CLAUDE.md (see Path Resolution above).

---

## Step 1 — Validate state

```bash
ls "$WORKSPACE/design/.meta" 2>/dev/null || { echo "No .meta found — not on a working branch."; exit 1; }
BRANCH_NAME=$(grep "^branch:" "$WORKSPACE/design/.meta" | sed 's/branch: //')
ISSUE_N=$(grep "^issue:" "$WORKSPACE/design/.meta" | sed 's/issue: //')
```

Must be on a branch where `$WORKSPACE/design/.meta` exists.

---

## Step 2 — Commit WIP on project branch

```bash
PAUSE_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
OUTPUT=$(python3 ~/.claude/skills/work-pause/pause_exec.py commit-wip "$PROJECT" message="WIP: paused $BRANCH_NAME at $PAUSE_TS")
```

Parse `COMMITTED=` from output:
- `COMMITTED=yes` → WIP commit created
- `COMMITTED=clean` → no commit needed (repo was clean)

---

## Step 3 — Commit WIP on workspace branch

```bash
WS_OUTPUT=$(python3 ~/.claude/skills/work-pause/pause_exec.py commit-wip "$WORKSPACE" message="WIP: paused $BRANCH_NAME at $PAUSE_TS")
```

Parse `COMMITTED=` from output:
- `COMMITTED=yes` → WIP commit created on workspace
- `COMMITTED=clean` → workspace was clean

---

## Step 4 — Push branches and add to pause stack

```bash
STACK_OUTPUT=$(python3 ~/.claude/skills/work-pause/pause_exec.py push-and-stack "$WORKSPACE" "$PROJECT" branch="$BRANCH_NAME" issue="$ISSUE_N" base-branch="$BASE_BRANCH")
```

Parse output:
- `PROJECT_PUSHED=yes|no` — whether project branch push succeeded
- `WORKSPACE_PUSHED=yes|no` — whether workspace branch push succeeded
- `STACKED=yes` — pause entry added to stack on workspace main
- If `ERROR=` appears, abort

This operation:
1. Pushes both branches to origin (non-fatal if fails — WIP commits are local)
2. Checks out base-branch in project, main in workspace
3. Pulls latest from both remotes
4. Adds pause entry to `.pause-stack` using stack.py
5. Commits and pushes the stack change

**If stack push to main fails: the script automatically aborts and pops the entry.**

---

## Step 5 — Parse stack depth and confirm

Get current stack depth:
```bash
STACK_DEPTH=$(python3 ~/.claude/skills/project-init/stack.py depth "$WORKSPACE/design/.pause-stack")
```

Display confirmation:
```
⏸  Paused: <branch-name>  Issue: #<N>
   WIP committed: project=<yes|no>  workspace=<yes|no>
   Stack depth: <N>

You're on main — type work to resume this branch or start new work.
```

If stack depth > 3, add: `⚠️  Stack has <N> paused branches — consider closing some.`

---

## Pause vs Wrap

**work-pause** is for switching branches mid-session — you're continuing to work,
just on something else. It does not write HANDOFF.md or run the session wrap.

If the session is ending (not switching to other work), use **handover** (`wrap`)
instead — it writes HANDOFF.md so the next session can resume on the same branch.

| Intent | Skill |
|--------|-------|
| Switch to a different branch now, come back later | work-pause |
| End the session, continue this branch next time | handover (wrap) |
| Branch is done, close everything | work-end |
