"""slot_state.py — Central slot state management.

Single entry point for all slot state transitions. Writes to both the
.slot file (authoritative) and the worklog DB (queryable). Validates
transitions against the allowed state machine.

States:
    active    — work in progress
    paused    — all repos WIP-committed, on hold
    ready     — phase A done, ready to land
    landed    — merged to main, ready to archive
    stale     — inactive 14+ days or plan-done-not-landed (audit-detected)
    abandoned — GitHub issue closed, never landed (audit-detected)
    archived  — in attic, done

Internal-only (DB, never in .slot):
    pending, failed — slot number reservation
    purged — DB cleanup artifact
"""

import sys
from pathlib import Path

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

_scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from slot_metadata import parse_slot_md, set_slot_state

try:
    import worklog as _wl
except ImportError:
    _wl = None


VISIBLE_STATES = frozenset({
    "active", "paused", "ready", "landed",
    "stale", "abandoned", "archived",
})

INTERNAL_STATES = frozenset({"pending", "failed", "purged"})

VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "active":    frozenset({"paused", "ready", "stale"}),
    "paused":    frozenset({"active", "stale", "abandoned"}),
    "ready":     frozenset({"landed", "stale"}),
    "landed":    frozenset({"archived"}),
    "stale":     frozenset({"active", "archived", "abandoned"}),
    "abandoned": frozenset({"archived"}),
    "archived":  frozenset(),
}


class InvalidTransition(ValueError):
    def __init__(self, from_state: str, to_state: str):
        self.from_state = from_state
        self.to_state = to_state
        allowed = VALID_TRANSITIONS.get(from_state, frozenset())
        super().__init__(
            f"Cannot transition from '{from_state}' to '{to_state}'. "
            f"Allowed: {sorted(allowed) if allowed else 'none (terminal state)'}"
        )


# DB state → .slot state mapping for states that differ
_DB_TO_SLOT = {
    "archiving": "archived",
}


def current_state(slot_dir: Path) -> str:
    """Read state from .slot file (authoritative). Defaults to 'active'."""
    info = parse_slot_md(slot_dir)
    return info.get("state", "active")


def _update_db(slot_number: int, family_root: str, new_state: str,
               resolution: str | None = None,
               landed_shas: dict[str, str] | None = None,
               pid: int | None = None,
               archived_from: str | None = None,
               archived_to: str | None = None,
               repos: list[str] | None = None,
               branch: str | None = None,
               issue_number: int = 0,
               issue_repo: str = "",
               covers: str | None = None,
               promoted: list[str] | None = None,
               published: list[str] | None = None,
               publish_dest: str | None = None) -> None:
    """Update worklog DB state. Maps visible states to DB API calls."""
    if _wl is None:
        return
    conn = _wl.connect()
    try:
        if new_state == "active" and repos is not None and branch:
            _wl.confirm_slot_create(
                conn, slot_number, family_root,
                repos=repos, branch=branch,
                issue_number=issue_number,
                issue_repo=issue_repo, covers=covers,
            )
        elif new_state == "ready":
            _wl.record_slot_phase_a(conn, slot_number, family_root)
        elif new_state == "landed":
            _wl.record_slot_merge(
                conn, slot_number, family_root,
                landed_shas=landed_shas,
            )
        elif new_state == "archived":
            _wl.record_slot_archive(
                conn, slot_number, family_root,
                promoted=promoted,
                published=published,
                publish_dest=publish_dest,
                archived_from=archived_from,
                archived_to=archived_to,
                resolution=resolution,
            )
        elif new_state == "paused":
            sid = _wl._find_slot(conn, slot_number, family_root)
            if sid is not None:
                conn.execute(
                    "UPDATE slots SET state='paused' WHERE id=?", (sid,))
                conn.execute(
                    "UPDATE work_items SET state='paused' "
                    "WHERE slot_id=? AND state='active'", (sid,))
                conn.commit()
        elif new_state in ("stale", "abandoned"):
            sid = _wl._find_slot(conn, slot_number, family_root)
            if sid is not None:
                conn.execute(
                    "UPDATE slots SET state=? WHERE id=?",
                    (new_state, sid))
                conn.commit()
        else:
            sid = _wl._find_slot(conn, slot_number, family_root)
            if sid is not None:
                conn.execute(
                    "UPDATE slots SET state=? WHERE id=?",
                    (new_state, sid))
                if new_state == "active":
                    conn.execute(
                        "UPDATE work_items SET state='active' "
                        "WHERE slot_id=? AND state='paused'", (sid,))
                conn.commit()
    finally:
        conn.close()


