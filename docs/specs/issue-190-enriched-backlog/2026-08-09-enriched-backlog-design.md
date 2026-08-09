# Enriched Backlog — Design Spec

**Epic:** #190 — Local enriched backlog
**Issues:** #191 (schema + cache), #192 (trajectory capture), #193 (what-next)
**Branch:** `issue-190-enriched-backlog`

## Problem

"What next" decisions require either querying GitHub every time or relying on
the user's memory. There's no structured way for an LLM to classify work items
by strategic role, readiness, or decay rate. Trajectory notes from completed
work evaporate between sessions.

## Solution

A local enrichment layer on the existing worklog DB (`~/.hortora/worklog.db`)
that caches GitHub issue state with a short TTL and stores per-issue strategic
metadata as the sole source of truth for those fields.

## Architecture

### Module split

- **`worklog.py`** — owns the DB schema (all versions) and lifecycle tracking.
  Gets a v2 migration that adds the two new tables. No new functions beyond
  the migration DDL.
- **`enrichment.py`** (new) — imports `worklog.connect()` for DB access. Owns
  all enrichment CRUD, cache refresh, and query/scoring logic. CLI interface
  for skill invocation.

### Schema — v2 migration

Added to `worklog.py._migrate()` when `PRAGMA user_version < 2`.

**`issue_enrichment`** — one row per issue, composite PK:

```sql
CREATE TABLE IF NOT EXISTS issue_enrichment (
    issue_number   INTEGER NOT NULL,
    issue_repo     TEXT NOT NULL,
    strategic_role TEXT,
    readiness      TEXT,
    decay          TEXT,
    blast_radius   TEXT,
    cohesion       TEXT,
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (issue_number, issue_repo)
);
```

**`trajectory_notes`** — append-only log, one row per note:

```sql
CREATE TABLE IF NOT EXISTS trajectory_notes (
    id           INTEGER PRIMARY KEY,
    issue_number INTEGER NOT NULL,
    issue_repo   TEXT NOT NULL,
    note         TEXT NOT NULL,
    source_branch TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trajectory_issue
    ON trajectory_notes(issue_number, issue_repo);
```

Trajectory is no longer a single field on `issue_enrichment` — it accumulates
over time as separate timestamped notes. Each work-end appends a row rather
than overwriting.

**`github_issue_cache`** — cached GitHub issue state, composite PK:

```sql
CREATE TABLE IF NOT EXISTS github_issue_cache (
    issue_number INTEGER NOT NULL,
    issue_repo   TEXT NOT NULL,
    title        TEXT,
    state        TEXT,
    labels       TEXT,
    body         TEXT,
    cached_at    TEXT NOT NULL,
    PRIMARY KEY (issue_number, issue_repo)
);

CREATE INDEX IF NOT EXISTS idx_cache_repo ON github_issue_cache(issue_repo);
CREATE INDEX IF NOT EXISTS idx_cache_staleness ON github_issue_cache(issue_repo, cached_at);
CREATE INDEX IF NOT EXISTS idx_enrichment_role ON issue_enrichment(strategic_role);
CREATE INDEX IF NOT EXISTS idx_enrichment_decay ON issue_enrichment(decay);
CREATE INDEX IF NOT EXISTS idx_enrichment_readiness ON issue_enrichment(readiness);
```

### Enrichment field vocabulary

| Field | Valid values |
|-------|------------|
| strategic_role | `quick-win`, `load-bearing`, `parallelizable`, `dependency-unlocker`, `consolidation` |
| readiness | `ready`, `needs-design`, `needs-spike`, `needs-decision` |
| decay | `stable`, `compounding`, `perishable` |
| blast_radius | `isolated`, `local`, `cross-cutting`, `foundational` |
| cohesion | free-text area tag |

All enum fields are validated on write. Cohesion is unconstrained free-text.
Trajectory notes live in the separate `trajectory_notes` table (append-only).

### enrichment.py — three layers

**CRUD layer:**

- `upsert_enrichment(conn, issue_number, issue_repo, **fields)` — merges
  with existing row (reads current, overlays non-None fields, writes back).
  Validates enum fields. Sets `updated_at` to now.
- `get_enrichment(conn, issue_number, issue_repo)` → dict or None
- `list_enrichments(conn, issue_repo)` → list of dicts
- `append_trajectory(conn, issue_number, issue_repo, note, source_branch=None)` — appends a row to `trajectory_notes`
- `get_trajectory(conn, issue_number, issue_repo, limit=10)` → list of dicts (most recent first)
- `upsert_cached_issue(conn, issue_number, issue_repo, title, state, labels, body)` — single row. `labels` stored as JSON array of name strings (e.g. `["enhancement", "scale:S"]`).
- `get_cached_issue(conn, issue_number, issue_repo)` → dict or None
- `is_cache_fresh(conn, issue_repo, ttl_seconds=300)` → bool — True if
  all cached rows for this repo have `cached_at` within TTL. False if no
  rows exist.

