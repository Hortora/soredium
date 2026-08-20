# Unified Work Queue — Design Spec

**Issue:** #261
**Date:** 2026-08-20
**Branch:** issue-261-unified-work-queue
**Review:** Light pass complete (R1-01 through R1-15 addressed)

## Problem

The work lifecycle has two separate mechanisms for "what's next":
- **On branches:** `.plan` queue with `← active` markers, `work next` advances
- **On main:** Ad-hoc what-next via enrichment.py/HANDOFF.md, funneling into `work start`

Commands error when invoked in the "wrong" context instead of routing to the right behavior. Work can be accidentally skipped or left unfinished. The LLM makes mechanical routing decisions that should be deterministic.

## Solution

### 1. Bidirectional chaining

Four commands form a chain. Each chains forward (nothing to do) and guards backward (not ready):

```
continue ←→ next ←→ end ←→ find
    →  "nothing to do, cascade forward"
    ←  "not ready, go back"
```

| Command | Responsibility | Forward chain | Backward guard |
|---------|---------------|---------------|----------------|
| `continue` | Keep working on active issue | Active issue done → `next` | — (entry point) |
| `next` | Advance queue to next issue | Queue empty → `end` | Active issue still open → `continue` |
| `end` | Close ceremony (issues, docs, blog) | Ceremony done → `find` | Queue not empty → `next` |
| `find` | Discover and populate queue | — (terminal, stays `drained` if zero results) | Unfinished work → `next` |

### 2. `.plan` on main

`.plan` files can exist on any branch including main. Same format, same queue semantics. The workspace main branch hosts the main `.plan`.

**Main `.plan` format:** Identical to branch `.plan` with `branch: main` in `## State`. All consumers handle this: lifecycle reads it for worklog, ctx reads it for mismatch detection (`main == main` passes), plan_manager doesn't use `branch:` for queue logic.

```markdown
# Work Plan — main

## State
branch: main
state: active
date: 2026-08-20
issue-repo: Hortora/soredium
covers: 42,55
design-repo: project

## Queue
- [ ] #42 — Fix caching bug ← active
- [ ] #55 — Refactor auth
```

On main, the `.plan` tracks a queue of work items. Each `work next` on main creates a feature branch via `work start` for the next item (unless the item is small enough for main — textual guidance, not a gate).

### 3. Chaining logic in Python

A new module **`work_chain.py`** (not `work_router.py` — avoids collision with the deleted `work/work_router.py` referenced in `work_state.py:3`) implements all chaining decisions. It outputs directives the LLM follows:

```python
# Output format
DIRECTIVE=continue          # proceed with continue
DIRECTIVE=chain_to_next     # nothing to continue, chain forward
DIRECTIVE=guard_continue    # next called but issue unfinished, go back
DIRECTIVE=chain_to_end      # queue empty, chain forward
DIRECTIVE=guard_next        # end called but queue not empty, go back
DIRECTIVE=chain_to_find     # ceremony done, chain forward
DIRECTIVE=guard_next        # find called but unfinished work, go back
DIRECTIVE=proceed           # command can proceed normally
DIRECTIVE=no_work_found     # find returned zero results, stay drained

# Additional context
REASON=active_issue_done
ACTIVE_ISSUE=42
ISSUE_STATE=closed
QUEUE_REMAINING=3
ON_MAIN=yes
```

The script checks:
- GitHub issue state (`gh issue view --json state`)
- Queue state (plan_manager.detect)
- .plan existence and META_STATE
- Uncommitted changes
- Branch context (main vs feature, using BASE_BRANCH not hardcoded "main")

**The router does NOT fire state machine events for chaining decisions.** It reads the current state and emits a directive. State machine events are reserved for actual state changes (R1-03).

### 4. New `drained` state

Renamed from `ended` to avoid collision with worklog `ended` semantics (R1-02). The worklog maps `idle → ended` (permanent branch close). `drained` means "queue empty, ceremony done, `.plan` persists, awaiting repopulation."

