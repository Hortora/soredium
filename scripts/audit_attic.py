#!/usr/bin/env python3
"""Audit every archived slot: verify code landed, check for lost artifacts."""
import subprocess
from pathlib import Path

FAMILY_ROOT = Path.home() / "claude" / "casehub"
ATTIC = FAMILY_ROOT / "worktrees" / "attic"
HORTORA_ATTIC = Path.home() / "claude" / "hortora" / "worktrees" / "attic"

def run(*cmd, cwd=None):
    r = subprocess.run(list(cmd), capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

def parse_slot(slot_dir):
    slot_file = slot_dir / ".slot"
    if not slot_file.exists():
        return None
    text = slot_file.read_text()
    info = {"path": str(slot_dir), "num": slot_dir.name}

    for line in text.splitlines():
        if "branch:" in line and line.strip().startswith("20"):
            info["branch"] = line.split("branch:")[1].strip()

    for line in text.splitlines():
        if "/" in line and "#" in line and not line.startswith("#") and not line.startswith("-"):
            info["issue"] = line.strip()
            break

    repos = []
    in_repos = False
    for line in text.splitlines():
        if line.strip() == "## Repos":
            in_repos = True
            continue
        if in_repos:
            if line.startswith("## "):
                break
            if line.startswith("- "):
                name = line.lstrip("- ").replace("(primary)", "").strip()
                primary = "(primary)" in line
                repos.append((name, primary))
    info["repos"] = repos

    landed_file = slot_dir / ".landed"
    if landed_file.exists():
        info["landed"] = landed_file.read_text().strip()
    else:
        info["landed"] = None

    remaining = [d.name for d in slot_dir.iterdir()
                 if d.is_dir() and not d.name.startswith(".")]
    info["remaining_dirs"] = remaining

    return info

def check_branch_exists(repo_name, branch, family_root):
    original = family_root / repo_name
    if not original.exists():
        for candidate in [family_root.parent / repo_name, family_root / repo_name]:
            if candidate.exists():
                original = candidate
                break

    results = {"repo": repo_name}

    if not original.exists():
        results["local"] = "repo_not_found"
        results["remote"] = "repo_not_found"
        return results

    rc, out, _ = run("git", "-C", str(original), "ls-remote", "--heads", "origin", branch)
    results["remote"] = "exists" if out.strip() else "not_found"

    rc, out, _ = run("git", "-C", str(original), "rev-parse", "--verify", f"refs/heads/{branch}")
    results["local"] = "exists" if rc == 0 else "not_found"

    rc, out, _ = run("git", "-C", str(original), "log", "--oneline", "-1", branch)
    if rc == 0:
        results["branch_tip"] = out.strip()

    return results

def check_workspace_branch(slot_info, family_root):
    branch = slot_info.get("branch", "")
    if not branch:
        return None

    workspace_dirs = []
    for d in ["work", "work-casehub", "work-casehub-ras"]:
        candidate = family_root / d
        if candidate.exists() and (candidate / ".git").exists():
            workspace_dirs.append(candidate)

    results = []
    for wksp in workspace_dirs:
        rc_local, _, _ = run("git", "-C", str(wksp), "rev-parse", "--verify", f"refs/heads/{branch}")
        rc_remote, out, _ = run("git", "-C", str(wksp), "ls-remote", "--heads", "origin", branch)
        if rc_local == 0 or out.strip():
            results.append({
                "workspace": wksp.name,
                "local": "exists" if rc_local == 0 else "not_found",
                "remote": "exists" if out.strip() else "not_found",
            })
    return results

def audit_slot(slot_dir, family_root):
    info = parse_slot(slot_dir)
    if not info:
        return {"num": slot_dir.name, "error": "no .slot file"}

    branch = info.get("branch", "")
    repos = info.get("repos", [])
    has_repos_on_disk = len(info["remaining_dirs"]) > 0

    repo_checks = []
    for repo_name, is_primary in repos:
        check = check_branch_exists(repo_name, branch, family_root)
        check["primary"] = is_primary
        repo_checks.append(check)

    wksp_checks = check_workspace_branch(info, family_root)

    info["repo_checks"] = repo_checks
    info["workspace_checks"] = wksp_checks or []
    info["has_repos_on_disk"] = has_repos_on_disk

    if not has_repos_on_disk and info["landed"] is None:
        info["severity"] = "CRITICAL"
        info["status"] = "stripped, no .landed, repos may be lost"
    elif not has_repos_on_disk and info["landed"]:
        info["severity"] = "WARNING"
        info["status"] = "stripped but .landed exists — verify SHAs on main"
    elif has_repos_on_disk and info["landed"]:
        info["severity"] = "OK"
        info["status"] = "repos intact, landed"
    elif has_repos_on_disk and not info["landed"]:
        info["severity"] = "WARNING"
        info["status"] = "repos intact but no .landed"
    else:
        info["severity"] = "UNKNOWN"
        info["status"] = "unexpected state"

    return info

print("=" * 80)
print("ATTIC SLOT AUDIT")
print("=" * 80)

all_results = []

for attic_root, family in [(ATTIC, FAMILY_ROOT), (HORTORA_ATTIC, Path.home() / "claude" / "hortora")]:
    if not attic_root.exists():
        continue
    family_name = family.name
    for slot_dir in sorted(attic_root.iterdir(), key=lambda d: int(d.name) if d.name.isdigit() else 0):
        if not slot_dir.is_dir() or not slot_dir.name.isdigit():
            continue
        result = audit_slot(slot_dir, family)
        result["family"] = family_name
        all_results.append(result)

        sev = result.get("severity", "?")
        num = result.get("num", "?")
        issue = result.get("issue", "?")
        status = result.get("status", "?")
        remaining = result.get("remaining_dirs", [])
        branch = result.get("branch", "?")

        print(f"\n--- Slot {num} ({family_name}) [{sev}] ---")
        print(f"  Issue: {issue}")
        print(f"  Branch: {branch}")
        print(f"  Status: {status}")
        print(f"  Dirs on disk: {remaining if remaining else '[EMPTY]'}")

        for rc in result.get("repo_checks", []):
            tag = " (primary)" if rc.get("primary") else ""
            print(f"  Repo {rc['repo']}{tag}: local={rc.get('local','?')} remote={rc.get('remote','?')}")

        for wc in result.get("workspace_checks", []):
            print(f"  Workspace {wc['workspace']}: local={wc.get('local','?')} remote={wc.get('remote','?')}")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

critical = [r for r in all_results if r.get("severity") == "CRITICAL"]
warning = [r for r in all_results if r.get("severity") == "WARNING"]
ok = [r for r in all_results if r.get("severity") == "OK"]

print(f"\nTotal slots: {len(all_results)}")
print(f"  CRITICAL: {len(critical)}")
print(f"  WARNING:  {len(warning)}")
print(f"  OK:       {len(ok)}")

if critical:
    print("\nCRITICAL — stripped, no .landed, potential data loss:")
    for r in critical:
        has_any_branch = any(
            rc.get("local") == "exists" or rc.get("remote") == "exists"
            for rc in r.get("repo_checks", [])
        )
        has_wksp = len(r.get("workspace_checks", [])) > 0
        print(f"  Slot {r['num']} ({r['family']}): {r.get('issue','?')}")
        print(f"    Any branch found: {has_any_branch}")
        print(f"    Workspace branch found: {has_wksp}")

if warning:
    print("\nWARNING — needs verification:")
    for r in warning:
        print(f"  Slot {r['num']} ({r['family']}): {r.get('issue','?')} — {r.get('status')}")
