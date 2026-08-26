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
    from slot_manager import relocate_claude_projects, remove_claude_projects
except ImportError:
    relocate_claude_projects = None
    remove_claude_projects = None

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


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

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