**Cache refresh layer:**

- `refresh_cache(conn, issue_repo, ttl_seconds=300)` → int (count cached)
  1. Check `is_cache_fresh()` — return early if fresh
  2. Shell out: `gh issue list --state open --json number,title,state,labels,body --limit 500 --repo <repo>`
  3. Parse JSON. If result is empty, warn and return 0 — do NOT delete
     existing cache (guards against auth failures returning empty lists)
  4. Wrap steps 4-5 in a single transaction:
     a. Upsert each issue (labels stored as `json.dumps([l["name"] for l in labels])`)
     b. Delete cache rows whose `issue_number` is not in the fetched set
        (closed since last refresh)
  5. Return count
- On subprocess failure (gh not found, auth error, network): warn to stderr, return 0.
  Cache staleness is never fatal. Existing cache is preserved on failure.

**Query layer:**

- `what_next(conn, issue_repo, mode="general", cohesion_tag=None, limit=5)` → list of dicts

  Each result: `{issue_number, issue_repo, title, score, reasoning, enriched, strategic_role, readiness, decay, blast_radius, cohesion, recent_trajectory}`

  Query modes and scoring:

  | Mode | Filter | Primary weight |
  |------|--------|---------------|
  | `general` | state=OPEN | Weighted composite of all factors |
  | `quick-wins` | role=quick-win, readiness=ready | Scale (from labels: XS > S > M) |
  | `critical-path` | role=load-bearing | Blocks count (from labels) |
  | `parallelizable` | blast_radius=isolated, readiness=ready | Independence score |
  | `compounding` | decay=compounding | Time since last update |
  | `cohesion` | cohesion matches tag | Recency of related trajectory notes |

  Un-enriched issues (in cache but no enrichment row) get `score: 0, enriched: false`.
  They appear in results so the LLM can classify them.

### CLI interface

```
python3 scripts/enrichment.py upsert --issue N --repo OWNER/REPO [--role X] [--readiness X] [--decay X] [--blast-radius X] [--cohesion X]
python3 scripts/enrichment.py trajectory --issue N --repo OWNER/REPO --text "..." [--branch issue-191-schema]
python3 scripts/enrichment.py get --issue N --repo OWNER/REPO
python3 scripts/enrichment.py list --repo OWNER/REPO
python3 scripts/enrichment.py refresh --repo OWNER/REPO [--ttl 300]
python3 scripts/enrichment.py what-next --repo OWNER/REPO [--mode general] [--cohesion-tag X] [--limit 5]
```

All output is JSON (single object or array). Exit code 0 on success, 1 on error.

### Integration — work-end (#192)

New step in work-end SKILL.md. Placement: after the `closing:promoted` state
(artifacts promoted) but before `closing:pushed` (branch pushed). This is
after all code and artifact work is complete but before the branch leaves the
local machine — if enrichment capture fails, the branch can still be pushed
and stamped without data loss.

1. LLM generates a trajectory note for the completed issue(s) and proposes
   2-3 enrichment updates for sibling/related issues
2. Present proposed updates in a table for user confirmation
3. On YES, call `enrichment.py trajectory` and `enrichment.py upsert` per update

### Integration — work-start (#193)

Lives in the `work` skill router (Step 1b), not inside `work-start`. Triggers
when the user invokes `work` from main without specifying an issue number —
the moment they're deciding what to do next.

1. Call `enrichment.py refresh --repo <repo>` (ensures cache is fresh)
2. Call `enrichment.py what-next --repo <repo>`
3. Present ranked recommendation with reasoning and metadata
4. User picks from recommendations or specifies something else

### Not in scope

- #194 (trellis dashboard integration) — separate slot, read-only consumer
- Automatic enrichment seeding — starts empty, populated via work-end over time
- Semantic search / neocortex — future possibility, not a dependency

## Testing

- Unit tests for all CRUD operations (pytest, tmp_path DB)
- Unit tests for cache freshness logic (mock time)
- Unit tests for query modes (seed enrichment + cache data, verify ranking)
- Integration test for `refresh_cache` with mocked subprocess (capture `gh` call, return fixture JSON)
- Integration test for v2 migration (create v1 DB, connect again, verify new tables exist)
- CLI tests via subprocess (verify JSON output, exit codes)

## Files changed

| File | Change |
|------|--------|
| `scripts/worklog.py` | v2 migration DDL in `_migrate()`, bump `SCHEMA_VERSION` |
| `scripts/enrichment.py` | New — CRUD, cache refresh, queries, CLI |
| `tests/test_enrichment.py` | New — all enrichment tests |
| `tests/test_worklog.py` | Add v2 migration test |
| `work-end/SKILL.md` | New trajectory capture step |
| `work/SKILL.md` or `work-start/SKILL.md` | New what-next recommendation step |
