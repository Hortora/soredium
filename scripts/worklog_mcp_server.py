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

mcp = FastMCP("Hortora Worklog")


def _connect():
    db_path = os.environ.get('WORKLOG_DB')
    return worklog.connect(db_path) if db_path else worklog.connect()


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
