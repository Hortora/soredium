# Clone Guard Decision Flow and Wrap Offer Suppression

**Issue:** Hortora/soredium#590
**Date:** 2026-11-23
**Branch:** issue-590-work-start-create-clone

## Problem

Two related UX problems in the work pipeline:

1. **Clone guard** (`work.py:162-195`) emits `ACTION=stop` with a command string the user must copy-paste. Should be an `ACTION=decision` with options, following the existing move-on-gate pattern.

2. **Wrap offer on session start** — `work_route.py:78` sets `offer = bool(done)` unconditionally, so any route with done-but-not-closed items triggers `OFFER=wrap_or_continue`, including the `continue` path a fresh session hits. Work end requires current session context (review material, decisions, diary) and should never be offered cold.

## Design

### Change 1 — Conditional wrap offer (`work_route.py`)

In `route()`, `offer` is set `True` only when the routed command is `done`. For `continue`, `start`, and `resume`, done items appear as `DONE_WAITING=N` in the output but do not trigger the `OFFER=wrap_or_continue` decision gate.

**Before:** `offer = bool(done)` (line 78)
**After:** `offer` stays `False` for all routes; `done_waiting = len(done)` is always set. The `done` command's completion handler in `work.py` sets `OFFER=wrap_or_continue` after marking the item done.

### Change 2 — Remove stop-for-done-items path (`work_route.py`)

Lines 131-134: when only done items remain and no active item exists, the current code returns `stop="end"` with `reason="done_items_await_close"`. Replace with an informational route that reports done items waiting but does not gate. The user runs `work end` explicitly.

### Change 3 — Clone guard decision (`work.py:162-195`)

Replace `ACTION=stop` with `ACTION=decision` and `DECISION=clone_guard`. Two sub-cases:

**Clone doesn't exist:**
```
ACTION=decision
DECISION=clone_guard
DETAIL=<family> uses clones and <repo> has none yet
OPTIONS=create_and_open,stop
HANDLER=handlers/clone-guard.md
```

**Clone already exists:**
```
ACTION=decision
DECISION=clone_guard
DETAIL=<repo> has a clone at <path>
OPTIONS=open_clone,stop
HANDLER=handlers/clone-guard.md
```

### Change 4 — Clone guard handler (`handlers/clone-guard.md`)

New handler file following the move-on-gate pattern. Presents options via the LLM:

- **create_and_open (Recommended when clone missing):** Run `clone_manager.create_clone()`, record via worktrace, emit `CREATED=yes`, `CLONE_PATH=`, `NEXT=open the session in <workspace-path>`.
- **open_clone (Recommended when clone exists):** Emit `NEXT=open the session in <workspace-path>`.
- **stop:** Exit cleanly, no further action.

### Change 5 — Decision callback in `work.py`

Add `clone_guard` to the decision dispatch in `main()`. When `choice=create_and_open`:
1. Call `clone_manager.create_clone(family_root, repo)`
2. Record the action via `worktrace.record()`
3. Print `CREATED=yes`, `CLONE_PATH=`, `NEXT=`

When `choice=open_clone` or `choice=stop`, print `NEXT=` or exit.

## Files Changed

| File | Change |
|------|--------|
| `project/work_route.py` | Remove unconditional `offer = bool(done)`, add `done_waiting` field to Route |
| `project/work.py` | Clone guard emits `ACTION=decision`; `done` command emits `OFFER=` after completion; decision callback for `clone_guard` |
| `work/handlers/clone-guard.md` | New handler file |
| `docs/development/lifecycle-maintainer-guide.md` | Update clone guard documentation |

## Testing

| Test | Verifies |
|------|----------|
| `continue` with done items emits `DONE_WAITING=N` but not `OFFER=` | Wrap offer suppression |
| `done` still emits `OFFER=wrap_or_continue` | Intentional offer preserved |
| `done_items_await_close` stop path removed | No stop gate on done items |
| Clone guard emits `ACTION=decision` not `ACTION=stop` | Decision flow |
| Clone guard with `choice=create_and_open` creates clone and records worktrace | Creation callback |
| Clone guard with `choice=open_clone` emits correct `NEXT=` | Existing clone path |
| Clone guard with `choice=stop` exits cleanly | Stop path |
| Guard removed → test fails | Protocol: a-test-must-fail-with-the-rule-removed |

## Protocols

- **a-read-never-writes:** The guard itself remains read-only detection. Clone creation happens in the callback, not the guard.
- **the-script-that-acts-records-it:** Clone creation records via worktrace.
- **a-test-must-fail-with-the-rule-removed:** Test that removing the guard allows work to proceed in a canonical repo.

## References

- `project/work.py:162-195` — current clone guard
- `project/work_route.py:78` — `offer = bool(done)`
- `project/work_route.py:131-134` — stop-for-done-items path
- `project/clone_manager.py:51` — `create_clone()`
- `work/handlers/move-on-gate.md` — model handler for decision pattern
- `docs/protocols/a-read-never-writes.md`
- `docs/protocols/the-script-that-acts-records-it.md`
- `docs/protocols/a-test-must-fail-with-the-rule-removed.md`
