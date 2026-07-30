#!/usr/bin/env python3
"""Verify WARNING slots: check if branch code is on main for each repo."""
import re
import subprocess
from pathlib import Path

FAMILY = Path.home() / "claude" / "casehub"
ATTIC = FAMILY / "worktrees" / "attic"

SLOTS = [1, 2, 6, 7, 9, 12, 14, 17, 25, 26, 27, 28, 29, 30, 34, 37, 38, 41, 43, 44, 47]

def run(*cmd):
    r = subprocess.run(list(cmd), capture_output=True, text=True)
    return r.returncode, r.stdout.strip()

def parse_slot(slot_dir):
    text = (slot_dir / ".slot").read_text()
    info = {}
    for line in text.splitlines():
        if "branch:" in line and line.strip().startswith("20"):
            info["branch"] = line.split("branch:")[1].strip()
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
    for line in text.splitlines():
        if "/" in line and "#" in line and not line.startswith("#") and not line.startswith("-"):
            info["issue"] = line.strip()
            break
    return info

for slot_num in SLOTS:
    slot_dir = ATTIC / str(slot_num)
    if not (slot_dir / ".slot").exists():
        continue
    info = parse_slot(slot_dir)
    branch = info.get("branch", "")
    issue = info.get("issue", "?")
    if not branch:
        print(f"Slot {slot_num}: {issue} — NO BRANCH NAME")
        continue

    all_on_main = True
    details = []
    for repo_name, is_primary in info.get("repos", []):
        repo_path = FAMILY / repo_name
        if not repo_path.exists():
            details.append(f"  {repo_name}: REPO NOT FOUND")
            all_on_main = False
            continue

        run("git", "-C", str(repo_path), "fetch", "origin", "main")

        # Check if branch exists locally
        rc, _ = run("git", "-C", str(repo_path), "rev-parse", "--verify", f"refs/heads/{branch}")
        if rc != 0:
            details.append(f"  {repo_name}: branch not found locally")
            continue

        # Get branch tip, skip closure stamps
        rc, log_out = run("git", "-C", str(repo_path), "log", "--oneline", "-5", branch)
        tip_sha = None
        for log_line in log_out.splitlines():
            sha = log_line.split()[0]
            if "branch closed" not in log_line and "WIP: pre-migration" not in log_line:
                tip_sha = sha
                break
            elif "landed as" in log_line:
                m = re.search(r"landed as (\w+)", log_line)
                if m:
                    tip_sha = m.group(1)
                    break

        if not tip_sha:
            tip_sha = log_out.splitlines()[0].split()[0] if log_out else None

        if tip_sha:
            rc, _ = run("git", "-C", str(repo_path), "merge-base", "--is-ancestor", tip_sha, "origin/main")
            if rc == 0:
                tag = " (primary)" if is_primary else ""
                details.append(f"  {repo_name}{tag}: ON MAIN")
            else:
                tag = " (primary)" if is_primary else ""
                details.append(f"  {repo_name}{tag}: *** NOT ON MAIN *** tip={tip_sha}")
                all_on_main = False
        else:
            details.append(f"  {repo_name}: could not determine tip")
            all_on_main = False

    status = "OK" if all_on_main else "*** NEEDS ATTENTION ***"
    print(f"\nSlot {slot_num}: {issue} [{status}]")
    for d in details:
        print(d)
