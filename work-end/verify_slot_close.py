#!/usr/bin/env python3
"""
verify_slot_close.py — Unified verification gate for work-end.

Checks that all repos are merged, stamped, pushed, and artifacts promoted.
Defense-in-depth audit — the primary fix is Execute's mechanical per-repo
loop; this catches bugs in Execute itself.

Usage:
    python3 verify_slot_close.py <project> branch=<name> workspace=<path> [covers=N,M]

Output: VERIFIED=yes|no with per-check results.
Exit 0 always (verification outcome is data, not an error).
Exit 1 on missing args or operational errors.
"""

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import parse_args


def git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True,
        timeout=10,
    )


def check_branch_merged(project: str, branch: str, base: str = "main") -> dict:
    result = git(project, "log", "--oneline", f"{base}..{branch}")
    if result.returncode != 0:
        return {"status": "fail", "detail": f"branch {branch} not found"}
    unmerged = [
        line for line in result.stdout.strip().splitlines()
        if line and not line.split(" ", 1)[-1].startswith("chore: branch closed")
    ]
    if unmerged:
        return {"status": "fail", "detail": f"UNMERGED: {len(unmerged)} commits not on {base}"}
    return {"status": "pass"}


def check_branch_stamped(project: str, branch: str) -> dict:
    result = git(project, "log", "-1", "--format=%s", branch)
    if result.returncode != 0:
        return {"status": "fail", "detail": f"branch {branch} not found"}
    msg = result.stdout.strip()
    if msg.startswith("chore: branch closed"):
        return {"status": "pass"}
    return {"status": "fail", "detail": "UNSTAMPED"}


def check_landing_sha(project: str, branch: str, base: str = "main") -> dict:
    result = git(project, "log", "-1", "--format=%s", branch)
    if result.returncode != 0:
        return {"status": "fail", "detail": "branch not found"}
    msg = result.stdout.strip()
    sha_match = re.search(r"landed as ([0-9a-f]+)", msg)
    if not sha_match:
        return {"status": "warn", "detail": "no landing SHA in stamp (old format — may indicate skipped squash-merge)"}
    sha = sha_match.group(1)
    verify = git(project, "merge-base", "--is-ancestor", sha, base)
    if verify.returncode == 0:
        return {"status": "pass", "detail": f"SHA {sha[:8]} on {base}"}
    return {"status": "fail", "detail": f"LANDING_SHA {sha[:8]} not on {base}"}


def check_main_pushed(project: str, base: str = "main") -> dict:
    result = git(project, "log", f"origin/{base}..{base}", "--oneline")
    if result.returncode != 0:
        return {"status": "pass", "detail": "no remote tracking (single remote check skipped)"}
    unpushed = result.stdout.strip()
    if unpushed:
        count = len(unpushed.splitlines())
        return {"status": "fail", "detail": f"UNPUSHED: {count} commits ahead of origin/{base}"}
    return {"status": "pass"}


def check_workspace_stamped(workspace: str, branch: str) -> dict:
    result = git(workspace, "branch", "--list", branch)
    if result.returncode != 0 or not result.stdout.strip():
        return {"status": "warn", "detail": "workspace branch not found — verify single-repo mode or branch deletion"}
    return check_branch_stamped(workspace, branch)


def check_landed_marker(slot_dir: str) -> dict:
    landed = Path(slot_dir) / ".landed"
    if not landed.exists():
        return {"status": "fail", "detail": "no .landed marker"}
    content = landed.read_text()
    if "landed_shas=" not in content:
        return {"status": "fail", "detail": "no landed_shas in .landed marker"}
    for line in content.splitlines():
        if line.startswith("failed="):
            failed = line.split("=", 1)[1]
            if failed:
                return {"status": "warn", "detail": f"partial land — failed repos: {failed}"}
    return {"status": "pass"}


def check_original_sync(slot_dir: str, repo_name: str, original_path: str) -> dict:
    landed = Path(slot_dir) / ".landed"
    if not landed.exists():
        return {"status": "fail", "detail": "no .landed marker"}

    landed_sha = ""
    for line in landed.read_text().splitlines():
        if line.startswith("landed_shas="):
            shas_str = line.split("=", 1)[1]
            for entry in shas_str.split(","):
                if ":" in entry:
                    name, sha = entry.split(":", 1)
                    if name == repo_name:
                        landed_sha = sha
                        break

    if not landed_sha:
        return {"status": "fail", "detail": f"no landed SHA for {repo_name}"}

    result = git(original_path, "merge-base", "--is-ancestor", landed_sha, "main")
    if result.returncode == 0:
        return {"status": "pass", "detail": f"{repo_name} SHA {landed_sha[:8]} on main"}
    return {"status": "fail", "detail": f"{repo_name} SHA {landed_sha[:8]} not reachable from main — original behind"}