Add to lifecycle state machine:

```python
VALID_STATES = frozenset({
    'idle', 'scaffolded', 'active', 'transitioning', 'paused', 'drained',
    'closing:review', 'closing:verified', 'closing:promoted',
    'closing:pushed', 'closing:merged', 'closing:stamped',
})
```

Worklog mapping addition:
```python
_LIFECYCLE_TO_WORKLOG = {
    'idle': 'ended',       # permanent close (unchanged)
    'drained': 'idle',     # queue empty, not actively working, not permanently closed
    ...
}
```

New transitions:

| From | Event | To | Effects | Post-commit |
|------|-------|----|---------|-------------|
| `closing:stamped` | `cleanup_pass` | `idle` | `write_plan_closed` | `return_to_main`, `write_handoff` (unchanged) |
| `closing:stamped` | `cleanup_main` | `drained` | `write_plan_drained` | `write_handoff` |
| `drained` | `work_find` | `transitioning` | `queue_populated` | — |

**Implementation notes:**

- Two distinct events (`cleanup_pass` vs `cleanup_main`) keep the transition table pure — no runtime context inspection inside `transition()`. The caller selects based on `ON_MAIN`.
- `cleanup_main` post-commit includes `write_handoff` (session context is useful on main too) but NOT `return_to_main` (already there).
- `drained → work_find → transitioning` routes through the existing transient state. The subsequent `auto_refresh → active` transition provides full context-loading effects: `garden_search`, `load_specs`, `check_protocols` (R1-04). This reuses existing infrastructure rather than adding a new activation path.
- **No self-transitions on `drained`** (R1-03). The chaining module reads the state and emits directives directly — no round-trip through the state machine for routing decisions.

**`write_plan_drained` effect:** Writes `state: drained` and `drained-sha: <HEAD>` to `.plan`'s `## State`. The SHA serves as the diff base for the next review cycle (R1-06).

**INVALID_MESSAGES for `drained`** (R1-07):

```python
('drained', 'work_end'):   "Already drained. Use `work find` to discover new work.",
('drained', 'work_pause'):  "Nothing active to pause.",
('drained', 'work_resume'): "Nothing to resume. Use `work find` to discover new work.",
('drained', 'work_next'):   "Queue is empty. Use `work find` to discover new work.",
```

### 5. work-end on main

work-end becomes context-aware. On main, it skips branch-specific steps:

| Step | Branch | Main |
|------|--------|------|
| 1. Context | Check branch alignment | Check .plan exists (via `work_end_context.py`) |
| 2. Review | Diff against base branch | Diff against `drained-sha` from `.plan` (or `HEAD~N` if first close) |
| 3. Sweep | Identical | Identical |
| 4.1 Promote | Identical | Identical |
| 4.2 Rebase | Rebase onto base | Skip |
| 4.3 Squash | Classify branch commits | Skip |
| 4.4 Land | Push, stamp, merge | Push only |
| 5. Verify | Check merged + stamped | Check pushed |
| 5b. Close issues | Identical | Identical |
| 6.2 Checkout main | Switch to main | Skip (already there) |
| 6.2b Cleanup | Remove .plan | Keep .plan (fire `cleanup_main`, set state to `drained`) |

**Diff base for main-mode review (R1-06):** When entering `drained` state, `write_plan_drained` writes `drained-sha: <HEAD>` to `.plan`'s `## State`. The next `work end` on main diffs against this SHA. On the first close (no prior `drained-sha`), diff against the SHA from when `.plan` was created (`project-sha:` field).

Textual guidance when starting work on main: "Consider a feature branch for non-trivial work (`work start #N`). `quick-fix` for small changes." Never blocks.

### 6. `work find`

New verb in the routing table. Runs the enrichment/what-next pipeline (currently Step 2a of `work`). Appends results to `.plan` via `plan_manager append`.

