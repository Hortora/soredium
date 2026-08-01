---
name: work
description: >
  Use when the user says "work", "work end", "work pause", or "work resume" —
  detects current branch state and routes to the correct work lifecycle skill
  automatically. "work" alone starts new work or shows the pause stack.
  "work end" closes the branch. "work pause" saves state. "work resume" shows
  the stack and returns to a paused branch. Replaces needing to know which
  lifecycle skill to invoke.
---

# work

Unified entry point for the work lifecycle. Detects state and routes to the
correct skill — developer says `work` to begin, `work-end` to close,
`work-pause` to save and switch, `work-resume` to return to paused work.

---

## Routing

**Step 1 — Parse the invocation and detect state**

| Invocation | Route to |
|------------|---------|
| `work end` | → **work-end** immediately (no router needed) |
| `work pause` | → **work-pause** immediately (no router needed) |
| `work epic #N` | → epic setup (Step 5) |
| `work next` | → advance epic issue (Step 6) |
| `work` / `work start` / `work resume` / `resume handover` / `resume` / `continue` | → run the router (Step 1b) |

For `work end` and `work pause`, route immediately — no state
detection needed.

**Step 1b — Run the router**

```bash
python3 ~/.claude/skills/project/ctx.py
# Read PROJECT, WORKSPACE, CURRENT_BRANCH from output

python3 ~/.claude/skills/work/work_router.py \
  $CURRENT_BRANCH $PROJECT $WORKSPACE
```

The router outputs KEY=VALUE lines. Read them all — they determine
the route AND provide context for the options menu. Do NOT re-derive
this state with additional tool calls.

**Step 2 — Route based on output**

| `ROUTE` | Action |
|---------|--------|
| `start` | → **work-start** — begin new work |
| `resume_stack` | → show stack picker (Step 3), then **work-resume** |
| `resume_branch` | → contextual options (Step 4) |

**Step 3 — Stack picker (on main, 1+ paused branches)**

Show paused branches with age and note. Adapt phrasing to stack depth:

```
You have <N> paused branch(es):
  1. <branch>  #<issue>  paused <duration> ago
  2. <branch>  #<issue>  paused <duration> ago   (if N > 1)
  ...

Resume one, or start something new? (1 / 2 / ... / new)
```

- Number → **work-resume** with that branch pre-selected
- `new` → **work-start**

If stack depth > 3, prefix with: `⚠️  Stack has <N> paused branches — consider closing some before adding more.`

**Step 4 — On feature branch: contextual options**

Present options based on the router output. The router has already
determined slot context, epic state, pause stack depth, and handoff
existence — do NOT re-derive these.

If `HAS_HANDOFF=yes`:
> 1. **resume** — read the last handover and continue where I left off

If `HAS_HANDOFF=no`:
> 1. **start** — begin working (first session on this branch)

If `STACK_DEPTH > 0`:
> 2. **switch** — you have <N> paused branch(es) — resume one instead

If `IS_EPIC=yes`:
> N. **next** — mark current child issue done, advance to next

Always present:
> N+1. **end** — close this branch, merge, push, return to main
> N+2. **pause** — commit WIP, push to stack, switch to main
> N+3. **wrap** — end session but keep branch open (write handover)

**On resume (option 1 when `HAS_HANDOFF=yes`):**

Read `$HANDOFF_PATH`.
If `IS_EPIC=yes`: read the epic file at `$EPIC_PATH` (single-repo) or
`$SLOT_PATH` (slot) for batch progress and active issue. Display:
```
Epic — Batch $EPIC_BATCH
Active issue: #$EPIC_ACTIVE_ISSUE
```
Set active issue for commit linkage (`Refs #$EPIC_ACTIVE_ISSUE`).

If `IN_SLOT=yes` but `IS_EPIC=no`: read .slot for issue context.

