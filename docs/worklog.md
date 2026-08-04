# Worklog — Work Event Log Database

SQLite-based event log and state store for the work lifecycle. Tracks work-start, work-end, work-pause, work-resume, slot-create, slot-merge, and slot-archive events across all repos.

**Database location:** `~/.hortora/worklog.db`
**Module:** `~/.claude/lib/worklog.py`
**Schema version:** 1

## Connection

```python
import worklog

conn = worklog.connect()           # default: ~/.hortora/worklog.db
conn = worklog.connect("/path")    # custom path
```

Creates the DB and runs migrations if needed. Uses WAL journal mode and foreign keys.

## Schema

### repos

Registered repositories. Upserted on first use via `ensure_repo()`.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| path | TEXT UNIQUE | Resolved absolute path |
| workspace | TEXT | Workspace path (nullable) |
| family_root | TEXT | Multi-repo family root (nullable) |
| github_repo | TEXT | e.g. `casehubio/engine` (nullable) |
| project_type | TEXT | e.g. `java`, `skills` (nullable) |

### slots

Slot lifecycle state. One row per slot per family.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| slot_number | INTEGER | Slot number within family |
| family_root | TEXT | Absolute path to family root |
| state | TEXT | `active` → `ready` → `landed` → `archived` |
| created_at | TEXT | ISO 8601 UTC |
| archived_at | TEXT | Set when state becomes `archived` |

Unique on `(slot_number, family_root)`.

### work_items

One row per branch per repo. Tracks the lifecycle of a unit of work.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| branch | TEXT | Branch name |
| repo_id | INTEGER FK→repos | |
| state | TEXT | `active` → `paused` → `active` → `ended` |
| location | TEXT | `primary` (normal) or `slot` (in a worktree slot) |
| slot_id | INTEGER FK→slots | Set when location=slot |
| work_path | TEXT | Working directory path (nullable) |
| created_at | TEXT | ISO 8601 UTC |
| ended_at | TEXT | Set when state becomes `ended` |

Unique on `(branch, repo_id)`.

### work_item_issues

Links work items to GitHub issues. Supports multi-issue branches (covers).

| Column | Type | Notes |
|--------|------|-------|
| work_item_id | INTEGER FK→work_items | |
| issue_number | INTEGER | |
| issue_repo | TEXT | e.g. `casehubio/engine` |
| is_primary | INTEGER | 1 for the primary issue, 0 for covered issues |

PK on `(work_item_id, issue_number, issue_repo)`.

### events

Append-only event log. Every state change writes a row.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment, chronological |
| timestamp | TEXT | ISO 8601 UTC |
| event_type | TEXT | See Event Types below |
| work_item_id | INTEGER FK→work_items | Nullable |
| slot_id | INTEGER FK→slots | Nullable |
| repo_path | TEXT | Nullable |
| metadata | TEXT | JSON blob (nullable) |

Indexed on `event_type`, `work_item_id`, `slot_id`.

## Event Types

| Event | Logged by | Metadata |
|-------|-----------|----------|
| `work-start` | `record_work_start()` | — |
| `work-pause` | `record_work_pause()` | — |
| `work-resume` | `record_work_resume()` | — |
| `work-end` | `record_work_end()` | `{"landed_sha": "abc123"}` |
| `slot-create` | `record_slot_create()` | `{"repos": [...], "branch": "..."}` |
| `slot-phase-a` | `record_slot_phase_a()` | — |
| `slot-merge` | `record_slot_merge()` | `{"landed_shas": {"engine": "abc", "iot": "def"}}` |
| `slot-archive` | `record_slot_archive()` | — |

## Automatic Emission

`lifecycle.commit_transition()` automatically logs a transition event and
updates `work_items.state` for every state change. Callers pass `repo_path`
to enable emission:

```python
from lifecycle import transition, commit_transition

result = transition(meta_path, 'work_pause')
execute_effects(result.effects)
commit_transition(meta_path, result, repo_path="/path/to/repo")
```

For transitions with domain metadata:

```python
result = transition(meta_path, 'merge_pass')
sha = execute_merge(result.effects)
commit_transition(meta_path, result, repo_path="/path/to/repo",
    metadata={"landed_sha": sha})
```

Worklog emission is best-effort — failures warn but never block the
`.meta` state write.

### Lifecycle-to-Worklog State Mapping

| Lifecycle state | work_items.state |
|-----------------|------------------|
| scaffolded, active, transitioning, closing:* | active |
| paused | paused |
| idle (from closing:stamped) | ended |

## Recording APIs