```bash
python3 scripts/enrichment.py refresh --repo $OWNER_REPO
python3 scripts/enrichment.py what-next --repo $OWNER_REPO --mode general --limit 5
```

If no `.plan` exists, creates one (with `branch: main`, `state: active`).

If `.plan` exists with `drained` state and user selects items:
1. `plan_manager append` adds items to queue
2. Fire `work_find` transition: `drained → transitioning`
3. Execute `auto_refresh` effects (garden search, load specs, check protocols)
4. Commit transition: `transitioning → active`

**Zero results (R1-09):** If enrichment returns nothing and user adds nothing, stay in `drained`. Output `DIRECTIVE=no_work_found`. Do not transition. The chain terminates — no loop.

### 7. Routing changes

**New route in `work_state.py` (R1-15):** When on main with a `.plan` in `drained` state:

```python
if on_main:
    if meta_state == 'drained':
        route = "drained"
    elif stack_depth > 0:
        route = "resume_stack"
    else:
        route = "start"
```

The `work/SKILL.md` routing table handles `drained` by offering `work find`:

| `ROUTE` | Action |
|---------|--------|
| `start` | → **work-start** (unchanged) |
| `resume_stack` | → stack picker (unchanged) |
| `resume_branch` | → contextual options (unchanged) |
| `workspace_dirty` | → warn and reset (unchanged) |
| `drained` | → "Queue drained. Run `work find` to discover new work, or start fresh with an issue number." |

## Implementation plan

### Phase 1: Python infrastructure

1. **`work_chain.py`** — new module in `project/`
   - `evaluate_continue(ctx)` → directive
   - `evaluate_next(ctx)` → directive
   - `evaluate_end(ctx)` → directive
   - `evaluate_find(ctx)` → directive
   - All functions take ctx.py output dict as input
   - All functions return structured output (directive + reason + context)
   - No state machine events — reads state, emits directives

2. **`lifecycle.py` changes**
   - Add `drained` to `VALID_STATES`
   - Add transitions: `cleanup_main → drained`, `work_find → transitioning`
   - Add `INVALID_MESSAGES` for `drained` state
   - Add `_LIFECYCLE_TO_WORKLOG` mapping for `drained`
   - New `write_plan_drained` effect (writes `state: drained` + `drained-sha`)

3. **`ctx.py` / `work_state.py` changes**
   - Pass `BASE_BRANCH` to `work_state.detect()` (fix hardcoded "main" comparison)
   - Add `drained` route detection
   - Output `CHAIN_DIRECTIVE` from `work_chain.evaluate_*` based on invoked command

4. **`work_health.py` changes** (R1-01)
   - `check_stale_scaffold_on_main`: skip `.plan` when `state: drained` (intentional, not stale)
   - `check_meta_consistency`: handle `branch: main` as valid on main

5. **`work_end_context.py` changes** (R1-13)
   - `check_branch_alignment`: pass-through on main (both repos on main is valid)
   - `check_meta_exists`: handle main `.plan` format
   - Context fields (`branch`, `issue`, `covers`): populate from main `.plan`

### Phase 2: Skill updates

6. **`work/SKILL.md`** — routing table
   - Add `work find` to routing table
   - Add `drained` route handling
   - Replace LLM-driven chaining with "read CHAIN_DIRECTIVE, follow it"
   - Remove Step 1c errors for continue-on-main (replaced by chaining)
   - Extract Step 2a into `work find` verb

7. **`work-end/SKILL.md`** — main support
   - Remove "must be on branch" precondition
   - Add conditional logic for main-mode (skip merge/stamp/rebase/squash)
   - Change scaffold cleanup to fire `cleanup_main` on main (sets `drained`)
   - Diff base: use `drained-sha` from `.plan` for review

8. **CSO updates** — update skill descriptions to reflect new verbs

