#!/usr/bin/env python3
"""Record every lifecycle action in the worklog (Hortora/soredium#575).

The script that performs an action records it, here, at the moment it
happens: start, each pipeline step, wrap, end, land, stamp, close, publish,
promote, blog publish, pause, resume. Recording never fails the action it
records: any error becomes one WARN line on stderr.

Issue references are passed and stored in full form, owner/repo#N.

Usage:
    worktrace.py record action=<name> [repo=<path>] [branch=<name>] [key=value ...]
    worktrace.py show [limit=<n>] [action=<name>]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent


def _worklog():
    """The worklog module, whichever copy this process already uses.

    Only functions every installed copy has are called (connect, find_work_item,
    record_work_start, record_work_end), so an older copy on the path still records.
    """
    if "worklog" in sys.modules:
        return sys.modules["worklog"]
    for candidate in (Path.home() / ".claude" / "lib", _HERE.parent / "scripts"):
        if (candidate / "worklog.py").is_file() and str(candidate) not in sys.path:
            sys.path.append(str(candidate))
    import worklog
    return worklog


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _norm(path) -> str:
    return str(Path(str(path)).resolve())


def _warn(action: str, error: Exception) -> None:
    print(f"WARN=worklog_not_recorded action={action} detail={error}", file=sys.stderr)


def _plain(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    return str(value)


def record(action: str, /, repo=None, branch: str = "", **details) -> bool:
    """Record one action. Returns whether it was written; never raises."""
    try:
        worklog = _worklog()
        conn = worklog.connect()
        try:
            meta = {k: _plain(v) for k, v in details.items() if v not in (None, "", [], {})}
            if branch:
                meta.setdefault("branch", branch)
            item = worklog.find_work_item(conn, branch, _norm(repo)) if branch and repo else None
            conn.execute(
                "INSERT INTO events (timestamp, event_type, work_item_id, repo_path, metadata) "
                "VALUES (?, ?, ?, ?, ?)",
                (_now(), action, item, _norm(repo) if repo else None,
                 json.dumps(meta) if meta else None))
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as error:          # recording must never fail the action
        _warn(action, error)
        return False


def _issue_parts(issue: str) -> tuple[str, int]:
    repo, _, number = (issue or "").partition("#")
    return repo, int(number) if number.isdigit() else 0


def work_started(repo, branch: str, issue: str = "", covers: str = "",
                 location: str = "primary", work_path: str = "") -> bool:
    """Make sure the work item for this branch exists, whichever path started it."""
    try:
        worklog = _worklog()
        issue_repo, number = _issue_parts((issue or covers).split(",")[0].strip())
        conn = worklog.connect()
        try:
            open_item = conn.execute(
                "SELECT wi.id FROM work_items wi JOIN repos r ON wi.repo_id = r.id "
                "WHERE wi.branch=? AND r.path=? AND wi.state != 'ended'",
                (branch, _norm(repo))).fetchone()
            if open_item is None:
                worklog.record_work_start(conn, branch, _norm(repo), number, issue_repo,
                                          covers=None, location=location,
                                          work_path=work_path or None)
        finally:
            conn.close()
        if covers and "," in covers:
            record("work-covers", repo=repo, branch=branch, covers=covers)
        return True
    except Exception as error:
        _warn("work-start", error)
        return False


def work_ended(repo, branch: str, sha: str = "") -> bool:
    """End the work item for this branch in this repo, if there is one."""
    try:
        worklog = _worklog()
        conn = worklog.connect()
        try:
            worklog.record_work_end(conn, branch, _norm(repo), landed_sha=sha or None)
        finally:
            conn.close()
        return True
    except Exception as error:
        _warn("work-end", error)
        return False


def recent(limit: int = 30, action: str = "") -> list[dict]:
    worklog = _worklog()
    conn = worklog.connect()
    try:
        query = "SELECT timestamp, event_type, repo_path, metadata FROM events"
        params: list = []
        if action:
            query += " WHERE event_type = ?"
            params.append(action)
        rows = conn.execute(query + " ORDER BY id DESC LIMIT ?", (*params, limit)).fetchall()
    finally:
        conn.close()
    return [dict(timestamp=r["timestamp"], action=r["event_type"], repo=r["repo_path"] or "",
                 details=json.loads(r["metadata"]) if r["metadata"] else {}) for r in rows]


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("record", "show"):
        print(__doc__.strip())
        return 2
    args = dict(a.split("=", 1) for a in argv[1:] if "=" in a)
    if argv[0] == "record":
        action = args.pop("action", "")
        if not action:
            print("ERROR=missing_action")
            return 2
        written = record(action, repo=args.pop("repo", None), branch=args.pop("branch", ""), **args)
        print(f"RECORDED={'yes' if written else 'no'}")
        return 0
    for row in reversed(recent(int(args.get("limit", "30")), args.get("action", ""))):
        details = " ".join(f"{k}={v}" for k, v in row["details"].items())
        print(f"{row['timestamp'][:19]} {row['action']:<24} {Path(row['repo']).name:<24} {details}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
