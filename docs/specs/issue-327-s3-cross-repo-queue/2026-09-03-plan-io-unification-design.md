# Plan I/O Unification — Design Spec

**Issue:** #327 — S3_ACTIVE_ALL_CLOSED fires incorrectly for cross-repo queues
**Branch:** issue-327-s3-cross-repo-queue
**Date:** 2026-09-03

## Problem

`corruption.py`'s S3 check fires false positives when a design issue closes
and spawns cross-repo child issues. Two direct bugs:

1. `check_active_all_closed` only checks `covers` issues against GitHub — never
   checks the queue for remaining uncompleted items
2. Queue regex in `check_queue_consistency` only parses `#N`, not `owner/repo#N`

The root cause is structural: `.plan` parsing is duplicated across the codebase.
13 independent implementations of `## State` field reading, 19 copies of
`covers.split(",")`, and 3 copies of the queue item regex — each with subtly
different behavior. 4/5 commits to `corruption.py` are false-positive fixes
caused by this duplication. Every format evolution (cross-repo refs, epics,
batches) lands in `plan_manager.py` but the corruption detector's inline
copies don't get updated.

## Solution

Extract `project/plan_io.py` — a single module owning all `.plan` file
operations: create, read, update, delete. Every consumer imports from here
instead of reimplementing section walking and field parsing inline.

## Module API

### Data types

```python
@dataclass(frozen=True)
class QueueItem:
    repo: str           # "owner/repo" (always qualified)
    number: int         # issue number
    title: str
    completed: bool
    active: bool

@dataclass(frozen=True)
class PlanState:
    fields: dict[str, str]          # all key:value from ## State
    queue_items: list[QueueItem]    # parsed queue entries
    unparsed_lines: list[str]       # queue lines that didn't match regex
```

`QueueItem` is intentionally simpler than `plan_manager.QueueItem` (which has
8 fields for write/edit operations: batches, tasks, children, is_epic). Read
consumers don't need write machinery.

`unparsed_lines` surfaces lines the regex didn't match — a signal that the
format evolved and the regex didn't. This is what would have caught #327
before it shipped.

### Read operations

```python
def read_plan(plan_path: Path) -> PlanState | None
```
Single-pass parse of `## State` fields and `## Queue` items. Returns `None`
if file doesn't exist. The queue regex matches `plan_manager`'s `_ITEM_RE`
pattern: `owner/repo#N` with optional `(epic)` and `← active` markers.

```python
def read_field(plan_path: Path, field: str) -> str | None
```
Convenience wrapper — reads one field from `## State`. Calls `read_plan()`
internally.

```python
def parse_covers(covers_str: str) -> list[int]
```
Canonical parsing of the `covers` field. `"42,19,32"` → `[42, 19, 32]`.
Strips whitespace, skips empty segments, converts to int. Replaces 19
inline `covers.split(",")` expressions.

```python
def has_uncompleted_items(plan_state: PlanState) -> bool
```
True if any queue item has `completed=False`. The specific helper S3 needs.

### Write operations

```python
def write_field(plan_path: Path, field: str, value: str) -> None
```
Updates a single field in `## State`, preserving all other content. Creates
the field if it doesn't exist. Uses the same section parser as reads.

```python
def write_fields(plan_path: Path, updates: dict[str, str]) -> None
```
Batch update — single file read/write cycle for multiple fields.

### Create operation

```python
def create_plan(plan_path: Path, state_fields: dict[str, str],
                queue_items: list[QueueItem] | None = None) -> None
```
Creates a new `.plan` file with `## State` and optional `## Queue`. Replaces
inline plan-building in `scaffold.py`.

### Delete operation

```python
def remove_plan(plan_path: Path) -> None
```
Deletes the `.plan` file. Single call site for future guards, logging, or
pre-delete validation.

## Corruption fixes (the #327 bugs)

### S3 — check_active_all_closed

After confirming all `covers` issues are CLOSED on GitHub, check the queue:

```python
plan_state = read_plan(plan_path)
if plan_state and has_uncompleted_items(plan_state):
    return None  # design done, implementation continues — not corruption
```

Enriched finding detail when it does fire:

```
"state: active, all covers (74) CLOSED, queue: 0 uncompleted / 0 total items"
```

vs current:

```
"state: active but all issues in covers (74) are CLOSED on GitHub"
```

### S8 — check_queue_consistency

Replace inline queue regex with `read_plan()`. Cross-repo items are now
visible because `plan_io` uses the canonical regex. The title-mismatch skip
logic for cross-repo issues stays (it's domain logic, not parsing).

### check_missing_state

Replace inline `## State` section parser with `read_plan()` — check if
`"state"` is in `fields`.

### Net effect on corruption.py

~80 lines of inline parsing replaced by ~5 import lines. Each check function
focuses on its domain logic, not on how to walk a markdown file.

## Consumer migration

### Read-side (17 files)

| File | Current | Migration |
|---|---|---|
| `project/corruption.py` | `_read_plan_field()` + section parser + queue regex | `read_plan`, `read_field`, `parse_covers`, `has_uncompleted_items` |
| `project/lifecycle.py` | `read_lifecycle_state()`, `read_branch()` | `read_field` |
| `project/work_health.py` | 2 inline section parsers | `read_field` |
| `project/ctx.py` | `covers.split(",")[0]` | `parse_covers(...)[0]` |
| `work-end/work_end_context.py` | Inline dict parser | `read_plan` |
| `work-end/artifact_promote.py` | 2 covers splits | `parse_covers` |
| `work-end/branch_recon.py` | covers split + `lstrip("#")` | `parse_covers` |
| `work-end/verify_slot_close.py` | covers split to ints | `parse_covers` |
| `work-end/work_end_orchestrator.py` | 2 covers splits | `parse_covers` |
| `work-end/close_progress.py` | Inline state read | `read_field` |
| `work-slot/slot_lifecycle.py` | 3 covers splits | `parse_covers` |
| `scripts/worklog.py` | 3 covers splits | `parse_covers` |
| `scripts/audit_attic.py` | Inline branch read | `read_field` |
| `scripts/audit_workspace.py` | Inline branch read | `read_field` |
| `scripts/verify_warnings.py` | Inline branch read | `read_field` |
| `scripts/reconcile_slots.py` | Regex branch read | `read_field` |
| `handover/wrap_orchestrator.py` | covers first-int | `parse_covers` |

### Write-side (1 file)

| File | Current | Migration |
|---|---|---|
| `project/lifecycle.py` | `_write_lifecycle_state()`, `_write_branch()` | `write_field` |

### Create-side (1 file)

| File | Current | Migration |
|---|---|---|
| `work-start/scaffold.py` | Inline plan building | `create_plan` |

### Not migrated (intentionally different domain)

- `work-slot/plan_manager.py` — owns full `QueueItem` with batch/task/child
  machinery for write/edit CLI operations
- `git-squash/commit_gather.py` — parses commit message refs, not `.plan` files
- `scripts/migrate_plan_repos.py` — one-time migration script

## Testing

- Unit tests for `plan_io.py`: parse round-trip, cross-repo queue items,
  unparsed line tracking, covers parsing edge cases, field read/write,
  create/delete
- Update existing `test_corruption.py`: add test for S3 with cross-repo
  queue items (issue acceptance criterion), verify S3 still fires with
  empty queue (regression guard)
- Existing consumer tests serve as integration tests — they verify behavior
  doesn't change after migration

## References

- `project/corruption.py` — 13 field-reader copies, inline queue regex
- `work-slot/plan_manager.py:103-105` — canonical `_ITEM_RE` regex
- `work-slot/plan_manager.py:263-340` — canonical `_parse_queue_lines()`
- 19 `covers.split(",")` call sites (see decisions.md D1 sources)
- Git history: 4/5 commits to corruption.py are false-positive fixes
