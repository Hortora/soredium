"""Read-only query functions for slot management.

Listing, scanning, cross-repo dependency checking, and drift detection.
"""

import re
import sys
from pathlib import Path

from slot_core import (
    run_cmd, _resolve_slots_dir, _resolve_slot_dir_for_number,
    get_slot_repos, get_all_slot_repos, is_project_repo,
    resolve_original_repo,
    SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME,
)
from slot_metadata import parse_slot_md
from slot_workspace import validate_slot_wksp

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))
try:
    import worklog as _wl
except ImportError:
    _wl = None


def find_slot_by_branch(family_root: Path, branch: str) -> tuple[int, bool] | None:
    """Check if an active slot already uses this branch name.
    Returns (slot_number, is_landed) or None."""
    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        slots_dir = family_root / dir_name
        if not slots_dir.exists():
            continue
        for d in sorted(slots_dir.iterdir()):
            if not d.is_dir() or not d.name.isdigit() or d.name == "attic":
                continue
            info = parse_slot_md(d)
            if info.get("branch") == branch:
                landed = (d / ".landed").exists()
                return int(d.name), landed
    return None


def get_repo_stats(repo_path: Path) -> dict:
    rc, log_out, _ = run_cmd(
        ["git", "-C", str(repo_path), "log", "--oneline", "origin/main..HEAD"]
    )
    commits = len(log_out.strip().splitlines()) if rc == 0 and log_out.strip() else 0
    rc, stat_out, _ = run_cmd(
        ["git", "-C", str(repo_path), "diff", "--shortstat", "origin/main..HEAD"]
    )
    diff = stat_out.strip() if rc == 0 else ""
    return {"commits": commits, "diff": diff}


def scan_ready(family_root: Path) -> list[dict]:
    slots = []
    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        slots_dir = family_root / dir_name
        if not slots_dir.exists():
            continue
        for d in sorted(slots_dir.iterdir()):
            if not d.is_dir() or not d.name.isdigit():
                continue
            if not (d / ".phase-a-complete").exists():
                continue
            if (d / ".landed").exists():
                continue
            timestamp = ""
            for line in (d / ".phase-a-complete").read_text().splitlines():
                if line.startswith("timestamp="):
                    timestamp = line.split("=", 1)[1]
            md = parse_slot_md(d)
            repo_names = md.get("repos", [])
            repo_data = []
            for repo_name in repo_names:
                repo_path = d / repo_name
                if repo_path.is_dir() and (repo_path / ".git").exists():
                    stats = get_repo_stats(repo_path)
                    repo_data.append({"name": repo_name, **stats})
                else:
                    repo_data.append({"name": repo_name, "commits": 0, "diff": ""})
            slots.append({
                "number": int(d.name),
                "branch": md.get("branch", ""),
                "repos": repo_data,
                "issue": md.get("issue", ""),
                "issue_repo": md.get("issue_repo", ""),
                "covers": md.get("covers", ""),
                "context": md.get("context", ""),
                "phase_a_timestamp": timestamp,
            })
    return slots


def list_slots(family_root: Path, include_archived: bool = False) -> list[dict]:
    slots = []
    seen: set[int] = set()

    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        slots_dir = family_root / dir_name
        if not slots_dir.exists():
            continue

        attic_dir = slots_dir / "attic"
        archived_nums: set[int] = set()
        if attic_dir.exists():
            archived_nums = {
                int(d.name) for d in attic_dir.iterdir()
                if d.is_dir() and d.name.isdigit()
            }

        for d in sorted(slots_dir.iterdir()):
            if not d.is_dir() or not d.name.isdigit():
                continue
            if not (d / ".slot").exists():
                continue
            num = int(d.name)
            if num in archived_nums or num in seen:
                continue
            seen.add(num)
            repos = [
                sub.name for sub in sorted(d.iterdir())
                if sub.is_dir() and (sub / ".git").exists() and is_project_repo(sub.name)
            ]
            branch = ""
            slot_md = d / ".slot"
            if slot_md.exists():
                for line in slot_md.read_text().splitlines():
                    if line.startswith("# Slot") and "—" in line:
                        branch = line.split("—", 1)[1].strip()
                        break

            if (d / ".landed").exists():
                state = "landed"
            elif (d / ".phase-a-complete").exists():
                state = "ready to land"
            else:
                state = "active"

            isolation = "none"
            if slot_md.exists():
                md = parse_slot_md(d)
                isolation = md.get("isolation_type", "") or "none"

            wksp_ok = True
            if state not in ("archived", "landed"):
                wksp_failures = validate_slot_wksp(d)
                wksp_ok = len(wksp_failures) == 0

            slots.append({
                "number": num,
                "branch": branch,
                "repos": repos,
                "state": state,
                "isolation": isolation,
                "wksp_ok": wksp_ok,
            })

        if include_archived and attic_dir.exists():
            for d in sorted(attic_dir.iterdir()):
                if not d.is_dir() or not d.name.isdigit():
                    continue
                num = int(d.name)
                if num in seen:
                    continue
                seen.add(num)
                md = parse_slot_md(d)
                slots.append({
                    "number": num,
                    "branch": md.get("branch", ""),
                    "repos": md.get("repos", []),
                    "state": "archived",
                    "isolation": md.get("isolation_type", "") or "none",
                    "wksp_ok": True,
                })

    _check_drift(family_root, slots, include_archived)

    return slots