def check_slot_archive_status(slot_dir: str, attic_dir: str) -> dict:
    if Path(attic_dir).is_dir():
        return {"status": "pass", "detail": "archived"}
    slot_path = Path(slot_dir)
    if slot_path.is_dir() and (slot_path / ".landed").exists():
        return {"status": "warn", "detail": "landed but not archived"}
    if slot_path.is_dir():
        return {"status": "warn", "detail": "active — not landed"}
    return {"status": "fail", "detail": "slot not found"}


def check_issues_closed(issue_repo: str, covers: list[int] | None) -> dict:
    if not covers:
        return {"status": "pass", "detail": "no issues to check"}
    open_issues = []
    for issue_num in covers:
        result = subprocess.run(
            ["gh", "issue", "view", str(issue_num), "--repo", issue_repo,
             "--json", "state", "--jq", ".state"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            open_issues.append(f"#{issue_num} (gh failed)")
            continue
        state = result.stdout.strip()
        if state != "CLOSED":
            open_issues.append(f"#{issue_num}")
    if open_issues:
        return {"status": "fail", "detail": f"OPEN: {', '.join(open_issues)}"}
    return {"status": "pass", "detail": f"{len(covers)}/{len(covers)} closed"}


def _resolve_original_repos(slot_dir: str) -> dict[str, str]:
    result = {}
    slot_path = Path(slot_dir)
    for sub in sorted(slot_path.iterdir()):
        if not sub.is_dir() or not (sub / ".git").exists():
            continue
        if sub.name in (".m2", "attic"):
            continue
        local_url = git(str(sub), "remote", "get-url", "local")
        if local_url.returncode == 0 and local_url.stdout.strip():
            orig_path = local_url.stdout.strip()
            if Path(orig_path).is_dir():
                result[sub.name] = orig_path
    return result


def verify(
    project: str, branch: str, workspace: str,
    base: str = "main", covers: list[int] | None = None,
    issue_repo: str = "",
    slot_dir: str = "", original_repos: dict[str, str] | None = None,
) -> bool:
    checks: list[tuple[str, dict]] = []

    checks.append(("project_merged", check_branch_merged(project, branch, base)))
    checks.append(("project_stamped", check_branch_stamped(project, branch)))
    checks.append(("landing_sha", check_landing_sha(project, branch, base)))
    checks.append(("main_pushed", check_main_pushed(project, base)))
    checks.append(("workspace_stamped", check_workspace_stamped(workspace, branch)))

    if covers and issue_repo:
        checks.append(("issues_closed", check_issues_closed(issue_repo, covers)))

    if slot_dir:
        checks.append(("landed_marker", check_landed_marker(slot_dir)))
        if original_repos:
            for repo_name, orig_path in original_repos.items():
                checks.append((
                    f"original_sync_{repo_name}",
                    check_original_sync(slot_dir, repo_name, orig_path),
                ))
                checks.append((
                    f"original_pushed_{repo_name}",
                    check_main_pushed(str(orig_path), base),
                ))
        slot_num = Path(slot_dir).name
        attic = str(Path(slot_dir).parent / "attic" / slot_num)
        checks.append(("archive_status", check_slot_archive_status(slot_dir, attic)))

    all_pass = True
    for name, result in checks:
        status = result["status"]
        detail = result.get("detail", "")
        icon = "✅" if status == "pass" else "❌" if status == "fail" else "⚠️"
        suffix = f" — {detail}" if detail else ""
        print(f"{icon} {name}: {status}{suffix}")
        if status == "fail":
            all_pass = False

    if all_pass:
        print("VERIFIED=yes")
    else:
        print("VERIFIED=no")
    return all_pass


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: verify_slot_close.py <project> branch=<name> workspace=<path> [covers=N,M] [slot_dir=<path>]",
              file=sys.stderr)
        return 1

    project = sys.argv[1]
    opts = parse_args(sys.argv[2:])

    branch = opts.get("branch", "")
    workspace = opts.get("workspace", "")
    base = opts.get("base_branch", "main")

    if not branch:
        print("ERROR=MISSING_ARGS")
        print("ERROR_DETAIL=branch= is required")
        return 1

    if not workspace:
        print("ERROR=MISSING_ARGS")
        print("ERROR_DETAIL=workspace= is required")
        return 1

    covers_str = opts.get("covers", "")
    covers = [int(x) for x in covers_str.split(",") if x.strip()] if covers_str else None
    issue_repo = opts.get("issue_repo", "")

    slot_dir = opts.get("slot_dir", "")
    original_repos = None
    if slot_dir:
        original_repos = _resolve_original_repos(slot_dir)

    verify(project, branch, workspace, base, covers,
           issue_repo=issue_repo,
           slot_dir=slot_dir, original_repos=original_repos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