All recording functions are wrapped with `@safe` — exceptions are caught and logged as `WARN=worklog_error`, never propagated. The worklog is informational; it must not block operations.

### Repos

```python
repo_id = worklog.ensure_repo(conn, "/path/to/repo",
    workspace="/path/to/workspace",     # optional
    family_root="/path/to/family",      # optional
    github_repo="casehubio/engine",     # optional
    project_type="java")                # optional
```

Upserts — creates if new, updates non-None fields if existing.

### Work Items

```python
# Start work on a branch
wid = worklog.record_work_start(conn, branch="issue-42-spi",
    repo_path="/path/to/repo",
    issue_number=42, issue_repo="casehubio/engine",
    covers="42,43",         # optional — comma-separated issue numbers
    location="primary",     # or "slot"
    slot_id=sid,            # optional — links to slot
    work_path="/path")      # optional

# Pause/resume/end
worklog.record_work_pause(conn, branch="issue-42-spi", repo_path="/path/to/repo")
worklog.record_work_resume(conn, branch="issue-42-spi", repo_path="/path/to/repo")
worklog.record_work_end(conn, branch="issue-42-spi", repo_path="/path/to/repo",
    landed_sha="abc123")   # optional
```

State transitions: `active` → `paused` → `active` → `ended`.

### Slots

```python
# Create a slot (also creates work_items for each repo)
sid = worklog.record_slot_create(conn, slot_number=1,
    family_root="/path/to/family",
    repos=["/path/to/engine", "/path/to/iot"],
    branch="issue-42-spi",
    issue_number=42, issue_repo="casehubio/engine",
    covers="42,43")         # optional

# Phase A complete (ready to land)
worklog.record_slot_phase_a(conn, slot_number=1, family_root="/path")

# Merge (also ends all work_items in the slot)
worklog.record_slot_merge(conn, slot_number=1, family_root="/path",
    landed_shas={"engine": "abc123", "iot": "def456"})

# Archive
worklog.record_slot_archive(conn, slot_number=1, family_root="/path")
```

Slot state transitions: `active` → `archived` (work-end runs the full
close sequence in one invocation). Legacy intermediate states (`ready`,
`landed`) are still recorded by the deprecated `record_slot_phase_a()`
and `record_slot_merge()` functions for backward compatibility.

## Query APIs

```python
# All non-ended work items
items = worklog.active_work(conn)
# Returns: [{id, branch, state, location, slot_id, created_at, repo_path, github_repo}, ...]

# Slot status (optionally filtered by family)
slots = worklog.slot_status(conn, family_root="/path/to/family")
# Returns: [{id, slot_number, family_root, state, created_at, archived_at}, ...]

# Event log (newest first, filterable)
events = worklog.event_log(conn,
    since="2026-07-01T00:00:00",    # optional
    event_type="work-start",         # optional
    repo_path="/path/to/repo",       # optional
    limit=100)                       # default 100
# Returns: [{id, timestamp, event_type, work_item_id, slot_id, repo_path, metadata}, ...]

# Full timeline for a specific branch+repo
timeline = worklog.work_item_timeline(conn, branch="issue-42-spi",
    repo_path="/path/to/repo")
# Returns: events in chronological order
```

## Callers

The worklog is called from these scripts (all calls are non-fatal via `@safe`):

| Script | Events recorded |
|--------|----------------|
| `lifecycle.py` `commit_transition()` | All transition events (automatic) |
| `slot_manager.py` `create_slot()` | `slot-create` + per-repo `work_items` |
| `slot_manager.py` `merge_slot()` | `slot-merge` (ends all work_items) |
| `slot_manager.py` `archive_slot()` | `slot-archive` |
| `work-start/scaffold.py` | `work-start` (via skill instructions, not direct) |
| `work-end` (via skill) | `work-end` |
| `work-pause` (via skill) | `work-pause` |
| `work-resume` (via skill) | `work-resume` |

## Direct SQL

```bash
sqlite3 ~/.hortora/worklog.db

# Recent events
SELECT timestamp, event_type, repo_path FROM events ORDER BY id DESC LIMIT 20;

# Active work
SELECT wi.branch, wi.state, wi.location, r.path
FROM work_items wi JOIN repos r ON wi.repo_id = r.id
WHERE wi.state != 'ended';

# Slot history for a family
SELECT slot_number, state, created_at, archived_at
FROM slots WHERE family_root LIKE '%casehub%'
ORDER BY slot_number;

# Timeline for a branch
SELECT e.timestamp, e.event_type, e.metadata
FROM events e JOIN work_items wi ON e.work_item_id = wi.id
WHERE wi.branch = 'issue-42-spi'
ORDER BY e.id;
```