def _map_db_to_disk_state(db_state: str) -> str:
    mapping = {
        "active": "active",
        "pending": "active",
        "failed": "failed",
        "ready": "ready to land",
        "landed": "landed",
        "archived": "archived",
    }
    return mapping.get(db_state, db_state)


def _check_drift(family_root: Path, slots: list[dict],
                  include_archived: bool) -> None:
    if _wl is None:
        return
    try:
        conn = _wl.connect()
        db_rows = _wl.slot_status(conn, family_root=str(family_root))
        conn.close()
    except Exception:
        return

    db_slots: dict[int, str] = {r["slot_number"]: r["state"] for r in db_rows}
    disk_nums: dict[int, str] = {s["number"]: s["state"] for s in slots}

    has_slot_file: set[int] = set()
    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        slots_dir = family_root / dir_name
        if not slots_dir.exists():
            continue
        for d in slots_dir.iterdir():
            if not d.is_dir() or not d.name.isdigit() or d.name == "attic":
                continue
            num = int(d.name)
            if (d / ".slot").exists():
                has_slot_file.add(num)

    for num, db_state in db_slots.items():
        if db_state == "pending":
            if num in disk_nums:
                print(f"WARN=db_drift type=pending slot={num}")
            continue
        if num not in disk_nums:
            if not include_archived:
                attic_exists = any(
                    (family_root / dn / "attic" / str(num)).exists()
                    for dn in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME)
                )
                if attic_exists and db_state in ("archived", "landed"):
                    continue
            print(f"WARN=db_drift type=db-only slot={num}")
        else:
            disk_state = disk_nums[num]
            db_mapped = _map_db_to_disk_state(db_state)
            if db_mapped != disk_state:
                print(f"WARN=db_drift type=state-mismatch slot={num} db={db_state} disk={disk_state}")

    for num in disk_nums:
        if num not in db_slots:
            if num not in has_slot_file:
                print(f"WARN=db_drift type=ghost slot={num}")
            else:
                print(f"WARN=db_drift type=disk-only slot={num}")

    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        slots_dir = family_root / dir_name
        if not slots_dir.exists():
            continue
        for d in slots_dir.iterdir():
            if not d.is_dir() or not d.name.isdigit() or d.name == "attic":
                continue
            num = int(d.name)
            if num not in disk_nums and num not in db_slots and num not in has_slot_file:
                print(f"WARN=db_drift type=ghost slot={num}")


def check_cross_deps(family_root: Path, slot_num: int) -> int:
    """Check if cross-repo Maven dependencies in a slot have landed on main."""
    slot_dir = _resolve_slot_dir_for_number(family_root, slot_num)
    if not slot_dir.exists():
        print(f"ERROR=slot_not_found slot={slot_num}")
        return 1

    repos = get_slot_repos(slot_dir)
    if len(repos) < 2:
        print("CHECK=skip (single repo, no cross-deps)")
        return 0

    group_ids: dict[str, set[str]] = {}
    dep_graph: dict[str, set[str]] = {}

    for repo_name in repos:
        slot_repo = slot_dir / repo_name
        group_ids[repo_name] = set()
        dep_graph[repo_name] = set()

        for pom in slot_repo.rglob("pom.xml"):
            try:
                content = pom.read_text()
            except Exception:
                continue
            for m in re.finditer(r"<groupId>([^<]+)</groupId>", content):
                if pom.parent == slot_repo:
                    group_ids[repo_name].add(m.group(1))

    for repo_name in repos:
        slot_repo = slot_dir / repo_name
        for pom in slot_repo.rglob("pom.xml"):
            try:
                content = pom.read_text()
            except Exception:
                continue
            for m in re.finditer(r"<dependency>[^<]*<groupId>([^<]+)</groupId>", content, re.DOTALL):
                dep_gid = m.group(1)
                for other_repo, gids in group_ids.items():
                    if other_repo != repo_name and dep_gid in gids:
                        dep_graph[repo_name].add(other_repo)

    if not any(dep_graph.values()):
        print("CHECK=pass (no cross-repo Maven dependencies detected)")
        return 0

    issues = []
    for consumer, providers in dep_graph.items():
        for provider in providers:
            original = resolve_original_repo(slot_dir / provider)
            rc, branch_out, _ = run_cmd(["git", "-C", str(original), "branch", "--show-current"])
            current = branch_out.strip() if rc == 0 else "unknown"
            slot_repo = slot_dir / provider
            rc, slot_branch, _ = run_cmd(["git", "-C", str(slot_repo), "branch", "--show-current"])
            slot_br = slot_branch.strip() if rc == 0 else "unknown"
            if current == "main":
                rc, _, _ = run_cmd(["git", "-C", str(original), "log", f"--grep={slot_br}", "--oneline", "-1"])
                print(f"DEP={consumer} → {provider} STATUS=on-main")
            else:
                issues.append((consumer, provider, slot_br))
                print(f"DEP={consumer} → {provider} STATUS=not-on-main branch={slot_br}")

    if issues:
        print(f"CHECK=fail BLOCKING={len(issues)}")
        for consumer, provider, branch in issues:
            print(f"BLOCK={provider} must land on main before {consumer} can be pushed (branch={branch})")
        return 1
    else:
        print("CHECK=pass (all provider repos on main)")
        return 0
