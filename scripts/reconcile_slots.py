#!/usr/bin/env python3
"""
Reconcile slot filesystem state with worklog DB.

Three phases:
  1. audit    — scan disk + DB, classify divergences
  2. strategy — propose actions for each divergence
  3. execute  — apply approved actions (quarantine, not delete)

GitHub check (--check-github):
  Detect active slots whose GitHub issues are already closed.
  Classify as superseded (work on main) or obsolete (never started).
  Prompt for confirmation before archiving.

Usage:
    python3 scripts/reconcile_slots.py <family-root>              # audit only
    python3 scripts/reconcile_slots.py <family-root> --strategy   # audit + strategy
    python3 scripts/reconcile_slots.py <family-root> --execute    # audit + strategy + execute
    python3 scripts/reconcile_slots.py <family-root> --check-github          # detect + classify
    python3 scripts/reconcile_slots.py <family-root> --check-github --execute  # detect + archive
    python3 scripts/reconcile_slots.py --purge-test-data          # remove pytest pollution from DB
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))

_scripts = Path(__file__).resolve().parent
sys.path.insert(0, str(_scripts))

_slot_mgr = Path(__file__).resolve().parent.parent / "work-slot"
if _slot_mgr.exists():
    sys.path.insert(0, str(_slot_mgr))

try:
    import worklog as _wl
except ImportError:
    _wl = None

try:
    from slot_claude import relocate_claude_projects, remove_claude_projects
except ImportError:
    relocate_claude_projects = None
    remove_claude_projects = None

try:
    from slot_metadata import parse_slot_md
except ImportError:
    parse_slot_md = None

try:
    from slot_state import current_state as _current_slot_state, set_slot_state
except ImportError:
    _current_slot_state = None
    set_slot_state = None

SLOT_DIR_NAME = "slots"
LEGACY_SLOT_DIR_NAME = "worktrees"


def _list_dir_contents(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted(f.name for f in path.iterdir())


def _infer_disk_state(location: str, has_landed: bool, has_phase_a: bool) -> str:
    if location == "attic":
        return "archived"
    if has_landed:
        return "landed"
    if has_phase_a:
        return "ready"
    return "active"


def _states_compatible(db_state: str, disk_state: str) -> bool:
    if db_state == disk_state:
        return True
    if db_state == "pending" and disk_state == "active":
        return True
    if db_state == "failed":
        return True
    if db_state == "ready" and disk_state in ("active", "ready"):
        return True
    return False


def _read_slot_state(slot_dir: Path) -> str | None:
    """Read the state: field from a .slot file. Returns None if absent."""
    slot_file = slot_dir / ".slot"
    if not slot_file.exists():
        return None
    for line in slot_file.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("state:") or stripped.startswith("status:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _check_plan_complete(slot_dir: Path) -> bool:
    """Check if a .plan exists in the slot and all issues are done."""
    for sub in slot_dir.iterdir():
        if not sub.is_dir():
            continue
        plan = sub / ".plan"
        if not plan.exists():
            continue
        content = plan.read_text()
        in_queue = False
        has_items = False
        all_done = True
        for line in content.splitlines():
            if line.startswith("## Queue"):
                in_queue = True
                continue
            if in_queue and line.startswith("## "):
                break
            if in_queue and line.strip().startswith("- "):
                has_items = True
                if "← active" in line:
                    all_done = False
                elif line.strip().startswith("- [ ]"):
                    all_done = False
        if has_items and all_done:
            return True
    return False


def _scan_disk(family_root: Path) -> dict[int, dict]:
    results: dict[int, dict] = {}
    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        base = family_root / dir_name
        if not base.exists():
            continue
        for d in base.iterdir():
            if not d.is_dir() or not d.name.isdigit() or d.name == "attic":
                continue
            num = int(d.name)
            if num in results:
                continue
            results[num] = {
                "location": "active",
                "path": str(d),
                "has_slot_file": (d / ".slot").exists(),
                "has_landed": (d / ".landed").exists(),
                "has_phase_a": (d / ".phase-a-complete").exists(),
                "slot_state": _read_slot_state(d),
                "plan_complete": _check_plan_complete(d),
                "contents": _list_dir_contents(d),
            }
        attic = base / "attic"
        if attic.exists():
            for d in attic.iterdir():
                if not d.is_dir() or not d.name.isdigit():
                    continue
                num = int(d.name)
                if num in results and results[num]["has_slot_file"]:
                    continue
                results[num] = {
                    "location": "attic",
                    "path": str(d),
                    "has_slot_file": (d / ".slot").exists(),
                    "has_landed": (d / ".landed").exists(),
                    "has_phase_a": (d / ".phase-a-complete").exists(),
                    "slot_state": _read_slot_state(d),
                    "plan_complete": False,
                    "contents": _list_dir_contents(d),
                }
    return results


def _scan_db(family_root: str) -> dict[int, dict]:
    if not _wl:
        return {}
    conn = _wl.connect()
    normalized = _wl._norm(family_root)
    rows = conn.execute(
        "SELECT id, slot_number, state, created_at, archived_at "
        "FROM slots WHERE family_root=? OR family_root=?",
        (normalized, family_root),
    ).fetchall()
    conn.close()
    return {
        r["slot_number"]: {
            "id": r["id"],
            "state": r["state"],
            "created_at": r["created_at"],
            "archived_at": r["archived_at"],
        }
        for r in rows
    }


def audit(family_root: Path) -> list[dict]:
    """Phase 1: scan disk and DB, classify all divergences."""
    disk = _scan_disk(family_root)
    db = _scan_db(str(family_root))
    divergences = []
    all_nums = sorted(set(disk.keys()) | set(db.keys()))

    for num in all_nums:
        d = disk.get(num)
        db_entry = db.get(num)

        if d and not d["has_slot_file"] and d["location"] == "active":
            divergences.append({
                "slot": num,
                "class": "ghost",
                "disk_path": d["path"],
                "disk_contents": d["contents"],
                "db_state": db_entry["state"] if db_entry else None,
                "detail": f"directory with no .slot file, contains: {d['contents']}",
            })
            continue

        if db_entry and not d:
            if db_entry["state"] == "purged":
                continue
            divergences.append({
                "slot": num,
                "class": "db-only",
                "db_state": db_entry["state"],
                "db_created": db_entry.get("created_at", ""),
                "detail": f"DB says {db_entry['state']} but no directory on disk",
            })
            continue

        if d and not db_entry:
            divergences.append({
                "slot": num,
                "class": "disk-only",
                "disk_path": d["path"],
                "disk_location": d["location"],
                "has_landed": d.get("has_landed", False),
                "detail": f"directory at {d['location']} but no DB record",
            })
            continue

        if d and db_entry:
            disk_state = _infer_disk_state(
                d["location"], d.get("has_landed", False),
                d.get("has_phase_a", False))
            if not _states_compatible(db_entry["state"], disk_state):
                divergences.append({
                    "slot": num,
                    "class": "state-mismatch",
                    "disk_path": d["path"],
                    "disk_state": disk_state,
                    "db_state": db_entry["state"],
                    "detail": f"DB={db_entry['state']}, disk={disk_state}",
                })

            # .slot file has no state: field (needs migration)
            slot_state = d.get("slot_state")
            if d["has_slot_file"] and slot_state is None:
                divergences.append({
                    "slot": num,
                    "class": "missing-state-field",
                    "disk_path": d["path"],
                    "db_state": db_entry["state"],
                    "disk_state": disk_state,
                    "detail": f".slot has no state: field, DB={db_entry['state']}, disk={disk_state}",
                })

            # .slot state disagrees with DB state
            if slot_state is not None and db_entry:
                db_mapped = db_entry["state"]
                if db_mapped == "archiving":
                    db_mapped = "archived"
                if slot_state != db_mapped and db_mapped not in ("pending", "failed", "purged"):
                    divergences.append({
                        "slot": num,
                        "class": "slot-file-mismatch",
                        "disk_path": d["path"],
                        "slot_state": slot_state,
                        "db_state": db_entry["state"],
                        "detail": f".slot says '{slot_state}', DB says '{db_entry['state']}'",
                    })

            # Plan complete but not landed — corruption
            if d.get("plan_complete") and not d.get("has_landed") and d["location"] == "active":
                divergences.append({
                    "slot": num,
                    "class": "plan-complete-not-landed",
                    "disk_path": d["path"],
                    "db_state": db_entry["state"] if db_entry else None,
                    "detail": "all .plan issues done but no .landed marker — work-end never ran",
                })

    # Work item orphans: active work items whose slot is archived/landed
    if _wl:
        conn = _wl.connect()
        try:
            normalized = _wl._norm(str(family_root))
            orphans = conn.execute(
                "SELECT wi.id, wi.branch, wi.state, wi.slot_id, s.slot_number, s.state as slot_state "
                "FROM work_items wi "
                "JOIN slots s ON wi.slot_id = s.id "
                "WHERE wi.state IN ('active', 'paused') "
                "AND s.state IN ('archived', 'landed', 'purged') "
                "AND (s.family_root = ? OR s.family_root = ?)",
                (normalized, str(family_root)),
            ).fetchall()
            for o in orphans:
                divergences.append({
                    "slot": o["slot_number"],
                    "class": "work-item-orphan",
                    "work_item_id": o["id"],
                    "wi_state": o["state"],
                    "wi_branch": o["branch"],
                    "slot_db_state": o["slot_state"],
                    "detail": f"work item '{o['branch']}' is {o['state']} but slot is {o['slot_state']}",
                })
        finally:
            conn.close()

    return divergences


def strategy(divergences: list[dict]) -> list[dict]:
    """Phase 2: propose an action for each divergence."""
    actions = []
    for d in divergences:
        cls = d["class"]
        if cls == "ghost":
            contents = d.get("disk_contents", [])
            has_content = len(contents) > 0
            db_state = d.get("db_state")
            content_summary = "empty"
            if has_content:
                content_summary = f"contains: {', '.join(contents)}"
                if db_state:
                    content_summary += f", DB state: {db_state}"
            actions.append({
                "slot": d["slot"],
                "action": "quarantine",
                "source": d["disk_path"],
                "content": content_summary,
                "detail": f"move to quarantine/ — {content_summary}",
                "risk": "medium" if has_content else "low",
            })
        elif cls == "db-only":
            actions.append({
                "slot": d["slot"],
                "action": "remove_db_record",
                "db_state": d["db_state"],
                "detail": f"remove stale DB record (was {d['db_state']})",
                "risk": "low",
            })
        elif cls == "disk-only":
            actions.append({
                "slot": d["slot"],
                "action": "backfill_db",
                "disk_path": d["disk_path"],
                "disk_location": d["disk_location"],
                "detail": "create DB record from disk state",
                "risk": "medium" if d.get("has_landed") else "low",
            })
        elif cls == "state-mismatch":
            actions.append({
                "slot": d["slot"],
                "action": "update_db_state",
                "new_state": d["disk_state"],
                "old_state": d["db_state"],
                "detail": f"update DB from {d['db_state']} to {d['disk_state']}",
                "risk": "low",
            })
        elif cls == "missing-state-field":
            correct = d.get("disk_state", d.get("db_state", "active"))
            actions.append({
                "slot": d["slot"],
                "action": "backfill_state_field",
                "disk_path": d["disk_path"],
                "new_state": correct,
                "detail": f"write state: {correct} to .slot file",
                "risk": "low",
            })
        elif cls == "slot-file-mismatch":
            actions.append({
                "slot": d["slot"],
                "action": "update_db_to_slot",
                "disk_path": d.get("disk_path", ""),
                "new_state": d["slot_state"],
                "old_state": d["db_state"],
                "detail": f"update DB from '{d['db_state']}' to '{d['slot_state']}' (.slot is authoritative)",
                "risk": "low",
            })
        elif cls == "plan-complete-not-landed":
            actions.append({
                "slot": d["slot"],
                "action": "flag_stale",
                "disk_path": d.get("disk_path", ""),
                "detail": "mark as stale — all plan issues done but work-end never ran",
                "risk": "medium",
            })
        elif cls == "work-item-orphan":
            actions.append({
                "slot": d["slot"],
                "action": "end_orphan_work_item",
                "work_item_id": d["work_item_id"],
                "wi_branch": d.get("wi_branch", ""),
                "detail": f"end orphaned work item '{d.get('wi_branch', '')}' (slot is {d.get('slot_db_state', '')})",
                "risk": "low",
            })
    return actions


def execute(actions: list[dict], family_root: Path) -> list[dict]:
    """Phase 3: apply approved actions. Returns results."""
    results = []
    for a in actions:
        try:
            if a["action"] == "quarantine":
                quarantine_dir = family_root / "slots" / "quarantine"
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                dest = quarantine_dir / str(a["slot"])
                if dest.exists():
                    results.append({"slot": a["slot"], "action": a["action"],
                                    "status": "skipped", "detail": "quarantine dest exists"})
                    continue
                shutil.move(a["source"], str(dest))
                if relocate_claude_projects:
                    relocate_claude_projects(Path(a["source"]), dest)
                results.append({"slot": a["slot"], "action": a["action"], "status": "done"})

            elif a["action"] == "remove_db_record":
                if _wl:
                    conn = _wl.connect()
                    normalized = _wl._norm(str(family_root))
                    try:
                        conn.execute(
                            "DELETE FROM slots WHERE slot_number=? AND family_root=?",
                            (a["slot"], normalized),
                        )
                        conn.commit()
                        results.append({"slot": a["slot"], "action": a["action"], "status": "done"})
                    except Exception:
                        conn.rollback()
                        conn.execute(
                            "UPDATE slots SET state='purged' WHERE slot_number=? AND family_root=?",
                            (a["slot"], normalized),
                        )
                        conn.commit()
                        results.append({"slot": a["slot"], "action": a["action"],
                                        "status": "done", "note": "FK constraint — marked purged"})
                    conn.close()

            elif a["action"] == "backfill_db":
                if _wl:
                    conn = _wl.connect()
                    state = "archived" if a["disk_location"] == "attic" else "active"
                    normalized = _wl._norm(str(family_root))
                    conn.execute(
                        "INSERT INTO slots (slot_number, family_root, state, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (a["slot"], normalized, state, _wl._now()),
                    )
                    conn.commit()
                    conn.close()
                results.append({"slot": a["slot"], "action": a["action"], "status": "done"})

            elif a["action"] == "update_db_state":
                if _wl:
                    conn = _wl.connect()
                    normalized = _wl._norm(str(family_root))
                    if a["new_state"] == "archived":
                        conn.execute(
                            "UPDATE slots SET state='archived', archived_at=? "
                            "WHERE slot_number=? AND family_root=?",
                            (_wl._now(), a["slot"], normalized),
                        )
                    else:
                        conn.execute(
                            "UPDATE slots SET state=? WHERE slot_number=? AND family_root=?",
                            (a["new_state"], a["slot"], normalized),
                        )
                    conn.commit()
                    conn.close()
                results.append({"slot": a["slot"], "action": a["action"], "status": "done"})

            elif a["action"] == "backfill_state_field":
                slot_path = Path(a["disk_path"])
                slot_file = slot_path / ".slot"
                if slot_file.exists():
                    content = slot_file.read_text()
                    lines = content.splitlines()
                    inserted = False
                    for i, line in enumerate(lines):
                        if line.startswith("## State") or line.startswith("## Status"):
                            lines.insert(i + 1, f"state: {a['new_state']}")
                            inserted = True
                            break
                    if not inserted:
                        for i, line in enumerate(lines):
                            if line.startswith("## Created"):
                                lines.insert(i, f"\n## State\nstate: {a['new_state']}")
                                inserted = True
                                break
                    if not inserted:
                        lines.append(f"\n## State\nstate: {a['new_state']}")
                    slot_file.write_text("\n".join(lines) + "\n")
                results.append({"slot": a["slot"], "action": a["action"], "status": "done"})

            elif a["action"] == "update_db_to_slot":
                if _wl:
                    conn = _wl.connect()
                    normalized = _wl._norm(str(family_root))
                    new_state = a["new_state"]
                    if new_state == "archived":
                        conn.execute(
                            "UPDATE slots SET state='archived', archived_at=? "
                            "WHERE slot_number=? AND family_root=?",
                            (_wl._now(), a["slot"], normalized),
                        )
                    else:
                        conn.execute(
                            "UPDATE slots SET state=? WHERE slot_number=? AND family_root=?",
                            (new_state, a["slot"], normalized),
                        )
                    conn.commit()
                    conn.close()
                results.append({"slot": a["slot"], "action": a["action"], "status": "done"})

            elif a["action"] == "flag_stale":
                slot_path = Path(a["disk_path"])
                slot_file = slot_path / ".slot"
                if slot_file.exists():
                    if set_slot_state:
                        set_slot_state(slot_path, "stale")
                if _wl:
                    conn = _wl.connect()
                    normalized = _wl._norm(str(family_root))
                    conn.execute(
                        "UPDATE slots SET state='stale' WHERE slot_number=? AND family_root=?",
                        (a["slot"], normalized),
                    )
                    conn.commit()
                    conn.close()
                results.append({"slot": a["slot"], "action": a["action"], "status": "done"})

            elif a["action"] == "end_orphan_work_item":
                if _wl:
                    conn = _wl.connect()
                    conn.execute(
                        "UPDATE work_items SET state='ended', ended_at=? WHERE id=?",
                        (_wl._now(), a["work_item_id"]),
                    )
                    conn.commit()
                    conn.close()
                results.append({"slot": a["slot"], "action": a["action"], "status": "done"})

        except Exception as e:
            results.append({"slot": a["slot"], "action": a["action"],
                            "status": "error", "detail": str(e)})
    return results


def _parse_slot_file(slot_path: Path) -> dict | None:
    """Extract issue repo, number, branch, and primary repo dir from .slot file."""
    slot_file = slot_path / ".slot"
    if not slot_file.exists():
        return None
    text = slot_file.read_text()
    issue_match = re.search(r"^(\S+)#(\d+)", text, re.MULTILINE)
    if not issue_match:
        return None
    branch_match = re.search(r"branch:\s*(\S+)", text)
    repos_section = re.search(r"## Repos\n(.*?)(?:\n##|\Z)", text, re.DOTALL)
    primary_repo = None
    if repos_section:
        for line in repos_section.group(1).strip().splitlines():
            line = line.strip().lstrip("- ")
            if "(primary)" in line:
                primary_repo = line.replace("(primary)", "").strip()
                break
            if primary_repo is None:
                primary_repo = line.strip()
    return {
        "issue_repo": issue_match.group(1),
        "issue_number": int(issue_match.group(2)),
        "branch": branch_match.group(1) if branch_match else None,
        "primary_repo": primary_repo,
    }


def _gh_issue_state(issue_repo: str, issue_number: int) -> str | None:
    """Query GitHub for issue state. Returns 'OPEN', 'CLOSED', or None on error."""
    try:
        result = subprocess.run(
            ["gh", "issue", "view", str(issue_number), "--repo", issue_repo,
             "--json", "state", "--jq", ".state"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _classify_resolution(slot_path: Path, slot_info: dict) -> tuple[str, str]:
    """Determine if a closed-issue slot is superseded or obsolete.

    Returns (resolution, evidence) tuple.
    """
    repo_dir = slot_path / slot_info["primary_repo"] if slot_info["primary_repo"] else None
    branch = slot_info["branch"]
    issue_number = slot_info["issue_number"]

    if repo_dir is None or not repo_dir.exists():
        return "obsolete", "no primary repo directory found"

    try:
        subprocess.run(
            ["git", "-C", str(repo_dir), "fetch", "origin"],
            capture_output=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    branch_ahead = 0
    if branch:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "log", "--oneline",
             f"origin/main..{branch}", "--"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            branch_ahead = len(result.stdout.strip().splitlines()) if result.stdout.strip() else 0

    result = subprocess.run(
        ["git", "-C", str(repo_dir), "log", "--oneline",
         "origin/main", f"--grep=#{issue_number}", "--"],
        capture_output=True, text=True, timeout=10,
    )
    on_main = len(result.stdout.strip().splitlines()) if result.returncode == 0 and result.stdout.strip() else 0

    if on_main > 0 and branch_ahead == 0:
        return "superseded", f"{on_main} commit(s) on main, 0 on branch"
    if on_main > 0 and branch_ahead > 0:
        return "superseded", f"{on_main} commit(s) on main, {branch_ahead} stale on branch"
    if on_main == 0 and branch_ahead == 0:
        return "obsolete", "0 commits on main, 0 on branch — never started"
    # Work on branch but not on main — needs investigation
    return "needs-review", f"0 on main, {branch_ahead} on branch — unmerged work"


def check_github(family_root: Path) -> list[dict]:
    """Detect active slots whose GitHub issues are already closed."""
    disk = _scan_disk(family_root)
    db = _scan_db(str(family_root))
    findings = []

    for num in sorted(disk.keys()):
        d = disk[num]
        if d["location"] != "active" or not d["has_slot_file"]:
            continue
        db_entry = db.get(num)
        if db_entry and db_entry["state"] not in ("active", "pending", "ready"):
            continue

        slot_path = Path(d["path"])
        slot_info = _parse_slot_file(slot_path)
        if slot_info is None:
            continue

        state = _gh_issue_state(slot_info["issue_repo"], slot_info["issue_number"])
        if state != "CLOSED":
            continue

        resolution, evidence = _classify_resolution(slot_path, slot_info)
        findings.append({
            "slot": num,
            "issue_repo": slot_info["issue_repo"],
            "issue_number": slot_info["issue_number"],
            "branch": slot_info["branch"],
            "resolution": resolution,
            "evidence": evidence,
            "disk_path": d["path"],
        })

    return findings


def execute_github_actions(findings: list[dict], family_root: Path) -> list[dict]:
    """Archive slots with confirmed resolutions. Move to attic, update DB."""
    results = []
    for f in findings:
        if f["resolution"] == "needs-review":
            results.append({"slot": f["slot"], "action": "skip",
                            "status": "needs-review", "detail": f["evidence"]})
            continue
        try:
            if _wl:
                conn = _wl.connect()
                _wl.record_slot_archive(conn, f["slot"], str(family_root),
                                        resolution=f["resolution"])
                conn.close()

            attic = family_root / "slots" / "attic"
            attic.mkdir(parents=True, exist_ok=True)
            dest = attic / str(f["slot"])
            if dest.exists():
                results.append({"slot": f["slot"], "action": "archive",
                                "status": "skipped", "detail": "attic dest exists"})
                continue
            shutil.move(f["disk_path"], str(dest))

            if remove_claude_projects:
                remove_claude_projects(Path(f["disk_path"]))

            results.append({"slot": f["slot"], "action": "archive",
                            "status": "done", "resolution": f["resolution"]})
        except Exception as e:
            results.append({"slot": f["slot"], "action": "archive",
                            "status": "error", "detail": str(e)})
    return results


def purge_test_data() -> int:
    """Remove all test-pollution entries from the worklog DB."""
    if not _wl:
        print("ERROR: worklog module not available")
        return 1
    conn = _wl.connect()
    test_patterns = ["%pytest%", "%/tmp/%", "%/private/tmp/%", "%/private/var/folders/%"]
    total_slots = 0
    total_wi = 0
    total_repos = 0
    for pattern in test_patterns:
        rows = conn.execute(
            "SELECT id FROM slots WHERE family_root LIKE ?", (pattern,)
        ).fetchall()
        slot_ids = [r["id"] for r in rows]
        if slot_ids:
            placeholders = ",".join("?" * len(slot_ids))
            wi_rows = conn.execute(
                f"SELECT id FROM work_items WHERE slot_id IN ({placeholders})",
                slot_ids,
            ).fetchall()
            wi_ids = [r["id"] for r in wi_rows]
            if wi_ids:
                wi_ph = ",".join("?" * len(wi_ids))
                conn.execute(f"DELETE FROM work_item_issues WHERE work_item_id IN ({wi_ph})", wi_ids)
                conn.execute(f"DELETE FROM events WHERE work_item_id IN ({wi_ph})", wi_ids)
                conn.execute(f"DELETE FROM work_items WHERE id IN ({wi_ph})", wi_ids)
                total_wi += len(wi_ids)
            conn.execute(f"DELETE FROM events WHERE slot_id IN ({placeholders})", slot_ids)
            conn.execute(f"DELETE FROM slots WHERE id IN ({placeholders})", slot_ids)
            total_slots += len(slot_ids)
        repo_rows = conn.execute(
            "SELECT id FROM repos WHERE path LIKE ?", (pattern,)
        ).fetchall()
        repo_ids = [r["id"] for r in repo_rows]
        if repo_ids:
            rp = ",".join("?" * len(repo_ids))
            wi_from_repos = conn.execute(
                f"SELECT id FROM work_items WHERE repo_id IN ({rp})", repo_ids
            ).fetchall()
            rw_ids = [r["id"] for r in wi_from_repos]
            if rw_ids:
                rw_ph = ",".join("?" * len(rw_ids))
                conn.execute(f"DELETE FROM work_item_issues WHERE work_item_id IN ({rw_ph})", rw_ids)
                conn.execute(f"DELETE FROM events WHERE work_item_id IN ({rw_ph})", rw_ids)
                conn.execute(f"DELETE FROM work_items WHERE id IN ({rw_ph})", rw_ids)
                total_wi += len(rw_ids)
            conn.execute(f"DELETE FROM repos WHERE id IN ({rp})", repo_ids)
            total_repos += len(repo_ids)
    conn.commit()
    conn.close()
    print(f"PURGED: {total_slots} slots, {total_wi} work items, {total_repos} repos")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    if sys.argv[1] == "--purge-test-data":
        return purge_test_data()

    family_root = Path(sys.argv[1])
    if not family_root.is_dir():
        print(f"ERROR: {family_root} is not a directory")
        return 1

    if "--check-github" in sys.argv:
        return _main_check_github(family_root)

    phase = "audit"
    if "--execute" in sys.argv:
        phase = "execute"
    elif "--strategy" in sys.argv:
        phase = "strategy"

    divergences = audit(family_root)
    if not divergences:
        print("Nothing to reconcile — all clean.")
        return 0

    print(f"AUDIT: {len(divergences)} divergence(s) found\n")
    for d in divergences:
        print(f"  SLOT {d['slot']:>3}  class={d['class']}  {d['detail']}")
    print()

    if phase == "audit":
        print("Run with --strategy to see proposed actions.")
        return 0

    actions = strategy(divergences)
    print(f"STRATEGY: {len(actions)} action(s) proposed\n")
    for a in actions:
        print(f"  SLOT {a['slot']:>3}  {a['action']}  risk={a['risk']}  {a['detail']}")
    print()

    if phase == "strategy":
        print("Run with --execute to apply.")
        return 0

    results = execute(actions, family_root)
    print(f"EXECUTE: {len(results)} action(s) applied\n")
    for r in results:
        status_detail = f"  ({r['detail']})" if r.get("detail") else ""
        print(f"  SLOT {r['slot']:>3}  {r['action']}  {r['status']}{status_detail}")
    return 0


def _main_check_github(family_root: Path) -> int:
    """Check GitHub issue state for active slots and prompt for archival."""
    print("Checking GitHub issue state for active slots...\n")
    findings = check_github(family_root)

    if not findings:
        print("All active slots have open issues — nothing to reconcile.")
        return 0

    print(f"Found {len(findings)} slot(s) with closed GitHub issues:\n")
    for f in findings:
        marker = "NEEDS REVIEW" if f["resolution"] == "needs-review" else f["resolution"]
        print(f"  Slot {f['slot']:>3} | {f['issue_repo']}#{f['issue_number']} CLOSED "
              f"| {f['evidence']} → {marker}")
    print()

    actionable = [f for f in findings if f["resolution"] != "needs-review"]
    review_needed = [f for f in findings if f["resolution"] == "needs-review"]

    if review_needed:
        print("Slots needing manual review (not auto-archivable):")
        for f in review_needed:
            print(f"  Slot {f['slot']:>3} | {f['evidence']}")
        print()

    if not actionable:
        print("No slots can be auto-archived.")
        return 0

    if "--execute" not in sys.argv:
        print(f"{len(actionable)} slot(s) can be archived. Run with --execute to apply.")
        return 0

    print(f"Archive {len(actionable)} slot(s) with proposed resolutions? [Y/n/edit] ", end="")
    sys.stdout.flush()
    answer = input().strip().lower()

    if answer == "edit":
        for f in actionable:
            print(f"\n  Slot {f['slot']} — proposed: {f['resolution']} ({f['evidence']})")
            print(f"  Override? [superseded/obsolete/skip] (default: {f['resolution']}): ", end="")
            sys.stdout.flush()
            override = input().strip().lower()
            if override == "skip":
                f["resolution"] = "needs-review"
            elif override in ("superseded", "obsolete"):
                f["resolution"] = override
        actionable = [f for f in actionable if f["resolution"] != "needs-review"]
        if not actionable:
            print("\nAll slots skipped.")
            return 0
        print()

    if answer == "n":
        print("Aborted.")
        return 0

    results = execute_github_actions(actionable, family_root)
    print(f"\nARCHIVED: {len(results)} action(s)\n")
    for r in results:
        detail = f"  ({r.get('detail', r.get('resolution', ''))})"
        print(f"  Slot {r['slot']:>3}  {r['status']}{detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