### Phase 3: Tests

9. **`test_work_chain.py`** — comprehensive tests for all chaining paths
   - Forward chains: continue→next, next→end, end→find
   - Backward guards: next←continue, end←next, find←next
   - Edge cases: no .plan, empty queue, all issues closed, drained state
   - Zero results from find (stays drained, no loop)
   - Main vs branch context differences

10. **`test_lifecycle.py` updates** — new state transitions
    - `drained` state transitions (cleanup_main, work_find)
    - INVALID_MESSAGES for drained
    - Worklog mapping for drained
    - `write_plan_drained` effect

11. **`test_work_end_main.py`** — main-mode work-end (R1-12)
    - Review with `drained-sha` diff base
    - Skip rebase/squash on main
    - Push-only (no merge/stamp) on main
    - Keep .plan with `drained` state instead of removing
    - Verify checks for main-mode (push verification without merge)
    - First close with no prior `drained-sha` (falls back to `project-sha`)

### Phase 4: Corruption recovery (separate issue)

Extracted per R1-14. Will be filed as a follow-up issue referencing the `drained` state once it exists. The unified work queue ships without corruption recovery; corruption recovery references the new states.

## Hardcoded "main" references (R1-11)

All files with hardcoded `"main"` comparison that need `BASE_BRANCH`:

| File | Line | Current | Fix |
|------|------|---------|-----|
| `project/work_state.py` | 52 | `on_main = current_branch == "main"` | Use `BASE_BRANCH` param |
| `project/work_health.py` | 93 | `if current == "main"` | Use `BASE_BRANCH` |
| `project/work_health.py` | 167 | `if current != "main"` | Use `BASE_BRANCH` |
| `project/work_health.py` | 181 | `if current != "main"` | Use `BASE_BRANCH` |
| `work-end/work_end_context.py` | 133 | `if ws_branch == "main"` | Use `BASE_BRANCH` |
| `project/lifecycle.py` | 476 | `base_branch: str = "main"` | Already parameterized (callers need to pass it) |

## Files changed

| File | Change type | Description |
|------|------------|-------------|
| `project/work_chain.py` | New | Bidirectional chaining directives |
| `project/lifecycle.py` | Modify | Add `drained` state, transitions, INVALID_MESSAGES, worklog mapping |
| `project/ctx.py` | Modify | Fix hardcoded "main", output CHAIN_DIRECTIVE |
| `project/work_state.py` | Modify | Use BASE_BRANCH, add `drained` route |
| `project/work_health.py` | Modify | Handle `drained` state .plan on main, fix hardcoded "main" |
| `work-end/work_end_context.py` | Modify | Main-mode context, fix hardcoded "main" |
| `work/SKILL.md` | Modify | New routing table, `work find`, `drained` route, chaining directives |
| `work-end/SKILL.md` | Modify | Remove branch-only guard, main-mode conditionals |
| `tests/test_work_chain.py` | New | Chaining and directive tests |
| `tests/test_lifecycle.py` | Modify | `drained` state transitions, INVALID_MESSAGES |
| `tests/test_work_end_main.py` | New | Main-mode work-end integration tests |

## References

- lifecycle.py — state machine, transition table, validate_state(), worklog mapping
- ctx.py / work_state.py — routing logic, ON_MAIN detection
- plan_manager.py — detect(), advance(), queue management
- work_health.py — stale scaffold check, meta consistency
- work_end_context.py — branch alignment, meta existence checks
- work/SKILL.md — current routing table, Step 1c errors, Step 2a what-next, Step 4 continue, Step 5 work next
- work-end/SKILL.md — 12 branch-specific touchpoints identified in audit
- ADR-0013 — unified .plan file design
- docs/protocols/evidence-before-claims.md — verification before completion
- docs/protocols/externalised-scripts-require-tests.md — tests for new scripts
- Design review R1-01 through R1-15 — structural issues addressed in this revision
