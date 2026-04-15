#!/usr/bin/env python3
"""garden_db.py — SQLite-backed storage for garden aggregate state.

Replaces CHECKED.md, DISCARDED.md, and the GARDEN.md By Technology index.
All mutable state lives in garden.db, committed to git alongside entry files.

Tables:
  checked_pairs    — deduplication pair results (replaces CHECKED.md)
  discarded_entries — retired entry log (replaces DISCARDED.md)
  entries_index    — metadata index for fast domain queries (derived, rebuildable)
  schema_version   — migration tracking
"""

import json
import sqlite3
from datetime import date
from pathlib import Path

SCHEMA_VERSION = 1
VALID_RESULTS = {'distinct', 'related', 'duplicate-discarded'}

_CREATE_CHECKED_PAIRS = """
CREATE TABLE IF NOT EXISTS checked_pairs (
    pair       TEXT PRIMARY KEY,
    result     TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    notes      TEXT DEFAULT ''
)"""

_CREATE_DISCARDED = """
CREATE TABLE IF NOT EXISTS discarded_entries (
    ge_id          TEXT PRIMARY KEY,
    conflicts_with TEXT NOT NULL,
    discarded_at   TEXT NOT NULL,
    reason         TEXT DEFAULT ''
)"""

_CREATE_ENTRIES_INDEX = """
CREATE TABLE IF NOT EXISTS entries_index (
    ge_id               TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    domain              TEXT NOT NULL,
    type                TEXT NOT NULL,
    score               INTEGER NOT NULL,
    submitted           TEXT NOT NULL,
    staleness_threshold INTEGER NOT NULL DEFAULT 730,
    tags                TEXT DEFAULT '[]',
    verified_on         TEXT DEFAULT '',
    last_reviewed       TEXT DEFAULT '',
    file_path           TEXT NOT NULL
)"""

_CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER NOT NULL,
    applied_at TEXT NOT NULL
)"""

_INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_entries_domain    ON entries_index(domain)",
    "CREATE INDEX IF NOT EXISTS idx_entries_score     ON entries_index(score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_entries_submitted ON entries_index(submitted)",
]


def _canonical_pair(pair: str) -> str:
    """Return canonical 'lower × higher' form regardless of input order."""
    # Handle both × (unicode) and x as separator
    for sep in ('×', ' x '):
        if sep in pair:
            parts = [p.strip() for p in pair.split(sep, 1)]
            if len(parts) == 2:
                return f"{min(parts)} × {max(parts)}"
    return pair


def get_connection(garden: Path) -> sqlite3.Connection:
    """Return an open sqlite3 connection to garden.db."""
    garden = Path(garden)
    if not garden.exists():
        raise FileNotFoundError(f"garden directory not found: {garden}")
    conn = sqlite3.connect(str(garden / 'garden.db'))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(garden: Path) -> None:
    """Create garden.db with all tables if they don't exist. Idempotent."""
    conn = get_connection(garden)
    try:
        with conn:
            conn.execute("PRAGMA journal_mode=WAL")
            for ddl in (_CREATE_CHECKED_PAIRS, _CREATE_DISCARDED,
                        _CREATE_ENTRIES_INDEX, _CREATE_SCHEMA_VERSION):
                conn.execute(ddl)
            for idx in _INDICES:
                conn.execute(idx)
            if not conn.execute("SELECT 1 FROM schema_version").fetchone():
                conn.execute(
                    "INSERT INTO schema_version VALUES (?, ?)",
                    (SCHEMA_VERSION, date.today().isoformat())
                )
    finally:
        conn.close()


def get_schema_version(garden: Path) -> int | None:
    """Return current schema version, or None if garden.db does not exist."""
    db_path = Path(garden) / 'garden.db'
    if not db_path.exists():
        return None
    conn = get_connection(garden)
    try:
        row = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return row['version'] if row else None
    finally:
        conn.close()


