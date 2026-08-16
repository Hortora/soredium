---
name: work
description: >
  Use when the user says "work", "work end", "work pause", "work resume",
  "work continue", or "work next" — detects current branch state and routes
  to the correct work lifecycle skill automatically. "work" alone starts new
  work or shows the pause stack. "work end" closes the branch. "work pause"
  saves state. "work continue" keeps working on the current branch.
  "work resume" restores a paused branch from the stack.
  "work next" advances to the next issue in the .plan queue.
---

# work

Unified entry point for the work lifecycle. Detects state and routes to the
correct skill — developer says `work` to begin, `work end` to close,
`work pause` to save and switch, `work resume` to return to paused work.

---

## Routing

**Step 1 — Parse the invocation and detect state**

| Invocation | Route to |
|------------|---------|
| `work end` | → **work-end** immediately (no router needed) |
| `work pause` | → **work-pause** immediately (no router needed) |
| `work next` | → advance to next issue in `.plan` queue (Step 5) |
| `work resume` / `resume` | → **work-resume** (pause-stack only; error if on active branch — see Step 1c) |
| `work continue` / `continue` | → run router → Step 4 `continue` action directly (error if on main — see Step 1c) |
| `work` / `work start` | → run router (Step 1b) |
| `resume handover` | → handover skill directly (manual invocation) |

For `work end` and `work pause`, route immediately — no state
detection needed.

**Step 1c — Wrong-context error handling (D4)**

Before dispatching to a sub-skill or executing an internal action,
check for wrong-context invocations:

| Invocation | Condition | Action |
|------------|-----------|--------|
| `work resume` | `ON_MAIN=no` (on feature branch, not paused) | Error: "Not paused — use `continue` to keep working, or `work pause` first." |
| `work resume` | `ON_MAIN=yes` + `STACK_DEPTH=0` | Error: "Nothing to resume — pause stack is empty. Use `work` to start new work." |
| `work continue` | `ON_MAIN=yes` + `STACK_DEPTH=0` | Error: "No active branch — use `work` to start new work." |
| `work continue` | `ON_MAIN=yes` + `STACK_DEPTH>0` | Error: "No active branch — use `work` to start new work or `work resume` to return to a paused branch." |
| `work continue` | `ROUTE=workspace_dirty` | Error: "Workspace is on a stale branch — run `work` to clean up." |
| `work start` | `ROUTE=resume_branch` | Redirect → `continue` + note: "Already on `<branch>` — continuing." |

**Step 1b — Run the router**

```bash
python3 ~/.claude/skills/project/ctx.py
# Read all fields from output — ctx.py includes both topology and
# routing fields (ROUTE, ON_MAIN, STACK_DEPTH, HAS_HANDOFF, etc.)
```

ctx.py outputs all KEY=VALUE lines. Read them all — they determine
the route AND provide context for the options menu. Do NOT re-derive
this state with additional tool calls.

**Step 2 — Route based on output**

| `ROUTE` | Action |
|---------|--------|
| `start` | → what-next recommendation (Step 2a), then **work-start** |
| `resume_stack` | → show stack picker (Step 3), then **work-resume** |
| `resume_branch` | → contextual options (Step 4) |
| `workspace_dirty` | → warn and offer to reset (Step 2b) |

**Step 2a — What-next recommendation (when no issue specified)**

If the user invoked `work` without an issue number and `ROUTE=start`:

1. Refresh the GitHub cache:
   ```bash
   python3 scripts/enrichment.py refresh --repo $OWNER_REPO
   ```

2. Query for recommendations:
   ```bash
   python3 scripts/enrichment.py what-next --repo $OWNER_REPO --mode general --limit 5
   ```

3. If results exist and any are enriched, present them:
   ```
   Recommended next:
     1. #42 — Fix caching bug (score: 12, quick-win, ready, compounding)
     2. #55 — Refactor auth (score: 8, load-bearing, ready, stable)
     3. #99 — Add tests (score: 0, not enriched)

   Pick a number, type an issue #, or describe what you want to work on.
   ```

