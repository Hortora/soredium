# Issue Transition Wiring — Design Spec

**Issue:** Hortora/soredium#158
**Date:** 2026-08-04
**Status:** Approved
**Parent epic:** #182 (Work Observability)
**Depends on:** #178 (worklog emission in commit_transition — closed)

## Problem Statement

`worklog.py` has `record_issue_activate()` and `record_issue_complete()` functions
(added as part of the worklog schema). No code calls them. Issue-level transitions
within a branch — which issue is being worked, when it completes, when the next
starts — are invisible to worklog.db. Trellis and any future observability tool
cannot answer "what specific issue is being worked right now?"

## Scope

Wire the existing worklog functions into three call sites. No new event types,
no schema changes, no new scripts.

### Out of scope

- Free text mode deferred activation (first issue created during brainstorming) — #180 Phase 3
- REST/MCP exposure of worklog data — #157
- Nested issue lifecycle in slots — #141

## Design

### 1. `plan_manager.advance()` — work-next issue events

Add `repo_path: str | None = None` parameter to `advance()`. After the existing
file writes (`.plan` rewrite at line 329, `.meta` covers update at line 309),
call worklog functions via a new `_emit_issue_events()` helper.

**Ordering:** Worklog recording happens AFTER file writes. This matches the
design spec §4.6 — worklog is always behind-or-equal to file state, never ahead.
A crash between file writes and worklog means files reflect truth and worklog
catches up on next invocation.

**Signature change:**

```python
def advance(plan_path: Path, meta_path: Path,
            repo_path: str | None = None) -> AdvanceResult:
```

When `repo_path` is `None`, worklog calls are skipped (backward compatibility
for any callers that don't have the project path).

**`_emit_issue_events()` helper:**

```python
def _emit_issue_events(meta_path: Path, repo_path: str,
                       completed: int, next_issue: int | None) -> None:
```

- Reads `branch:` and `issue-repo:` from `.meta` (already on disk)
- Imports `worklog` via `sys.path` insertion (same pattern as `lifecycle.py:_emit_to_worklog`)
- Calls `record_issue_complete(conn, branch, repo_path, completed, issue_repo)`
- If `next_issue is not None`: calls `record_issue_activate(conn, branch, repo_path, next_issue, issue_repo)`
- Wrapped in try/except — errors emit `WARN=worklog_error`, never block

**`advance_issue()` dispatch:** Passes `repo_path` through to `plan_manager.advance()`.
The epic_manager fallback path does not accept `repo_path` and gets no worklog
emission — this is acceptable because epic_manager is the deprecated legacy path
(§17 of the parent spec). New branches always use `.plan`.

**Upstream caller:** The skill layer (work SKILL.md Step 5) calls `advance_issue()`
and passes the project repo path from ctx.py's `PROJECT` output.

### 2. `scaffold.py` — initial issue activation at work-start

After the existing `record_work_start()` call (line 136), add
`record_issue_activate()` for the initial issue. Same connection, same
try/except block.

**Guard:** `issue_num > 0`. Free text mode starts with no issue, so no
activation event is emitted. When the first issue is created during
brainstorming (#180 Phase 3), the skill layer will call
`record_issue_activate` at that point — not this issue's scope.

### 3. `plan_manager.complete_active_issue()` — work-end implicit completion

New function in `plan_manager.py`:

```python
def complete_active_issue(plan_path: Path, meta_path: Path,
                          repo_path: str) -> int | None:
```

- Parses `.plan`, finds the active leaf via `_find_active_leaf()`
- If found: calls `_emit_issue_events(meta_path, repo_path, active.issue_number, next_issue=None)`
- Returns the completed issue number, or `None` if no active issue
- Does NOT modify `.plan` — work-end handles file cleanup via the
  `write_plan_closed` lifecycle effect

Called by the work-end skill layer during pre-close sweep. If `.plan`
doesn't exist (non-epic branch, legacy `.epic` branch), the caller skips it.

### 4. Shared helper: `_read_meta_fields()`

Small helper to read key-value pairs from `.meta`:

```python
def _read_meta_fields(meta_path: Path) -> dict[str, str]:
    fields = {}
    for line in meta_path.read_text().splitlines():
        if ':' in line:
            k, _, v = line.partition(':')
            fields[k.strip()] = v.strip()
    return fields
```

Used by `_emit_issue_events()` to extract `branch` and `issue-repo`.

## Test Plan

All tests extend `tests/test_plan_manager.py` and `tests/test_scaffold.py`.
No new test files.

### plan_manager tests

- **advance with repo_path emits worklog events:** Mock worklog module,
  verify `record_issue_complete` called with correct args after advance
- **advance with repo_path=None skips worklog:** Verify no worklog import
  or calls when repo_path is not provided (backward compat)
- **advance worklog error is non-fatal:** Mock worklog to raise, verify
  advance still returns correct AdvanceResult and .plan/.meta are written
- **advance_issue passes repo_path through:** Verify dispatch function
  forwards the parameter
- **complete_active_issue emits issue-complete:** Mock worklog, verify
  correct call
- **complete_active_issue with no active issue returns None:** No worklog
  call, no error
- **complete_active_issue does not modify .plan:** Verify file content
  unchanged after call

### scaffold tests

- **scaffold emits issue-activate after work-start:** Mock worklog,
  verify `record_issue_activate` called with correct issue number and repo
- **scaffold skips issue-activate when issue=0:** Free text mode guard
- **scaffold worklog error is non-fatal:** Mock worklog to raise, verify
  scaffold still completes successfully

## Files Changed

| File | Change |
|------|--------|
| `work-slot/plan_manager.py` | Add `repo_path` param to `advance()`, `_emit_issue_events()`, `_read_meta_fields()`, `complete_active_issue()` |
| `work-start/scaffold.py` | Add `record_issue_activate()` call after `record_work_start()` |
| `tests/test_plan_manager.py` | New test class for worklog emission |
| `tests/test_scaffold.py` | New tests for issue-activate at scaffold time |

## Risks

- **Import path fragility:** `plan_manager.py` imports `worklog` via `sys.path`
  insertion. Same pattern lifecycle.py uses — proven stable. If worklog import
  fails, the `@safe` decorator / try-except catches it.
- **No transactional guarantee across files + worklog:** By design (§4.6 of the
  parent spec). Worklog is observability, not a gate. In the `advance()` path,
  a crash after file writes but before worklog means the next `work-next` call
  records events for the new active issue, leaving a gap for the missed
  transition. In the `scaffold.py` and `complete_active_issue()` paths, there
  is no automatic catch-up — a missed activation or completion event is a
  permanent gap in the worklog timeline. This is acceptable because worklog
  is advisory; no downstream system gates on event completeness.
