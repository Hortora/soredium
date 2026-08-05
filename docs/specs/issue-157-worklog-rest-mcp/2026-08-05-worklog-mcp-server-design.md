# Worklog MCP Server — Design Spec

**Issue:** Hortora/soredium#157
**Date:** 2026-08-05
**Status:** Approved
**Parent epic:** #182 (Work Observability)
**Depends on:** #183 (closed — wiring gaps)

## Problem Statement

Claude Code agents cannot query worklog data structurally. The only
options are `python3 -c "import worklog; ..."` or raw `sqlite3` shell-outs.
Neither appears in the tool list, neither has parameter descriptions, and
both require the agent to know import paths and connection setup.

Trellis (always-running Quarkus sidecar) also needs worklog data for its
timeline UI, but that is a separate concern with different transport needs
(REST, JDBC, MCP/SSE). This spec covers the Claude Code agent use case only.

## Design Goal

A Python MCP server (stdio transport) that exposes 4 read-only tools over
`worklog.db`, following the established `garden_mcp_server.py` pattern.
Spawned per session by Claude Code, dies with the session. No always-running
process.

## Scope

### In scope

- FastMCP server with 4 tools wrapping existing `worklog.py` query functions
- Tests using temp SQLite database
- Claude Code MCP server configuration

### Out of scope

- REST endpoints (trellis concern — separate issue in Hortora/trellis)
- MCP over SSE transport (trellis always-on concern)
- Write operations (writes go through skills -> worklog.py -> lifecycle)
- New query functions in worklog.py (4 existing functions are sufficient)
- JDBC/Java reader (trellis concern)
- Schema documentation for cross-language contract (deferred until trellis needs it)

## Architecture

### Why Python, not Quarkus

The read path for Claude Code is per-session stdio. A Quarkus app for 4
read-only SQLite queries would mean JVM startup cost, CDI wiring, and
200MB+ memory for something that lives seconds to hours and may never be
called. The Python server imports `worklog.py` directly — no schema
translation, no impedance mismatch. Same language, same module, same
path normalization.

### Why separate from garden MCP server

Garden is knowledge curation (git repo operations). Worklog is work lifecycle
(SQLite reads). Different domains, different data stores, different failure
modes. Combining them increases startup cost for sessions that need only one.
MCP servers are spawned at session start — a combined server pays the cost of
both domains even when only one is used.

### Connection model

SQLite WAL mode is already configured in `worklog.py:connect()`. The MCP
server is a reader in a separate process. The main Claude process writes
via `worklog.py`. WAL supports concurrent readers + one writer — no
contention.

Connection opened per tool call. Each call: `connect()`, query, `close()`.
Simple, safe, no stale connection bugs across long sessions.

### Schema coupling

The MCP server imports `worklog.py` directly — schema coupling is implicit
and safe (same repo, same import). When trellis adds JDBC access (future),
a documented schema contract will be needed. Not this issue's concern.

## Tools

### `worklog_active`

Returns all active (non-ended) work items.

**Parameters:** none

**Returns:** List of dicts with fields:
- `id`, `branch`, `state`, `location`, `slot_id`, `created_at`
- `repo_path`, `github_repo` (from joined repos table)

**Wraps:** `worklog.active_work(conn)`

### `worklog_events`

Returns filtered event log, newest first.

**Parameters:**
- `since: str | None` — ISO timestamp lower bound
- `event_type: str | None` — filter by event type (e.g. `work-start`, `issue-activate`)
- `repo_path: str | None` — filter by repo path
- `limit: int` — max results (default 100)

**Returns:** List of event dicts with fields:
- `id`, `timestamp`, `event_type`, `work_item_id`, `slot_id`, `repo_path`
- `metadata` — parsed dict (the MCP layer calls `json.loads()` on the raw
  JSON string stored in SQLite, so agents receive a proper object)

**Normalization:** `repo_path` parameter is normalized via `Path.resolve()`
before passing to `event_log()`. This matches `work_item_timeline`'s
normalization and prevents silent mismatches when paths differ in form
(`~/repo` vs `/Users/x/repo`).

**Wraps:** `worklog.event_log(conn, since, event_type, repo_path, limit)`

### `worklog_timeline`

Returns all events for a specific branch, oldest first.

**Parameters:**
- `branch: str` — branch name (e.g. `issue-42-fix-login`)
- `repo_path: str` — repo path for work item lookup

**Returns:** List of event dicts (same shape as `worklog_events`, with
`metadata` parsed to dict)

**Wraps:** `worklog.work_item_timeline(conn, branch, repo_path)`

### `worklog_slots`

Returns slot status, optionally filtered by family root.

**Parameters:**
- `family_root: str | None` — filter by family root path

**Returns:** List of slot dicts with fields:
- `id`, `slot_number`, `family_root`, `state`, `created_at`, `archived_at`

**Wraps:** `worklog.slot_status(conn, family_root)`

## Implementation

### File: `scripts/worklog_mcp_server.py`

