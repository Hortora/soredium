#!/usr/bin/env python3
"""
Branch reconnaissance for work-end — replaces the Step 1 subagent dispatch.

Gathers branch state and validates the journal mechanically. Every operation
is deterministic (git commands, file reads, gh CLI) — no LLM judgment needed.

Usage:
    python3 branch_recon.py <workspace> <project> \
      branch=<name> base_branch=<base> issue_repo=<owner/repo> \
      covers=<csv> project_sha=<sha> design_repo=<path> \
      meta_section_hashes=<pipe-separated> single_repo=<yes|no>

Output: JSON object matching the subagent contract (stdout).
Errors: printed to stderr, exit code 1.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import parse_args


def git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True,
    )


def gh_issue(issue_repo: str, number: str) -> dict:
    result = subprocess.run(
        ["gh", "issue", "view", number, "--repo", issue_repo,
         "--json", "title,state"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {"number": int(number), "title": f"(fetch failed: {result.stderr.strip()})", "state": "UNKNOWN"}
    try:
        data = json.loads(result.stdout)
        return {"number": int(number), "title": data.get("title", ""), "state": data.get("state", "UNKNOWN")}
    except json.JSONDecodeError:
        return {"number": int(number), "title": "(parse error)", "state": "UNKNOWN"}


def gather_issues(issue_repo: str, covers: str) -> list[dict]:
    if not covers or not issue_repo:
        return []
    numbers = [n.strip().lstrip("#") for n in covers.split(",") if n.strip()]
    return [gh_issue(issue_repo, n) for n in numbers]


def gather_commits(project: str, base_branch: str, branch: str) -> tuple[list[dict], int]:
    result = git(project, "log", "--oneline", f"{base_branch}..{branch}")
    if result.returncode != 0:
        return [], 0
    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split(" ", 1)
        sha = parts[0]
        message = parts[1] if len(parts) > 1 else ""
        commits.append({"sha": sha, "message": message})
    return commits, len(commits)


def gather_diff_stats(project: str, project_sha: str) -> str:
    result = git(project, "diff", "--shortstat", f"{project_sha}..HEAD")
    if result.returncode != 0:
        return "(diff failed)"
    return result.stdout.strip() or "no changes"


def parse_journal(workspace: str) -> dict:
    journal_path = Path(workspace) / "JOURNAL.md"
    if not journal_path.exists():
        journal_path = Path(workspace) / "design" / "JOURNAL.md"
    result: dict = {
        "journal_entry_count": 0,
        "anchored_entries": 0,
        "unanchored_entries": 0,
        "entries_without_anchors": [],
        "empty_journal": True,
        "warnings": [],
    }
    if not journal_path.exists():
        return result

    text = journal_path.read_text()
    entries = []
    for line in text.splitlines():
        if line.startswith("### "):
            entries.append(line)
        elif line.startswith("###") and not line.startswith("####"):
            result["warnings"].append(f"possible malformed entry (no space after ###): {line}")

    result["journal_entry_count"] = len(entries)
    result["empty_journal"] = len(entries) == 0

    anchored = 0
    unanchored_list = []
    for entry in entries:
        if "§" in entry:
            anchored += 1
        else:
            unanchored_list.append(entry)

    result["anchored_entries"] = anchored
    result["unanchored_entries"] = len(unanchored_list)
    result["entries_without_anchors"] = unanchored_list
    return result


def check_arc42(design_repo: str) -> bool:
    if not design_repo:
        return False
    return (Path(design_repo) / "ARC42STORIES.MD").exists()


def compute_section_drift(design_repo: str, meta_section_hashes: str) -> tuple[list[dict], list[str]]:
    """Returns (drift_list, warnings)."""
    if not design_repo or not meta_section_hashes:
        return [], []

    arc42_path = Path(design_repo) / "ARC42STORIES.MD"
    if not arc42_path.exists():
        return [], []

    # Delegate to section_hashes.py — single source of truth for the algorithm
    hashes_script = Path(__file__).parent.parent / "project" / "section_hashes.py"
    if not hashes_script.exists():
        return [], [f"section_hashes.py not found at {hashes_script} — drift check skipped"]

    result = subprocess.run(
        [sys.executable, str(hashes_script), str(arc42_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return [], [f"section_hashes.py failed: {result.stderr.strip()}"]

    # Parse current hashes from script output (pipe-separated hash:heading)
    current: dict[str, str] = {}
    for pair in result.stdout.strip().split("|"):
        if ":" in pair:
            h, _, heading = pair.partition(":")
            current[heading.strip()] = h.strip()

    # Parse stored hashes from meta (same format)
    stored: dict[str, str] = {}
    for pair in meta_section_hashes.split("|"):
        if ":" in pair:
            h, _, heading = pair.partition(":")
            stored[heading.strip()] = h.strip()

    drift = []
    for heading, stored_hash in stored.items():
        current_hash = current.get(heading, "")
        if current_hash and current_hash != stored_hash:
            drift.append({
                "section": heading,
                "stored_hash": stored_hash,
                "current_hash": current_hash,
            })
    return drift, []


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: branch_recon.py <workspace> <project> key=value ...", file=sys.stderr)
        return 1

    workspace = sys.argv[1]
    project = sys.argv[2]
    opts = parse_args(sys.argv[3:])

    branch = opts.get("branch", "")
    base_branch = opts.get("base_branch", "main")
    issue_repo = opts.get("issue_repo", "")
    covers = opts.get("covers", "")
    project_sha = opts.get("project_sha", "")
    design_repo = opts.get("design_repo", "")
    meta_section_hashes = opts.get("meta_section_hashes", "")

    if not branch:
        print("ERROR: branch= is required", file=sys.stderr)
        return 1

    warnings: list[str] = []

    issues = gather_issues(issue_repo, covers)
    commits, commit_count = gather_commits(project, base_branch, branch)
    diff_stats = gather_diff_stats(project, project_sha)
    journal = parse_journal(workspace)
    warnings.extend(journal.pop("warnings", []))
    arc42_exists = check_arc42(design_repo)
    section_drift, drift_warnings = compute_section_drift(design_repo, meta_section_hashes)
    warnings.extend(drift_warnings)

    result = {
        "issues": issues,
        "commits": commits,
        "commit_count": commit_count,
        "diff_stats": diff_stats,
        "journal_entry_count": journal["journal_entry_count"],
        "journal_validation": {
            "arc42_exists": arc42_exists,
            "section_drift": section_drift,
            "anchored_entries": journal["anchored_entries"],
            "unanchored_entries": journal["unanchored_entries"],
            "entries_without_anchors": journal["entries_without_anchors"],
            "empty_journal": journal["empty_journal"],
        },
        "warnings": warnings,
    }

    json.dump(result, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
