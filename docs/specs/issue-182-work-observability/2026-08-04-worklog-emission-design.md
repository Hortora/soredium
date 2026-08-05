# Worklog Event Emission — Design Spec

**Issue:** #178 (child of #182 Work Observability epic)
**Date:** 2026-08-04
**Scope:** Wire automatic worklog event emission into `commit_transition()`

## Problem

`commit_transition()` writes lifecycle state to `.meta` but doesn't emit worklog
events. Callers (skill scripts, scaffold.py, slot_manager.py) call worklog
recording functions separately — and can forget. Some transitions (the entire
closing sequence: `review_pass`, `promote_pass`, `push_pass`, `merge_pass`,
`stamp_pass`, `cleanup_pass`) have no worklog events at all.

The existing recording functions (`record_work_pause`, `record_work_resume`, etc.)
conflate two concerns: work item state updates AND event logging. This prevents
moving emission into the state machine without either duplicating events or
pulling resource management along.

## Design

### Principle

The state machine is the single authority on state. It owns ALL state changes
(`.meta` on disk, `work_items.state` in worklog) and ALL event emission. Callers
own resource CREATION only.

### Changes to lifecycle.py

`commit_transition()` gains two optional parameters:

```python
def commit_transition(
    meta_path: Path,
    result: TransitionResult,
    repo_path: str | None = None,
    metadata: dict | None = None,
) -> None:
```

After the existing `.meta` validation and write, it calls `_emit_to_worklog()`:

```python
def _emit_to_worklog(
    meta_path: Path,
    result: TransitionResult,
    repo_path: str,
    metadata: dict | None,
) -> None:
    """Best-effort worklog emission. Never blocks."""
    try:
        from scripts import worklog
        conn = worklog.connect()
        branch = _read_branch(meta_path)
        wid = worklog.find_work_item(conn, branch, repo_path)

        # Update work_items.state
        wl_state = _LIFECYCLE_TO_WORKLOG.get(result.new_state)
        if wl_state and wid:
            worklog.update_work_item_state(conn, wid, wl_state)

        # Log transition event
        event_meta = {
            'from_state': result.from_state,
            'to_state': result.new_state,
        }
        if metadata:
            event_meta.update(metadata)
        worklog.log_transition(
            conn, result.event,
            work_item_id=wid,
            repo_path=repo_path,
            metadata=event_meta,
        )
        conn.close()
    except Exception as e:
        print(f"WARN=worklog_error detail={e}")
```

### Lifecycle-to-worklog state mapping

| Lifecycle state | work_items.state | Notes |
|---|---|---|
| `scaffolded` | `active` | Work item already created by scaffold |
| `active` | `active` | — |
| `transitioning` | `active` | Mid-issue-advance, still working |
| `paused` | `paused` | — |
| `closing:*` | `active` | Still working (closing is active work) |
| `idle` (from `closing:stamped`) | `ended` | Also sets `ended_at` |

### Changes to worklog.py

Extract state management from event logging. Add three public functions:

```python
def find_work_item(conn, branch, repo_path):
    """Find work item ID by branch and repo. Returns None if not found."""
    # Existing _find_work_item logic, made public

def update_work_item_state(conn, work_item_id, new_state):
    """Update work_items.state. Sets ended_at when state is 'ended'."""

def log_transition(conn, event_name, work_item_id=None,
                   repo_path=None, metadata=None):
    """Log a lifecycle transition event."""
```

These are thin wrappers around existing internal functions. No schema changes.

### Changes to callers

**scaffold.py:** keeps `record_work_start()` call — this creates the work item
row with issue links, covers, location. This is resource creation, not state
management. No change needed.

**slot_manager.py:** keeps `record_slot_create()` — creates slot row and per-repo
work items. No change needed.

**Skill instructions (work-pause, work-resume, work-end):** remove explicit
`worklog.record_work_pause()` / `record_work_resume()` / `record_work_end()` calls.
Add `repo_path=` to their `commit_transition()` calls instead.