```python
#!/usr/bin/env python3
"""
worklog_mcp_server.py — Hortora Worklog MCP Server.

Exposes 4 read-only tools over ~/.hortora/worklog.db via FastMCP:
  worklog_active   — active work items
  worklog_events   — filtered event log
  worklog_timeline — all events for a branch
  worklog_slots    — slot status

Usage (stdio transport):
  python3 worklog_mcp_server.py

Configure in Claude Code settings:
  {
    "mcpServers": {
      "hortora-worklog": {
        "command": "python3",
        "args": ["/path/to/soredium/scripts/worklog_mcp_server.py"]
      }
    }
  }
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP
import worklog

_DB_PATH = os.environ.get('WORKLOG_DB')

mcp = FastMCP("Hortora Worklog")


def _connect():
    return worklog.connect(_DB_PATH) if _DB_PATH else worklog.connect()


def _parse_metadata(rows: list[dict]) -> list[dict]:
    for row in rows:
        raw = row.get("metadata")
        if isinstance(raw, str):
            try:
                row["metadata"] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
    return rows


def _norm_path(p: str | None) -> str | None:
    return str(Path(p).resolve()) if p else None


@mcp.tool()
def worklog_active() -> list | dict:
    """Return all active (non-ended) work items."""
    try:
        conn = _connect()
        try:
            return worklog.active_work(conn)
        finally:
            conn.close()
    except Exception as e:
        return {"error": type(e).__name__, "message": str(e)}


@mcp.tool()
def worklog_events(
    since: str = None,
    event_type: str = None,
    repo_path: str = None,
    limit: int = 100,
) -> list | dict:
    """Return filtered event log, newest first."""
    try:
        conn = _connect()
        try:
            results = worklog.event_log(conn, since=since,
                                         event_type=event_type,
                                         repo_path=_norm_path(repo_path),
                                         limit=limit)
            return _parse_metadata(results)
        finally:
            conn.close()
    except Exception as e:
        return {"error": type(e).__name__, "message": str(e)}


@mcp.tool()
def worklog_timeline(branch: str, repo_path: str) -> list | dict:
    """Return all events for a branch, oldest first."""
    try:
        conn = _connect()
        try:
            results = worklog.work_item_timeline(conn, branch, repo_path)
            return _parse_metadata(results)
        finally:
            conn.close()
    except Exception as e:
        return {"error": type(e).__name__, "message": str(e)}


@mcp.tool()
def worklog_slots(family_root: str = None) -> list | dict:
    """Return slot status, optionally filtered by family root."""
    try:
        conn = _connect()
        try:
            return worklog.slot_status(conn, family_root=family_root)
        finally:
            conn.close()
    except Exception as e:
        return {"error": type(e).__name__, "message": str(e)}


if __name__ == '__main__':
    mcp.run()
```

Inline tool implementations — no per-tool modules. Each tool is a thin
wrapper. If a tool grows complex later, extract then.

### File: `tests/test_worklog_mcp_server.py`

Tests call tool functions directly (no MCP transport). Each test:
1. Creates a temp SQLite database via `worklog.connect(str(tmp_path / "test.db"))`
2. Populates with test data via `worklog.record_*()` functions
3. Sets `WORKLOG_DB` env var to the temp path (via `monkeypatch.setenv`)
   so that `_connect()` in the server routes to the temp database
4. Calls the tool function
5. Asserts return shape and values

Test cases:
- `test_active_returns_empty_on_fresh_db` — no work items
- `test_active_returns_started_items` — work-start recorded, appears in results
- `test_active_excludes_ended_items` — work-end recorded, excluded
- `test_active_returns_error_dict_on_db_failure` — structured error, not raw exception
- `test_events_returns_all_when_unfiltered` — basic event log
- `test_events_filters_by_type` — only matching event_type returned
- `test_events_filters_by_since` — only events after timestamp
- `test_events_respects_limit` — at most N results
- `test_events_normalizes_repo_path` — `~/repo` and `/full/path/repo` match
- `test_events_metadata_is_parsed_dict` — metadata field is dict, not JSON string
- `test_timeline_returns_branch_events` — all events for a specific branch
- `test_timeline_empty_for_unknown_branch` — no events for nonexistent branch
- `test_timeline_metadata_is_parsed_dict` — same metadata check
- `test_slots_returns_all` — slot status
- `test_slots_filters_by_family_root` — only matching family

### Configuration

Add to Claude Code project settings (`.claude/settings.local.json` in soredium):

```json
{
  "mcpServers": {
    "hortora-worklog": {
      "command": "python3",
      "args": ["scripts/worklog_mcp_server.py"]
    }
  }
}
```

## Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| `worklog.py` query function signature changes | MCP server breaks silently (returns wrong data or errors) | Server imports worklog.py directly — Python import errors are immediate. Test suite catches signature drift. |
| SQLite locked by long write transaction | MCP read times out | WAL mode already configured — readers never block on writers. |
| `mcp` package not installed | Server fails to start | Same dependency as garden MCP server — already installed. |
| Large event tables slow queries | Slow tool responses | `event_log` has `limit` parameter (default 100). Timeline queries are per-branch (bounded). |

## Future

- **Trellis REST endpoints** — separate issue in Hortora/trellis. JDBC SQLite reader, JAX-RS endpoints, quarkus-mcp-server tools.
- **Issue-to-branch lookup** — new query: "find work item by issue number" via `work_item_issues` table. Add when agents need it.
- **Duration computation** — "how long was #42 paused?" is client logic from timeline events. Could become a server-side convenience tool.
