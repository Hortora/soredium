# Slot-Scoped .plan Persistence

## Problem

In a multi-repo slot, `.plan` lives on the workspace branch. The workspace branch is stamp-only — never merged to main. When work-end closes a branch and switches the workspace to main, the `.plan` is committed on the branch but unreachable from main. The next session's `work continue` finds no `.plan` and reports "no active work."

Additionally, `cleanup_scaffold` unconditionally deletes `$SLOT_PATH/.plan` (lines 127-129 of `branch_cleanup.py`), destroying any slot-level copy.

The existing `_plan_has_remaining` preservation logic (line 86) correctly skips deletion on the workspace branch, but this is preservation in name only — the branch is switched away from moments later.

## Design

### Core principle

In slot mode, `.plan` is a **slot-level resource**. Branch-level operations (close, stamp, checkout) must not destroy it while queue items remain.

### Mechanism: elevation at close time

When `cleanup_scaffold` preserves `.plan` (remaining items exist) and a `slot_path` is provided:

1. Copy the preserved `.plan` from the workspace branch to `$SLOT_PATH/.plan`
2. Set the branch field to `pending` (signals "between branches")
3. Do NOT delete the slot-root `.plan`

When the queue is fully drained (no remaining items):

1. Delete `.plan` from workspace (existing behavior)
2. Delete `$SLOT_PATH/.plan` if it exists

### ctx.py fallback

PLAN_PATH resolution gains a slot-root fallback:

1. Check `$WORKSPACE/.plan` (existing, backward compat)
2. If not found and `IN_SLOT=yes`: check `$SLOT_PATH/.plan`
3. Return whichever is found

Suppress `BRANCH_MISMATCH` when `.plan` has `branch: pending` — this is the expected state for a slot-root `.plan` between branches.

### Work continue path

When `ON_MAIN=yes`, `IN_SLOT=yes`, `HAS_PLAN=yes`, and `ACTIVE_ISSUE` is set:

1. Read slot-root `.plan` for the active issue
2. Create branch on the target repo for that issue
3. Update `.plan` branch field from `pending` to the new branch name
4. Begin working

## Files changed

| File | Change |
|------|--------|
| `work-end/branch_cleanup.py` | Replace unconditional `slot_plan.unlink()` with conditional: copy on preserve, delete on drain. Add `_reset_plan_branch`. |
| `project/ctx.py` | Add slot-root `.plan` fallback in PLAN_PATH resolution. Suppress mismatch for `branch: pending`. |

## Files NOT changed

- `plan_manager.py` — receives `plan_path` from ctx.py, path-agnostic
- `lifecycle.py` — same
- `work_end_orchestrator.py` — receives `plan_path` from ctx.py
- `scaffold.py` — still writes to workspace on initial creation
- `land_flow.py` — doesn't touch `.plan`

## Test plan

1. `test_cleanup_elevates_plan_to_slot_root` — remaining items + slot path → .plan copied
2. `test_cleanup_deletes_slot_plan_when_drained` — no remaining → slot root .plan deleted
3. `test_elevated_plan_has_pending_branch` — branch field set to `pending`
4. `test_ctx_finds_slot_root_plan_fallback` — workspace absent, slot root found
5. `test_ctx_prefers_workspace_plan` — both exist, workspace wins
6. `test_no_branch_mismatch_for_pending_branch` — no BRANCH_MISMATCH for `branch: pending`

## References

- `branch_cleanup.py:45-73` — existing `_plan_has_remaining` + `_reset_plan_state`
- `branch_cleanup.py:125-129` — unconditional `slot_plan.unlink()` (the secondary bug)
- `work_end_execute.py:347` — workspace stamp-only comment (root cause)
- `ctx.py` — PLAN_PATH resolution and BRANCH_MISMATCH detection
- Issue #364 — original report with slot 170 reproduction scenario