4. If no enrichment data exists yet (all scores are 0) or what-next
   returns no results, check HANDOFF.md for a What's Next section:

   a. Read `$HANDOFF_PATH` (from router output) or `$WORKSPACE/HANDOFF.md`
   b. Parse the What's Next table (if present)
   c. If items found, present them:
      ```
      From last session's handover:
        1. Layer 4a: Trust & routing (M / Med)
        2. Layer 4b: CBR & incident lifecycle (M / High)

      Pick a number, type an issue #, or describe what you want to work on.
      ```
   d. If the user picks an item without an issue number, route to work-start
      which invokes issue-workflow Phase 2 to create the issue.
   e. If no HANDOFF.md or no What's Next section, route directly to work-start.

5. **Surface notes (if present):**
   If `$WORKSPACE/.notes/NOTES.md` exists, read the most recent date
   section and surface it below the recommendations:
   ```
   Notes (2026-08-10):
     - Remember to check auth token expiry after the migration
     - [engine] reindex needed after next schema change
   ```
   Show only the most recent date section. Skip silently if the file
   doesn't exist or is empty.

6. If the user specified an issue number in their `work` invocation,
   skip this step entirely — route directly to work-start with the
   specified issue.

7. User picks → route to **work-start** with the selected issue number.

**Step 2b — Workspace on stale branch (workspace_dirty)**

The workspace is on a non-main branch left by another session — the project
is on main but the workspace wasn't switched back. This means another session
switched the workspace branch without pausing.

Present:

> ⚠️ Workspace is on `$WORKSPACE_BRANCH` (project is on main).
> Another session left the workspace on this branch.
>
> Options:
> 1. **reset** — switch workspace to main and start new work
> 2. **continue** — stay on this workspace branch (advanced)

- **reset** → `git -C "$WORKSPACE" checkout main`, then route to **work-start**
- **continue** → route to **work-start** (user takes responsibility for alignment)

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
determined slot context, queue state, pause stack depth, and handoff
existence — do NOT re-derive these.

> 1. **continue** — keep working (loads context automatically)

If `STACK_DEPTH > 0`:
> 2. **switch** — you have <N> paused branch(es) — restore one from stack

If `HAS_PLAN=yes`:
> N. **next** — mark current issue done, advance to next in queue

Always present:
> N+1. **end** — close this branch, merge, push, return to main

If `HAS_PLAN=yes` and queue has remaining items, annotate the end option:
> N+1. **end** — ⚠️ queue has N remaining issues — close this branch, merge, push, return to main

> N+2. **pause** — commit WIP, push to stack, switch to main
> N+3. **wrap** — end session but keep branch open (write handover)

**On continue (option 1):**

**Lifecycle:** Fire `transition(plan_path, 'work_continue')` — validates
branch is `active`, emits worklog event. No state change (self-transition).

When `HAS_HANDOFF=yes` (subsequent session):
1. Read `$HANDOFF_PATH` — summarise last session's narrative
2. Run `work_health.py --scope entry --owner-repo $OWNER_REPO` — syncs `.plan` with GitHub, validates workspace state
3. If `HAS_PLAN=yes`: read `.plan` at `$PLAN_PATH` for queue progress and
   active issue. Display:
   ```
   Queue — Position $PLAN_POSITION
   Active issue: #$ACTIVE_ISSUE
   ```
   Set active issue for commit linkage (`Refs #$ACTIVE_ISSUE`).
4. If `IN_SLOT=yes` and `HAS_PLAN=no`: read .slot for issue context
5. **Load design specs (mandatory):** Run work-start Step 3c — scan workspace
   and project for specs, read them all
6. **Done-detection auto-suggest (D3):** If `ACTIVE_ISSUE` is empty after
   health sync (issue was marked complete), suggest next action:
   - If remaining items in queue: "Current issue complete. `next` (N remaining) or `end`?"
   - If queue is empty: "Current issue complete. `end` to close the branch?"
7. Summarise what the last session accomplished and continue working.
   Do NOT invoke work-start — the branch and scaffold already exist.

When `HAS_HANDOFF=no` (first session, or HANDOFF.md missing):
1. Run work-start resume path (Steps 0, 2, 3, 3b, 3c, 11)
   for platform coherence, protocols, spec loading, and IntelliJ pre-checks
2. Run `work_health.py --scope entry --owner-repo $OWNER_REPO`
3. If `HAS_PLAN=yes` or `IN_SLOT=yes`: read .plan/slot context as above
4. Done-detection auto-suggest (D3)
5. Begin working — the branch and scaffold already exist.

