# Work Tracking — Cross-Repo Lifecycle Observability

**Date:** 2026-07-26
**Issue:** Hortora/soredium (to be created before implementation)
**Status:** Draft

## Problem

No central view of what work is in flight across repos. Lifecycle state is scattered across `.meta` files, `.pause-stack`, `SLOT.md`, `EPIC-CLOSED.md`, and git branches. Auditing requires scanning each workspace individually. The eidos#100 incident (slot stamped as landed but never merged) proved that without observability, silent failures go undetected.

## Design

### Storage

SQLite at `~/.hortora/worklog.db`. WAL mode for concurrent readers/writers. Auto-created on first access. Schema self-migrates via `PRAGMA user_version`.

### Schema

```sql
CREATE TABLE repos (
    id           INTEGER PRIMARY KEY,
    path         TEXT UNIQUE NOT NULL,
    workspace    TEXT,
    family_root  TEXT,
    github_repo  TEXT,
    project_type TEXT
);

CREATE TABLE work_items (
    id         INTEGER PRIMARY KEY,
    branch     TEXT NOT NULL,
    repo_id    INTEGER NOT NULL REFERENCES repos(id),
    state      TEXT NOT NULL DEFAULT 'active',  -- active, paused, ended
    location   TEXT NOT NULL DEFAULT 'primary', -- primary, slot
    slot_id    INTEGER REFERENCES slots(id),
    work_path  TEXT,
    created_at TEXT NOT NULL,
    ended_at   TEXT,
    UNIQUE(branch, repo_id)
);

CREATE TABLE work_item_issues (
    work_item_id INTEGER NOT NULL REFERENCES work_items(id),
    issue_number INTEGER NOT NULL,
    issue_repo   TEXT NOT NULL,
    is_primary   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (work_item_id, issue_number, issue_repo)
);

CREATE TABLE slots (
    id          INTEGER PRIMARY KEY,
    slot_number INTEGER NOT NULL,
    family_root TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'active', -- active, ready, landed, archived
    created_at  TEXT NOT NULL,
    archived_at TEXT,
    UNIQUE(slot_number, family_root)
);

CREATE TABLE events (
    id           INTEGER PRIMARY KEY,
    timestamp    TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    work_item_id INTEGER REFERENCES work_items(id),
    slot_id      INTEGER REFERENCES slots(id),
    repo_path    TEXT,
    metadata     TEXT  -- JSON blob for event-specific details
);

CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_work_item ON events(work_item_id);
CREATE INDEX idx_events_slot ON events(slot_id);
CREATE INDEX idx_work_items_state ON work_items(state);
```

### Entity model

- **work_item**: one per branch per repo. Branch name is the natural key (git prevents the same branch existing in primary and slot simultaneously). Location tracks whether work is on the primary clone or in a slot.
- **work_item_issues**: junction table. A branch covers 1:N issues (matching `.meta` `covers` field). `is_primary` marks the focal issue.
- **slot**: one per slot number per family root. Lifecycle: active → ready → landed → archived.
- **event**: append-only audit trail. Every state transition is recorded with timestamp and optional metadata JSON.
- **repo**: registered repos with workspace pairings. Upserted on first use.

### Module location

`scripts/worklog.py` in soredium. Copied to `~/.claude/lib/worklog.py` by `sync-local`. Lifecycle scripts add its path to `sys.path` before import.

Schema migrations embedded in the module — `PRAGMA user_version` checked on every `connect()`. DB self-upgrades regardless of which copy of the module opens it.

### API

Write functions (called by lifecycle scripts):

| Function | Called by | When |
|----------|-----------|------|
| `ensure_repo(conn, path, ...)` | work-start, slot_manager | On first encounter |
| `record_work_start(conn, branch, repo_path, issue, ...)` | work-start/scaffold.py | After .meta written |
| `record_work_pause(conn, branch, repo_path)` | work-pause/pause_exec.py | After WIP commit |
| `record_work_resume(conn, branch, repo_path)` | work-resume/resume_exec.py | After branch checkout |
| `record_work_end(conn, branch, repo_path, landed_sha)` | work-end/land_branch.py | After verified merge |
| `record_slot_create(conn, slot_number, family_root, ...)` | slot_manager.create_slot | After SLOT.md written |
| `record_slot_phase_a(conn, slot_number, family_root)` | work-end Phase A | After .phase-a-complete |
| `record_slot_merge(conn, slot_number, family_root, shas)` | slot_manager.merge_slot | After .landed written |
| `record_slot_archive(conn, slot_number, family_root)` | slot_manager.archive_slot | After move to attic |

Query functions (for auditing and future project-manager skill):

| Function | Returns |
|----------|---------|
| `active_work(conn)` | All work_items where state != 'ended', joined with issues and repos |
| `slot_status(conn, family_root=None)` | All slots with current state |
| `event_log(conn, since, event_type, repo_path, limit)` | Filtered event history |
| `work_item_timeline(conn, branch, repo_path)` | All events for a specific work item |

### Failure isolation

All write calls are wrapped with a `safe` decorator. Worklog errors print a warning but never block lifecycle operations. The worklog is observability — losing an event is acceptable, losing work is not.

### Non-functional

- **Timestamps**: UTC ISO 8601, consistent with `.landed` and `.pause-stack` formats
- **Transactions**: each `record_*` call is atomic — work_item + issues + event commit together
- **Concurrency**: WAL mode handles concurrent readers/writers. At lifecycle-event volumes, write contention is negligible.
- **Testing**: `tests/test_worklog.py` per `externalised-scripts-require-tests` protocol. `tmp_path` DBs, covers happy path, migration, concurrent access, failure isolation.

## Future

This schema is the foundation for a project-manager skill: unified backlogs, critical path analysis, "what should I work on next?" recommendations. The query API is designed to support those use cases without schema changes.
