# Clear stale .landed marker when slot is re-activated

**Issue:** Hortora/soredium#373
**Branch:** issue-373-clear-stale-landed
**Date:** 2026-09-17

---

## Problem

When a slot finishes one issue via work-end, `.landed` is written
unconditionally. If the slot has more work queued (remaining `.plan`
items, or new items appended after close), the `.landed` marker makes
the slot look archivable to `archive-landed.py` and `slot_manager.py
archive-slot` even though it has active work.

The current mitigation — `archive-landed.py` checks `has_active_plan()`
— is fragile: if the `.plan` happens to be empty between issues, the
slot passes all archive checks.

Slot 198 (casehub) hit this: issue landed, `.landed` written, `.plan`
re-populated with new issues (#503-#508). The slot is still active
but carries a stale `.landed`.

### Root cause

The orchestrator writes `.landed` based on slot membership (`_skip_not_slot`),
not queue state. Terminal steps (`.landed`, stamp, archive, checkout-main,
cleanup) run unconditionally when in a slot — there is no concept of
"issue cycle" vs "terminal close."

---

## Design

### Core concept: cycle mode

work-end gains two modes, selected automatically by queue state:

| Queue state | Mode | Behavior |
|-------------|------|----------|
| `.plan` has uncompleted items | **cycle** | Sync code to canonical, close current issue, advance queue, stay active |
| `.plan` is empty or absent | **terminal** | Sync code to canonical, close current issue, write `.landed`, stamp, archive |

The user never selects the mode. The orchestrator reads the `.plan`
at the boundary between sync and terminal steps and acts accordingly.
Terminal closure with remaining items is a hard gate: "Cannot close —
.plan has N remaining items. Empty the .plan to proceed."

### What runs in each mode

All steps through `land` (sync to canonical) run in both modes. The
review pipeline runs in full — cycle mode is not a quality shortcut.

Steps that differ:

| Step | Terminal | Cycle |
|------|----------|-------|
| `stamp_pass` | runs (`closing:merged → closing:stamped`) | **skipped** |
| `write_marker` (`.phase-a-complete`) | runs | **skipped** |
| `write_landed` (`.landed`) | runs | **skipped** |
| `archive_slot` | runs | **skipped** |
| `report_archive` | runs | **skipped** |
| `checkout_main` | runs | **skipped** |
| `cleanup_stack` | runs | **skipped** |
| `cleanup` | runs | **skipped** |
| `cleanup_pass` / `cleanup_main` | runs (`→ idle` / `→ drained`) | **skipped** |
| **`cycle_pass`** (new) | skipped | **runs** (`closing:merged → active`) |
| `close_issues` | runs | runs |
| `elevate_plan` | runs | runs |
| `verify` | runs | runs (scoped to landed code) |
| `arc42_scan`, content steps | runs | runs |

### Close-with-remaining-items gate

When work-end reaches the terminal boundary and `.plan` has uncompleted
items, it blocks:

```
Cannot close — .plan has 3 remaining items.
To close: empty the .plan first (remove items or mark them done).
To sync and continue: this will cycle automatically.
```

The orchestrator does not offer a choice — it cycles. Terminal close
requires an empty `.plan`. This is enforced in the skip predicate, not
in the LLM instructions.

---

## Changes

### 1. New skip predicate: `_skip_cycle_mode(ctx)` (work_end_orchestrator.py)

```python
def _skip_cycle_mode(ctx) -> bool:
    """Skip terminal steps when .plan has remaining items (cycle mode)."""
    from plan_io import read_plan, has_uncompleted_items
    ws_plan = Path(ctx.workspace) / ".plan"
    state = read_plan(ws_plan)
    return state is not None and has_uncompleted_items(state)
```

Inverse for the cycle-only step:

```python
def _skip_not_cycle_mode(ctx) -> bool:
    """Skip cycle step when in terminal mode."""
    return not _skip_cycle_mode(ctx)
```

### 2. Skip combiner: `_or_skip()` (work_end_orchestrator.py)

Some steps already have skip predicates (e.g., `write_landed` has
`_skip_not_slot`). Compose them:

```python
def _or_skip(*fns):
    """Skip if ANY predicate returns True."""
    def combined(ctx):
        return any(fn(ctx) for fn in fns)
    return combined
```

### 3. Apply skip predicates to terminal steps

| Step | Current `skip_fn` | New `skip_fn` |
|------|-------------------|---------------|
| `write_marker` | `_skip_not_slot` | `_or_skip(_skip_not_slot, _skip_cycle_mode)` |
| `stamp_pass` | `None` | `_skip_cycle_mode` |
| `write_landed` | `_skip_not_slot` | `_or_skip(_skip_not_slot, _skip_cycle_mode)` |
| `archive_slot` | `_skip_not_slot` | `_or_skip(_skip_not_slot, _skip_cycle_mode)` |
| `report_archive` | `_skip_not_slot` | `_or_skip(_skip_not_slot, _skip_cycle_mode)` |
| `checkout_main` | `_skip_on_main` | `_or_skip(_skip_on_main, _skip_cycle_mode)` |
| `cleanup_stack` | `_skip_on_main` | `_or_skip(_skip_on_main, _skip_cycle_mode)` |
| `cleanup` | `None` | `_skip_cycle_mode` |
| `cleanup_pass` | `_skip_on_main` | `_or_skip(_skip_on_main, _skip_cycle_mode)` |
| `cleanup_main` | `_skip_not_main` | `_or_skip(_skip_not_main, _skip_cycle_mode)` |

### 4. New step: `cycle_pass` (work_end_orchestrator.py)

```python
StepDef("cycle_pass", "closing:merged", "lifecycle",
        skip_fn=_skip_not_cycle_mode,
        from_state="closing:merged", to_state="active",
        event="issue_cycle"),
```

Insert after `merge_pass` and before `stamp_pass` in the STEPS list.
When cycle mode is active, `cycle_pass` fires `issue_cycle` and
transitions `closing:merged → active`. The skipped `stamp_pass` never
fires, so the state stays `active` and all `closing:stamped`-phase
steps are naturally unreachable (though skip predicates provide
defense-in-depth).

### 5. New lifecycle transition: `issue_cycle` (lifecycle.py)

Add to `TRANSITION_TABLE`:

```python
('closing:merged', 'issue_cycle'): ('active', ['advance_issue', 'clear_closing_markers'], []),
```

Effects:
- `advance_issue`: advance `.plan` to next item (same as `work_next`)
- `clear_closing_markers`: remove `.close-progress` and any partial
  close state

This follows the existing `abort_close` pattern (`closing:review → active`,
`closing:verified → active`) but from a later state — permitted because
code has already landed on canonical (unlike abort, which reverts
pre-artifact).

### 6. Slot state machine: `landed → active` (slot_state.py)

Add `"active"` to `VALID_TRANSITIONS["landed"]`:

```python
"landed": frozenset({"archived", "active"}),
```

This supports the retroactive case (D4) where `.landed` already exists
and new work is appended.

### 7. Retroactive cleanup in `append_to_queue()` (plan_manager.py)

Add optional `slot_path` parameter:

```python
def append_to_queue(plan_path: Path, new_items: list[QueueItem],
                    position: int | None = None,
                    skip_state_check: bool = False,
                    slot_path: Path | None = None) -> list[QueueItem]:
```

When `slot_path` is provided and `slot_path / ".landed"` exists:
1. Remove the `.landed` file
2. If `slot_path / ".slot"` exists and contains `state: landed`,
   transition to `state: active` via `slot_state.transition()`
3. Log: `"Cleared stale .landed — slot re-activated with new work"`

This is a safety net for the edge case where `.landed` was written
(queue was empty at close time) and new work is appended later.

---

## What does NOT change

- **Review pipeline** — all review, audit, sweep, and content steps
  run identically in both modes. Cycle mode is not a quality shortcut.
- **`close_issues`** — always closes the current issue regardless of mode.
- **`elevate_plan`** — already queue-aware, runs in both modes. In
  terminal mode it cleans up; in cycle mode it preserves the queue.
- **`verify`** — still verifies code landed on canonical.
- **`land` step** — still syncs code to canonical repos (this is the
  whole point of cycle mode).
- **`advance()` and `promote_selected()` in plan_manager.py** — remain
  pure `.plan` operations, no slot awareness added.

---

## Testing

### Unit tests

1. **`_skip_cycle_mode`** — returns True when `.plan` has uncompleted
   items, False when empty/absent
2. **`_or_skip` combiner** — composes correctly with existing predicates
3. **`cycle_pass` step** — fires `issue_cycle` event, transitions
   `closing:merged → active`
4. **`append_to_queue` with slot_path** — removes `.landed`, transitions
   slot state, handles missing `.landed` gracefully
5. **Lifecycle `issue_cycle` transition** — `closing:merged → active`
   with correct effects
6. **Slot state `landed → active`** — transition validates

### Integration tests

7. **Full cycle flow** — work-end with non-empty queue: runs review,
   syncs code, closes issue, advances queue, stays active, no `.landed`
8. **Full terminal flow** — work-end with empty queue: runs review,
   syncs code, closes issue, writes `.landed`, archives
9. **Retroactive append** — `.landed` exists, `append_to_queue` with
   `slot_path` clears it and transitions state

---

## References

- `work_end_orchestrator.py:203-215` — StepDef dataclass with skip_fn
- `work_end_orchestrator.py:217-254` — existing skip predicates
- `work_end_orchestrator.py:433-480` — `elevate_plan_inline` (queue detection pattern)
- `work_end_orchestrator.py:353-364` — `_write_landed_script`
- `work_end_orchestrator.py:839-980` — STEPS list
- `project/lifecycle.py:109-132` — TRANSITION_TABLE
- `work-slot/slot_state.py:47-55` — VALID_TRANSITIONS
- `work-slot/plan_manager.py:529-590` — `advance()` signature
- `work-slot/plan_manager.py:831-871` — `append_to_queue()` signature
- `work-slot/slot_metadata.py:192` — `is_slot_landed()`
- Issue #373 — slot 198 incident
- D1-D4 in decisions.md — design rationale