**Mid-session issue completion (D4):** When the active issue is completed
during a session (GitHub issue closed, user says "that's done", execution
skill reports all tasks done, or a `Closes #N` commit is made), ALWAYS
check queue state before suggesting next action:

1. Run `python3 ~/.claude/skills/project/ctx.py`
2. Read `HAS_PLAN` and `ACTIVE_ISSUE`
3. If `HAS_PLAN=yes`:
   - If `ACTIVE_ISSUE` is non-empty → more work remains.
     Suggest `next` to advance, NOT `work end`.
   - If `ACTIVE_ISSUE` is empty → queue is exhausted.
     Suggest `work end`.
4. If `HAS_PLAN=no` → suggest `work end`.

**Never suggest work-end when the queue has remaining issues.**

**On switch (option 2):**
Route to **work-pause** (saves current branch), then **work-resume**
(shows pause stack picker).

**On end/pause/wrap:**
Route to work-end, work-pause, or handover respectively.

**Step 5 — `work next` (advance to next issue in `.plan` queue)**

Advances to the next issue in the `.plan` queue. Works identically in
branch and slot mode — the `.plan` file is the single source of truth.

**Precondition:** `.plan` must exist (`HAS_PLAN=yes` from ctx.py).

Steps:

1. Run `ctx.py` to resolve paths. Read `PLAN_PATH` from output.
2. Fire `transition(plan_path, 'work_next')` — validates the transition,
   returns effects `[advance_issue, tick_github]`.
3. Execute effects:
   - `advance_issue`: Call `plan_manager.advance(<PLAN_PATH>)`.
     The function atomically checks off the current issue and moves the
     `← active` marker to the next leaf issue.
   - `tick_github`: Check off the completed issue's checkbox on the
     GitHub epic body (if the completed issue was an epic child).
4. Call `commit_transition(plan_path, result)` — writes `state: transitioning`.
5. If `has_deferred` in the result → deferred items exist and the agreed
   queue is complete. Read deferred items:
   ```bash
   python3 ~/.claude/skills/work-slot/plan_manager.py list-deferred <PLAN_PATH>
   ```
   Present each item individually with scale, complexity, and deferral reason.
   The reason is the advice — it tells the user whether the item is feasible now.
   ```
   All planned issues complete. N deferred items:

     0. <title> (S / Low) — <reason>
        → Recommendation: feasible now, no blockers
     1. <title> (M / High) — blocked by #55 upstream release
        → Recommendation: not feasible until #55 lands
     2. <title> (L / High) — needs schema migration first
        → Recommendation: do in a separate branch after migration

   Select items to add to queue (e.g. "0,2"), or "none" to close:
   ```
   Assess each item's feasibility based on its reason and the current context
   (available repos, what just landed, known blockers). Items with no reason
   or reasons that are no longer blocking should be recommended. Items with
   active blockers should be flagged.

   - **User selects items** → call `plan_manager.promote_selected(<PLAN_PATH>, [indices])`,
     then proceed to step 8 (context refresh) with the first promoted item as active.
     Remaining unselected items stay in the deferred list.
   - **"none"** → run work-end. Deferred items stay in `.plan` for the next branch
     or can be filed as GitHub issues.
6. If `queue_complete` and not `has_deferred` → report: "All issues done. Run work end."
7. If `batch_complete` and not `queue_complete` → log: "Batch N complete.
   Safe exit point — run work end to close, or continue."
8. **Context refresh (auto-resolve):** Fire `transition(plan_path, 'auto_refresh')`,
   execute context refresh effects (garden search with new issue keywords,
   load specs matching new issue, check protocols), then
   `commit_transition(plan_path, result)`. The branch transitions back to `active`.
9. Report new active issue. Set `Refs #<next-issue>` for commit linkage.

---

## Skill Chaining

**Routes to:**
- `work-start` — when beginning new work from main
- `work-resume` — when returning to a paused branch from main
- `work-end` — when closing a completed branch (includes full wrap + HANDOFF.md)
- `work-pause` — when saving state to switch to something else
- `handover` — when ending the session but keeping the branch open (mid-work wrap)

**Complements:**
- `quick-fix` — lands small changes on main without a feature branch;
  work routes to work-start for branch-based work

**This skill does not implement the lifecycle itself** — it detects state and
delegates. All logic lives in the individual lifecycle skills.
