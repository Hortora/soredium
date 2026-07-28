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

Always present:
> 1. **resume** — read the last handover and continue where I left off

If `STACK_DEPTH > 0`:
> 2. **switch** — you have <N> paused branch(es) — resume one instead

Always present:
> 3. **end** — close this branch, merge, push, return to main
> 4. **pause** — commit WIP, push to stack, switch to main
> 5. **wrap** — end session but keep branch open (write handover)

**On resume (option 1):**

If `HAS_HANDOFF=yes`: read `$HANDOFF_PATH`.
If `IS_EPIC=yes`: also read .slot at `$SLOT_PATH` for batch
progress and active issue. Display:
```
Epic — Batch $EPIC_BATCH
Active issue: #$EPIC_ACTIVE_ISSUE
```
Set active issue for commit linkage (`Refs #$EPIC_ACTIVE_ISSUE`).

If `IN_SLOT=yes` but `IS_EPIC=no`: read .slot for issue context.

Summarise what the last session accomplished and continue working.
Do NOT invoke work-start — the branch and scaffold already exist.

**On switch (option 2):**
Route to **work-pause** (saves current branch), then **work-resume**
(shows pause stack picker).

**On end/pause/wrap:**
Route to work-end, work-pause, or handover respectively.

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
