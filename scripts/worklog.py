"""
worklog.py — Cross-repo work lifecycle tracking

SQLite-based event log and state store for work-start, work-end,
work-pause, work-resume, slot-create, slot-merge, slot-archive events.
"""

import datetime
import functools
import json
import os
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 4

DEFAULT_DB = os.path.expanduser("~/.hortora/worklog.db")

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS repos (
    id           INTEGER PRIMARY KEY,
    path         TEXT UNIQUE NOT NULL,
    workspace    TEXT,
    family_root  TEXT,
    github_repo  TEXT,
    project_type TEXT
);

CREATE TABLE IF NOT EXISTS slots (
    id          INTEGER PRIMARY KEY,
    slot_number INTEGER NOT NULL,
    family_root TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL,
    archived_at TEXT,
    UNIQUE(slot_number, family_root)
);

CREATE TABLE IF NOT EXISTS work_items (
    id         INTEGER PRIMARY KEY,
    branch     TEXT NOT NULL,
    repo_id    INTEGER NOT NULL REFERENCES repos(id),
    state      TEXT NOT NULL DEFAULT 'active',
    location   TEXT NOT NULL DEFAULT 'primary',
    slot_id    INTEGER REFERENCES slots(id),
    work_path  TEXT,
    created_at TEXT NOT NULL,
    ended_at   TEXT,
    UNIQUE(branch, repo_id)
);

CREATE TABLE IF NOT EXISTS work_item_issues (
    work_item_id INTEGER NOT NULL REFERENCES work_items(id),
    issue_number INTEGER NOT NULL,
    issue_repo   TEXT NOT NULL,
    is_primary   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (work_item_id, issue_number, issue_repo)
);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY,
    timestamp    TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    work_item_id INTEGER REFERENCES work_items(id),
    slot_id      INTEGER REFERENCES slots(id),
    repo_path    TEXT,
    metadata     TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_work_item ON events(work_item_id);