# ── checked_pairs ──────────────────────────────────────────────────────────────

def is_pair_checked(garden: Path, pair: str) -> bool:
    """Return True if pair has been classified."""
    canon = _canonical_pair(pair)
    conn = get_connection(garden)
    try:
        row = conn.execute(
            "SELECT 1 FROM checked_pairs WHERE pair = ?", (canon,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_pair_result(garden: Path, pair: str) -> str | None:
    """Return result for pair, or None if not yet classified."""
    canon = _canonical_pair(pair)
    conn = get_connection(garden)
    try:
        row = conn.execute(
            "SELECT result FROM checked_pairs WHERE pair = ?", (canon,)
        ).fetchone()
        return row['result'] if row else None
    finally:
        conn.close()


def record_pair(garden: Path, pair: str, result: str, notes: str = '') -> None:
    """Record a pair comparison result. Idempotent — silently skips if already recorded."""
    if result not in VALID_RESULTS:
        raise ValueError(f"result must be one of {sorted(VALID_RESULTS)}, got {result!r}")
    canon = _canonical_pair(pair)
    conn = get_connection(garden)
    try:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO checked_pairs "
                "(pair, result, checked_at, notes) VALUES (?, ?, ?, ?)",
                (canon, result, date.today().isoformat(), notes)
            )
    finally:
        conn.close()


def load_checked_pairs(garden: Path) -> set:
    """Return set of all canonical pair strings already classified."""
    conn = get_connection(garden)
    try:
        rows = conn.execute("SELECT pair FROM checked_pairs").fetchall()
        return {row['pair'] for row in rows}
    finally:
        conn.close()


# ── discarded_entries ─────────────────────────────────────────────────────────

def record_discarded(garden: Path, ge_id: str, conflicts_with: str,
                     reason: str = '') -> None:
    """Record a discarded entry. Idempotent."""
    conn = get_connection(garden)
    try:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO discarded_entries "
                "(ge_id, conflicts_with, discarded_at, reason) VALUES (?, ?, ?, ?)",
                (ge_id, conflicts_with, date.today().isoformat(), reason)
            )
    finally:
        conn.close()


def is_discarded(garden: Path, ge_id: str) -> bool:
    """Return True if ge_id has been discarded."""
    conn = get_connection(garden)
    try:
        row = conn.execute(
            "SELECT 1 FROM discarded_entries WHERE ge_id = ?", (ge_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# ── entries_index ─────────────────────────────────────────────────────────────

def upsert_entry(garden: Path, entry: dict) -> None:
    """Insert or replace an entry in entries_index."""
    if 'ge_id' not in entry or not entry['ge_id']:
        raise ValueError("entry must have a non-empty 'ge_id' field")
    tags = entry.get('tags', [])
    if not isinstance(tags, list):
        raise ValueError(f"'tags' must be a list, got {type(tags).__name__}")
    conn = get_connection(garden)
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO entries_index "
                "(ge_id, title, domain, type, score, submitted, staleness_threshold, "
                "tags, verified_on, last_reviewed, file_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry['ge_id'],
                    entry.get('title', ''),
                    entry.get('domain', ''),
                    entry.get('type', ''),
                    int(entry.get('score', 0)),
                    entry.get('submitted', ''),
                    int(entry.get('staleness_threshold', 730)),
                    json.dumps(tags),
                    entry.get('verified_on', ''),
                    entry.get('last_reviewed', ''),
                    entry.get('file_path', ''),
                )
            )
    finally:
        conn.close()


def get_entries_by_domain(garden: Path, domain: str) -> list:
    """Return all entries_index rows for a domain, ordered by score DESC."""
    conn = get_connection(garden)
    try:
        rows = conn.execute(
            "SELECT * FROM entries_index WHERE domain = ? ORDER BY score DESC", (domain,)
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d['tags'] = json.loads(d['tags'])
            result.append(d)
        return result
    finally:
        conn.close()