def transition(slot_dir: Path, new_state: str,
               family_root: Path | None = None,
               slot_number: int | None = None,
               resolution: str | None = None,
               landed_shas: dict[str, str] | None = None,
               pid: int | None = None,
               archived_from: str | None = None,
               archived_to: str | None = None,
               repos: list[str] | None = None,
               branch: str | None = None,
               issue_number: int = 0,
               issue_repo: str = "",
               covers: str | None = None,
               promoted: list[str] | None = None,
               published: list[str] | None = None,
               publish_dest: str | None = None,
               force: bool = False) -> str:
    """Transition a slot to a new state. Writes to .slot and DB.

    Args:
        slot_dir: Path to the slot directory (active or attic).
        new_state: Target state (must be in VISIBLE_STATES).
        family_root: Family root path (for DB lookup). Inferred if not given.
        slot_number: Slot number (for DB lookup). Inferred from slot_dir if not given.
        force: Skip transition validation (for migration/repair only).
        **kwargs: State-specific context passed to the DB update.

    Returns:
        The previous state.

    Raises:
        InvalidTransition: If the transition is not allowed and force=False.
        ValueError: If new_state is not a visible state.
    """
    if new_state not in VISIBLE_STATES:
        raise ValueError(f"Unknown state: '{new_state}'. Must be one of {sorted(VISIBLE_STATES)}")

    old_state = current_state(slot_dir)

    if not force and old_state in VALID_TRANSITIONS:
        if new_state not in VALID_TRANSITIONS[old_state]:
            raise InvalidTransition(old_state, new_state)

    set_slot_state(slot_dir, new_state)

    if slot_number is None:
        slot_number = _infer_slot_number(slot_dir)
    if family_root is None:
        family_root = _infer_family_root(slot_dir)

    if slot_number is not None and family_root is not None:
        try:
            _update_db(
                slot_number, str(family_root), new_state,
                resolution=resolution,
                landed_shas=landed_shas,
                pid=pid,
                archived_from=archived_from,
                archived_to=archived_to,
                repos=repos, branch=branch,
                issue_number=issue_number,
                issue_repo=issue_repo, covers=covers,
                promoted=promoted, published=published,
                publish_dest=publish_dest,
            )
        except Exception as e:
            print(f"WARN=db_update_failed state={new_state} error={e}")

    return old_state


def _infer_slot_number(slot_dir: Path) -> int | None:
    """Infer slot number from directory name."""
    try:
        return int(slot_dir.name)
    except ValueError:
        return None


def _infer_family_root(slot_dir: Path) -> Path | None:
    """Infer family root from slot directory path.

    Handles both active (family/slots/N/) and attic (family/slots/attic/N/).
    """
    parent = slot_dir.parent
    if parent.name == "attic":
        parent = parent.parent
    if parent.name in ("slots", "worktrees"):
        return parent.parent
    return None


def audit_state(slot_dir: Path, family_root: Path) -> list[dict]:
    """Cross-check .slot state vs DB state vs disk markers.

    Returns a list of divergence dicts, empty if consistent.
    """
    divergences: list[dict] = []
    slot_number = _infer_slot_number(slot_dir)
    if slot_number is None:
        return divergences

    slot_state = current_state(slot_dir)
    is_attic = "attic" in str(slot_dir)
    has_landed = (slot_dir / ".landed").exists()
    has_phase_a = (slot_dir / ".phase-a-complete").exists()

    expected_from_disk = "active"
    if is_attic:
        expected_from_disk = "archived"
    elif has_landed:
        expected_from_disk = "landed"
    elif has_phase_a:
        expected_from_disk = "ready"

    if slot_state != expected_from_disk and slot_state not in ("stale", "abandoned", "paused"):
        divergences.append({
            "slot": slot_number,
            "class": "slot-disk-mismatch",
            "slot_state": slot_state,
            "disk_state": expected_from_disk,
            "detail": f".slot says '{slot_state}' but disk signals say '{expected_from_disk}'",
        })

    if _wl is not None:
        conn = _wl.connect()
        try:
            sid = _wl._find_slot(conn, slot_number, str(family_root))
            if sid is not None:
                row = conn.execute(
                    "SELECT state FROM slots WHERE id=?", (sid,)
                ).fetchone()
                if row:
                    db_state = row["state"]
                    mapped = _DB_TO_SLOT.get(db_state, db_state)
                    if mapped in INTERNAL_STATES:
                        pass
                    elif mapped != slot_state:
                        divergences.append({
                            "slot": slot_number,
                            "class": "slot-db-mismatch",
                            "slot_state": slot_state,
                            "db_state": db_state,
                            "detail": f".slot says '{slot_state}' but DB says '{db_state}'",
                        })
        finally:
            conn.close()

    return divergences