**work-end closing sequence:** pass domain metadata where available:
```python
# After merge step
commit_transition(meta, result, repo_path=repo_path,
                  metadata={'landed_sha': sha})

# After archive step
commit_transition(meta, result, repo_path=repo_path,
                  metadata={'promoted': file_list})
```

### Event type mapping

Transition events use the lifecycle event name directly:

| Lifecycle event | Worklog event_type | Metadata |
|---|---|---|
| `work` | `work` | `{from_state, to_state}` |
| `auto_setup` | `auto_setup` | `{from_state, to_state}` |
| `work_pause` | `work_pause` | `{from_state, to_state}` |
| `work_resume` | `work_resume` | `{from_state, to_state}` |
| `work_end` | `work_end` | `{from_state, to_state}` |
| `review_pass` | `review_pass` | `{from_state, to_state}` |
| `promote_pass` | `promote_pass` | `{from_state, to_state}` |
| `push_pass` | `push_pass` | `{from_state, to_state}` |
| `merge_pass` | `merge_pass` | `{from_state, to_state, landed_sha}` |
| `stamp_pass` | `stamp_pass` | `{from_state, to_state}` |
| `cleanup_pass` | `cleanup_pass` | `{from_state, to_state}` |
| `work_next` | `work_next` | `{from_state, to_state}` |
| `auto_refresh` | `auto_refresh` | `{from_state, to_state}` |
| `abort_close` | `abort_close` | `{from_state, to_state}` |
| `slot_create` | `slot_create` | `{from_state, to_state}` |

### Import path

`lifecycle.py` lives at `project/lifecycle.py`. `worklog.py` lives at
`scripts/worklog.py`. The import is lazy (inside `_emit_to_worklog()`, not
at module level) so lifecycle.py can be imported without worklog.py on the
path. The path to `scripts/` is resolved relative to the repository root
via `meta_path` ancestry. If worklog.py is not importable, the warning
fires and execution continues.

### Graceful degradation

The entire `_emit_to_worklog()` call is wrapped in try/except. Failures:
- Missing worklog.py → warn, continue
- Missing worklog.db → warn, continue
- SQL error → warn, continue
- No work item found → log event without work_item_id linkage

The `.meta` write (authoritative state) has already succeeded before
worklog emission is attempted. Worklog is observability, never a gate.

### What this does NOT change

- worklog.db schema — no new tables, no new columns, no migrations
- Existing query APIs — `active_work()`, `event_log()`, `work_item_timeline()` work unchanged
- `record_work_start()` — still called by scaffold.py for work item creation
- `record_slot_create()` — still called by slot_manager.py for slot/work-item creation
- `record_issue_activate()` / `record_issue_complete()` — owned by #158, not this issue

## Testing

Per the `externalised-scripts-require-tests` protocol:

1. **Unit tests for lifecycle.py changes:**
   - `commit_transition()` with `repo_path` emits worklog event
   - `commit_transition()` without `repo_path` skips worklog (backward compat)
   - `commit_transition()` with metadata merges into event metadata
   - Worklog failure doesn't prevent `.meta` state write
   - Work item state updates match the lifecycle-to-worklog mapping
   - `ended_at` is set when transitioning to idle

2. **Unit tests for worklog.py additions:**
   - `find_work_item()` returns correct ID
   - `update_work_item_state()` updates state column
   - `update_work_item_state()` sets `ended_at` for `ended`
   - `log_transition()` writes event with merged metadata

3. **Integration test:**
   - Full transition cycle (idle → scaffolded → active → paused → active → closing:* → idle) produces correct event trail in worklog.db

## Done when

- `commit_transition()` emits a worklog event for every transition automatically
- Work item state in worklog.db stays in sync with lifecycle state
- All existing tests pass
- New tests cover emission, state mapping, graceful degradation
- No caller-side event emission for transitions handled by the state machine