**Load design specs (mandatory):** Run work-start Step 3c — scan workspace
and project for specs, read them all. These are the design decisions for
this branch. Do not begin implementation without them.

Summarise what the last session accomplished and continue working.
Do NOT invoke work-start — the branch and scaffold already exist.

**On start (option 1 when `HAS_HANDOFF=no`):**

No handover to read. Run work-start resume path (Steps 0, 2, 3, 3b, 3c, 11)
for platform coherence, protocols, spec loading, and IntelliJ pre-checks.
If `IS_EPIC=yes` or `IN_SLOT=yes`: read epic/slot context as above.
Then begin working — the branch and scaffold already exist.

**On switch (option 2):**
Route to **work-pause** (saves current branch), then **work-resume**
(shows pause stack picker).

**On end/pause/wrap:**
Route to work-end, work-pause, or handover respectively.

**Step 5 — `work epic #N` (epic setup)**

Sets up single-repo epic iteration. Must be on main.

1. Resolve paths via `ctx.py`. Use `$OWNER_REPO` for the repo.
2. Fetch the epic issue: `gh issue view <N> --repo $OWNER_REPO --json title,body`
3. Parse child issues from `## Scope` checklist (`- [ ] #N` entries).
   For each child, check state via `gh issue view <child> --repo $OWNER_REPO
   --json state` — skip CLOSED children (handles mid-epic resume after
   prior work-end).
4. Fetch title/labels for each open child.
5. If 5+ open children → batch planning (LLM-driven grouping: domain
   affinity, shared API surface, scale fit, dependency ordering — same
   criteria as `work-slot epic` Step 4). Otherwise flat ordered list as
   a single batch.
6. Sync main before branch creation (equivalent to work-start Step 4d):
   `git fetch origin main && git rebase origin/main`
7. Create or reset branch (target: `issue-N-<slug>`):
   - Branch does not exist → `git checkout -b issue-N-<slug>`
   - Branch exists with closure stamp (`chore: branch closed` as latest
     commit subject) → mid-epic resume. Reset: `git checkout -B issue-N-<slug>`
   - Branch exists without stamp → error: "Epic branch already exists
     and is active. Use `work` to resume."
8. Scaffold `.meta` and `JOURNAL.md` via `scaffold.py`.
9. Write `workspace/design/.epic` via `epic_manager.write_epic()`.
10. If `$GITHUB_PROJECT` configured, activate all child issues (non-fatal).
11. Report: "Epic #N — M children, K batches. Active: #<first>. Run
    work-start to begin."

**Step 6 — `work next` (advance epic issue)**

Advances to the next child issue in the current epic. Detects context:
- `/worktrees/` in `$PROJECT` → slot context, epic file at
  `$PROJECT/../.slot`
- `workspace/design/.epic` exists → single-repo context

Steps:

1. Run `ctx.py` to resolve paths. Determine epic file location.
2. Call `epic_manager.py advance <epic-path>`. The script atomically
   checks off the current issue, appends to COVERS in `.meta`, moves
   `← active` to next, updates Session State.
3. Check off the completed issue's checkbox on the GitHub epic body
   (progress signaling, not issue closure — consistent with work-slot).
4. If `epic_complete` in the result → add the epic issue number to
   `Covers:` in `.meta`. Report: "All children done. Run work-end."
5. If `batch_complete` and not `epic_complete` → log: "Batch N complete.
   Safe exit point — run work-end to merge, or continue."
6. Report new active issue. Set `Refs #<next-issue>` for commit linkage.

---

## Skill Chaining

**Routes to:**
- `work-start` — when beginning new work from main
- `work-resume` — when returning to a paused branch from main
- `work-end` — when closing a completed branch (includes full wrap + HANDOFF.md)
- `work-pause` — when saving state to switch to something else
- `handover` — when ending the session but keeping the branch open (mid-work wrap)

**This skill does not implement the lifecycle itself** — it detects state and
delegates. All logic lives in the individual lifecycle skills.