CREATE INDEX IF NOT EXISTS idx_events_slot ON events(slot_id);
CREATE INDEX IF NOT EXISTS idx_work_items_state ON work_items(state);
"""

SCHEMA_V2 = """
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
"""

SCHEMA_V3 = """
ALTER TABLE slots ADD COLUMN resolution TEXT;
"""

SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS session_boundaries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    mode         TEXT NOT NULL,
    branch       TEXT,
    issue_repo   TEXT,
    issue_number INTEGER,
    steps_json   TEXT,
    timestamp    TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _norm(path: str) -> str:
    return str(Path(path).resolve())


def _migrate(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current < 1:
        conn.executescript(SCHEMA_V1)
    if current < 2:
        conn.executescript(SCHEMA_V2)
    if current < 3:
        conn.executescript(SCHEMA_V3)
    if current < 4:
        conn.executescript(SCHEMA_V4)
    if current < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    _migrate(conn)
    return conn


def safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            print(f"WARN=worklog_error detail={e}")
            return None
    return wrapper


def _log_event(conn: sqlite3.Connection, event_type: str,
               work_item_id: int | None = None,
               slot_id: int | None = None,
               repo_path: str | None = None,
               metadata: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO events (timestamp, event_type, work_item_id, slot_id, repo_path, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (_now(), event_type, work_item_id, slot_id, repo_path,
         json.dumps(metadata) if metadata else None),
    )


def find_work_item(conn: sqlite3.Connection, branch: str,
                   repo_path: str) -> int | None:
    """Find work item ID by branch and repo path. Public API for lifecycle integration."""
    normalized = _norm(repo_path)
    row = conn.execute(
        "SELECT wi.id FROM work_items wi "
        "JOIN repos r ON wi.repo_id = r.id "
        "WHERE wi.branch=? AND r.path=?",
        (branch, normalized),
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        "SELECT wi.id FROM work_items wi "
        "WHERE wi.branch=? AND wi.state != 'ended' "
        "ORDER BY wi.created_at DESC LIMIT 1",
        (branch,),
    ).fetchone()
    return row["id"] if row else None


_find_work_item = find_work_item


def _find_slot(conn: sqlite3.Connection, slot_number: int,
               family_root: str) -> int | None:
    normalized = _norm(family_root)
    row = conn.execute(
        "SELECT id FROM slots WHERE slot_number=? AND family_root=?",
        (slot_number, normalized),
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        "SELECT id FROM slots WHERE slot_number=? AND family_root=?",
        (slot_number, family_root),
    ).fetchone()
    return row["id"] if row else None


def reserve_slot_number(conn: sqlite3.Connection,
                        family_root: str) -> int:
    """Allocate next slot number and insert a pending row. No @safe."""
    family_root = _norm(family_root)
    row = conn.execute(
        "SELECT MAX(slot_number) FROM slots WHERE family_root=?",
        (family_root,),
    ).fetchone()
    next_num = (row[0] or 0) + 1
    conn.execute(
        "INSERT INTO slots (slot_number, family_root, state, created_at) "
        "VALUES (?, ?, 'pending', ?)",
        (next_num, family_root, _now()),
    )
    conn.commit()
    return next_num


def confirm_slot_create(conn: sqlite3.Connection, slot_number: int,
                        family_root: str, repos: list[str],
                        branch: str, issue_number: int,
                        issue_repo: str,
                        covers: str | None = None) -> int:
    """Confirm a pending slot reservation. No @safe — errors propagate."""
    family_root = _norm(family_root)
    sid = _find_slot(conn, slot_number, family_root)
    if sid is None:
        raise ValueError(f"No pending slot {slot_number} for {family_root}")
    conn.execute("UPDATE slots SET state='active' WHERE id=?", (sid,))
    issue_nums = [int(n.strip()) for n in (covers or str(issue_number)).split(",") if n.strip()]
    for repo_path in repos:
        repo_id = _ensure_repo_strict(conn, repo_path, family_root=family_root)
        wi_cur = conn.execute(
            "INSERT INTO work_items (branch, repo_id, state, location, slot_id, created_at) "
            "VALUES (?, ?, 'active', 'slot', ?, ?)",
            (branch, repo_id, sid, _now()),
        )
        wid = wi_cur.lastrowid
        for num in issue_nums:
            conn.execute(
                "INSERT INTO work_item_issues (work_item_id, issue_number, issue_repo, is_primary) "
                "VALUES (?, ?, ?, ?)",
                (wid, num, issue_repo, 1 if num == issue_number else 0),
            )
    _log_event(conn, "slot-create", slot_id=sid,
               metadata={"repos": repos, "branch": branch})
    conn.commit()
    return sid


def fail_slot(conn: sqlite3.Connection, slot_number: int,
              family_root: str) -> None:
    """Transition a slot to failed state. Works for both pending and active.
    Preserves audit trail — no deletion. No @safe."""
    family_root = _norm(family_root)
    conn.execute(
        "UPDATE slots SET state='failed' WHERE slot_number=? AND family_root=?",
        (slot_number, family_root),
    )
    conn.commit()


def record_session_boundary(conn: sqlite3.Connection,
                            mode: str, branch: str,
                            issue_repo: str = "",
                            issue_number: int = 0,
                            steps: dict | None = None) -> None:
    """Record a session boundary event (close or wrap). No @safe."""
    conn.execute(
        "INSERT INTO session_boundaries (mode, branch, issue_repo, issue_number, steps_json, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (mode, branch, issue_repo, issue_number,
         json.dumps(steps) if steps else "{}", _now()),
    )
    conn.commit()


def find_reusable_slot(conn: sqlite3.Connection,
                       family_root: str) -> tuple[int, list[int]] | None:
    """Find reusable pending/failed slots for a family_root.
    Returns (highest_number, [other_numbers]) or None."""
    family_root = _norm(family_root)
    rows = conn.execute(
        "SELECT slot_number FROM slots "
        "WHERE family_root=? AND state IN ('pending', 'failed') "
        "ORDER BY slot_number DESC",
        (family_root,),
    ).fetchall()
    if not rows:
        return None
    highest = rows[0][0]
    others = [r[0] for r in rows[1:]]
    return highest, others


# --- Repos ---

@safe
def ensure_repo(conn: sqlite3.Connection, path: str,
                workspace: str | None = None,
                family_root: str | None = None,
                github_repo: str | None = None,
                project_type: str | None = None) -> int | None:
    path = _norm(path)
    if family_root:
        family_root = _norm(family_root)
    row = conn.execute("SELECT id FROM repos WHERE path=?", (path,)).fetchone()
    if row:
        updates = {}
        if workspace is not None:
            updates["workspace"] = workspace
        if family_root is not None:
            updates["family_root"] = family_root
        if github_repo is not None:
            updates["github_repo"] = github_repo
        if project_type is not None:
            updates["project_type"] = project_type
        if updates:
            sets = ", ".join(f"{k}=?" for k in updates)
            conn.execute(f"UPDATE repos SET {sets} WHERE id=?",
                         (*updates.values(), row["id"]))
            conn.commit()
        return row["id"]
    cur = conn.execute(
        "INSERT INTO repos (path, workspace, family_root, github_repo, project_type) "
        "VALUES (?, ?, ?, ?, ?)",
        (path, workspace, family_root, github_repo, project_type),
    )
    conn.commit()
    return cur.lastrowid


def _ensure_repo_strict(conn: sqlite3.Connection, path: str,
                        family_root: str | None = None) -> int:
    """Like ensure_repo but raises on failure. No @safe."""
    path = _norm(path)
    if family_root:
        family_root = _norm(family_root)
    row = conn.execute("SELECT id FROM repos WHERE path=?", (path,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO repos (path, family_root) VALUES (?, ?)",
        (path, family_root),
    )
    conn.commit()
    return cur.lastrowid


# --- Work Items ---

@safe
def record_work_start(conn: sqlite3.Connection, branch: str, repo_path: str,
                      issue_number: int, issue_repo: str,
                      covers: str | None = None,
                      location: str = "primary",
                      slot_id: int | None = None,
                      work_path: str | None = None) -> int | None:
    repo_id = ensure_repo(conn, repo_path)
    if repo_id is None:
        return None
    cur = conn.execute(
        "INSERT INTO work_items (branch, repo_id, state, location, slot_id, work_path, created_at) "
        "VALUES (?, ?, 'active', ?, ?, ?, ?)",
        (branch, repo_id, location, slot_id, work_path, _now()),
    )
    wid = cur.lastrowid
    issue_nums = [int(n.strip()) for n in (covers or str(issue_number)).split(",") if n.strip()]
    for num in issue_nums:
        conn.execute(
            "INSERT INTO work_item_issues (work_item_id, issue_number, issue_repo, is_primary) "
            "VALUES (?, ?, ?, ?)",
            (wid, num, issue_repo, 1 if num == issue_number else 0),
        )
    _log_event(conn, "work-start", work_item_id=wid, repo_path=repo_path)
    conn.commit()
    return wid


def check_active_work(conn: sqlite3.Connection, issue_number: int,
                      issue_repo: str) -> list[dict]:
    """Return active work items that cover the given issue.

    Used by work-start, plan_manager append, and slot creation to detect
    duplicate work before it starts. Returns a list of dicts with branch,
    state, location, repo_path, and slot_id for each active work item.
    """
    rows = conn.execute(
        """
        SELECT wi.branch, wi.state, wi.location, wi.slot_id, r.path as repo_path
        FROM work_item_issues wii
        JOIN work_items wi ON wii.work_item_id = wi.id
        JOIN repos r ON wi.repo_id = r.id
        WHERE wii.issue_number = ?
          AND wii.issue_repo = ?
          AND wi.state IN ('active', 'paused')
        """,
        (issue_number, issue_repo),
    ).fetchall()
    return [dict(r) for r in rows]


@safe
def record_work_pause(conn: sqlite3.Connection, branch: str,
                      repo_path: str) -> None:
    wid = _find_work_item(conn, branch, repo_path)
    if wid is None:
        return
    conn.execute("UPDATE work_items SET state='paused' WHERE id=?", (wid,))
    _log_event(conn, "work-pause", work_item_id=wid, repo_path=repo_path)
    conn.commit()


@safe
def record_work_resume(conn: sqlite3.Connection, branch: str,
                       repo_path: str) -> None:
    wid = _find_work_item(conn, branch, repo_path)
    if wid is None:
        return
    conn.execute("UPDATE work_items SET state='active' WHERE id=?", (wid,))
    _log_event(conn, "work-resume", work_item_id=wid, repo_path=repo_path)
    conn.commit()


@safe
def record_work_end(conn: sqlite3.Connection, branch: str,
                    repo_path: str,
                    landed_sha: str | None = None) -> None:
    wid = _find_work_item(conn, branch, repo_path)
    if wid is None:
        return
    conn.execute(
        "UPDATE work_items SET state='ended', ended_at=? WHERE id=?",
        (_now(), wid),
    )
    meta = {"landed_sha": landed_sha} if landed_sha else None
    _log_event(conn, "work-end", work_item_id=wid, repo_path=repo_path,
               metadata=meta)
    conn.commit()


# --- Slots ---

@safe
def record_slot_create(conn: sqlite3.Connection, slot_number: int,
                       family_root: str, repos: list[str],
                       branch: str, issue_number: int,
                       issue_repo: str,
                       covers: str | None = None) -> int | None:
    family_root = _norm(family_root)
    cur = conn.execute(
        "INSERT INTO slots (slot_number, family_root, state, created_at) "
        "VALUES (?, ?, 'active', ?)",
        (slot_number, family_root, _now()),
    )
    sid = cur.lastrowid
    issue_nums = [int(n.strip()) for n in (covers or str(issue_number)).split(",") if n.strip()]
    for repo_path in repos:
        repo_id = ensure_repo(conn, repo_path, family_root=family_root)
        if repo_id is None:
            continue
        wi_cur = conn.execute(
            "INSERT INTO work_items (branch, repo_id, state, location, slot_id, created_at) "
            "VALUES (?, ?, 'active', 'slot', ?, ?)",
            (branch, repo_id, sid, _now()),
        )
        wid = wi_cur.lastrowid
        for num in issue_nums:
            conn.execute(
                "INSERT INTO work_item_issues (work_item_id, issue_number, issue_repo, is_primary) "
                "VALUES (?, ?, ?, ?)",
                (wid, num, issue_repo, 1 if num == issue_number else 0),
            )
    _log_event(conn, "slot-create", slot_id=sid,
               metadata={"repos": repos, "branch": branch})
    conn.commit()
    return sid


@safe
def record_slot_phase_a(conn: sqlite3.Connection, slot_number: int,
                        family_root: str) -> None:
    sid = _find_slot(conn, slot_number, family_root)
    if sid is None:
        return
    conn.execute("UPDATE slots SET state='ready' WHERE id=?", (sid,))
    _log_event(conn, "slot-phase-a", slot_id=sid)
    conn.commit()


@safe
def record_slot_merge(conn: sqlite3.Connection, slot_number: int,
                      family_root: str,
                      landed_shas: dict[str, str] | None = None) -> None:
    sid = _find_slot(conn, slot_number, family_root)
    if sid is None:
        return
    conn.execute("UPDATE slots SET state='landed', resolution='delivered' WHERE id=?", (sid,))
    conn.execute(
        "UPDATE work_items SET state='ended', ended_at=? WHERE slot_id=?",
        (_now(), sid),
    )
    _log_event(conn, "slot-merge", slot_id=sid,
               metadata={"landed_shas": landed_shas} if landed_shas else None)
    conn.commit()


@safe
def record_slot_archiving(conn: sqlite3.Connection, slot_number: int,
                          family_root: str, pid: int,
                          archived_from: str | None = None,
                          archived_to: str | None = None,
                          resolution: str | None = None) -> None:
    """Mark slot as archiving — in attic but session still running."""
    sid = _find_slot(conn, slot_number, family_root)
    if sid is None:
        return
    updates = "state='archiving', archived_at=?"
    params: list = [_now()]
    if resolution:
        updates += ", resolution=?"
        params.append(resolution)
    params.append(sid)
    conn.execute(f"UPDATE slots SET {updates} WHERE id=?", params)
    if resolution in ("superseded", "obsolete"):
        conn.execute(
            "UPDATE work_items SET state='ended', ended_at=? WHERE slot_id=? AND state != 'ended'",
            (_now(), sid),
        )
    meta: dict = {"pid": pid}
    if archived_from:
        meta["archived_from"] = archived_from
    if archived_to:
        meta["archived_to"] = archived_to
    if resolution:
        meta["resolution"] = resolution
    _log_event(conn, "slot-archiving", slot_id=sid,
               metadata=meta)
    conn.commit()


@safe
def record_slot_archived(conn: sqlite3.Connection, slot_number: int,
                         family_root: str,
                         promoted: list[str] | None = None,
                         published: list[str] | None = None,
                         publish_dest: str | None = None) -> None:
    """Mark slot as fully archived — session exited, project dir renamed."""
    sid = _find_slot(conn, slot_number, family_root)
    if sid is None:
        return
    conn.execute("UPDATE slots SET state='archived' WHERE id=?", (sid,))
    meta: dict = {}
    if promoted:
        meta["promoted"] = promoted
    if published:
        meta["published"] = published
    if publish_dest:
        meta["publish_dest"] = publish_dest
    _log_event(conn, "slot-archived", slot_id=sid,
               metadata=meta if meta else None)
    conn.commit()


@safe
def record_slot_archive(conn: sqlite3.Connection, slot_number: int,
                        family_root: str,
                        promoted: list[str] | None = None,
                        published: list[str] | None = None,
                        publish_dest: str | None = None,
                        archived_from: str | None = None,
                        archived_to: str | None = None,
                        resolution: str | None = None) -> None:
    """Legacy: mark slot as archived in one step (no PID tracking)."""
    sid = _find_slot(conn, slot_number, family_root)
    if sid is None:
        return
    if resolution:
        conn.execute(
            "UPDATE slots SET state='archived', archived_at=?, resolution=? WHERE id=?",
            (_now(), resolution, sid),
        )
    else:
        conn.execute(
            "UPDATE slots SET state='archived', archived_at=? WHERE id=?",
            (_now(), sid),
        )
    if resolution in ("superseded", "obsolete"):
        conn.execute(
            "UPDATE work_items SET state='ended', ended_at=? WHERE slot_id=? AND state != 'ended'",
            (_now(), sid),
        )
    meta: dict = {}
    if promoted:
        meta["promoted"] = promoted
    if published:
        meta["published"] = published
    if publish_dest:
        meta["publish_dest"] = publish_dest
    if archived_from:
        meta["archived_from"] = archived_from
    if archived_to:
        meta["archived_to"] = archived_to
    if resolution:
        meta["resolution"] = resolution
    _log_event(conn, "slot-archive", slot_id=sid,
               metadata=meta if meta else None)
    conn.commit()


# --- Issue Events ---

@safe
def record_issue_activate(conn: sqlite3.Connection, branch: str,
                          repo_path: str, issue_number: int,
                          issue_repo: str) -> None:
    wid = _find_work_item(conn, branch, repo_path)
    if wid is None:
        return
    _log_event(conn, "issue-activate", work_item_id=wid,
               repo_path=repo_path,
               metadata={"issue_number": issue_number,
                          "issue_repo": issue_repo})
    conn.commit()


@safe
def record_issue_complete(conn: sqlite3.Connection, branch: str,
                          repo_path: str, issue_number: int,
                          issue_repo: str) -> None:
    wid = _find_work_item(conn, branch, repo_path)
    if wid is None:
        return
    _log_event(conn, "issue-complete", work_item_id=wid,
               repo_path=repo_path,
               metadata={"issue_number": issue_number,
                          "issue_repo": issue_repo})
    conn.execute(
        "INSERT OR IGNORE INTO work_item_issues "
        "(work_item_id, issue_number, issue_repo, is_primary) "
        "VALUES (?, ?, ?, 0)",
        (wid, issue_number, issue_repo),
    )
    conn.commit()


# --- Lifecycle integration ---


@safe
def update_work_item_state(conn: sqlite3.Connection, work_item_id: int,
                           new_state: str) -> None:
    """Update work item state. Sets ended_at when state is 'ended'."""
    if new_state == "ended":
        conn.execute(
            "UPDATE work_items SET state=?, ended_at=? WHERE id=?",
            (new_state, _now(), work_item_id),
        )
    else:
        conn.execute(
            "UPDATE work_items SET state=? WHERE id=?",
            (new_state, work_item_id),
        )
    conn.commit()


@safe
def log_transition(conn: sqlite3.Connection, event_name: str,
                   work_item_id: int | None = None,
                   repo_path: str | None = None,
                   metadata: dict | None = None) -> None:
    """Log a lifecycle transition event."""
    _log_event(conn, event_name, work_item_id=work_item_id,
               repo_path=repo_path, metadata=metadata)
    conn.commit()


@safe
def record_step_failure(conn: sqlite3.Connection, mode: str,
                        branch: str, step: str,
                        attempts: int, reason: str,
                        repo_path: str | None = None,
                        issue_repo: str | None = None) -> None:
    """Record a step failure event after final retry exhaustion."""
    record_close_event(conn, "step-failed", mode, branch,
                       repo_path=repo_path,
                       step=step, attempts=attempts, reason=reason,
                       issue_repo=issue_repo)


@safe
def record_close_event(conn: sqlite3.Connection, event_type: str,
                       mode: str, branch: str,
                       repo_path: str | None = None,
                       issue_repo: str | None = None,
                       **kwargs) -> None:
    """Record any close/wrap orchestrator event."""
    wid = None
    if branch and repo_path:
        wid = find_work_item(conn, branch, repo_path)
    meta = {"mode": mode, "issue_repo": issue_repo or ""}
    meta.update(kwargs)
    _log_event(conn, event_type, work_item_id=wid,
               repo_path=repo_path, metadata=meta)
    conn.commit()


# --- Queries ---

def active_work(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT wi.id, wi.branch, wi.state, wi.location, wi.slot_id, "
        "wi.created_at, r.path AS repo_path, r.github_repo "
        "FROM work_items wi JOIN repos r ON wi.repo_id = r.id "
        "WHERE wi.state != 'ended' "
        "ORDER BY wi.created_at",
    ).fetchall()
    return [dict(r) for r in rows]


def slot_status(conn: sqlite3.Connection,
                family_root: str | None = None) -> list[dict]:
    if family_root:
        rows = conn.execute(
            "SELECT * FROM slots WHERE family_root=? ORDER BY slot_number",
            (_norm(family_root),),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM slots ORDER BY family_root, slot_number",
        ).fetchall()
    return [dict(r) for r in rows]


def event_log(conn: sqlite3.Connection,
              since: str | None = None,
              event_type: str | None = None,
              repo_path: str | None = None,
              limit: int = 100) -> list[dict]:
    clauses, params = [], []
    if since:
        clauses.append("timestamp >= ?")
        params.append(since)
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if repo_path:
        clauses.append("repo_path = ?")
        params.append(repo_path)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM events{where} ORDER BY id DESC LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def work_item_timeline(conn: sqlite3.Connection, branch: str,
                       repo_path: str) -> list[dict]:
    rows = conn.execute(
        "SELECT e.* FROM events e "
        "JOIN work_items wi ON e.work_item_id = wi.id "
        "JOIN repos r ON wi.repo_id = r.id "
        "WHERE wi.branch=? AND r.path=? "
        "ORDER BY e.id",
        (branch, _norm(repo_path)),
    ).fetchall()
    return [dict(r) for r in rows]
