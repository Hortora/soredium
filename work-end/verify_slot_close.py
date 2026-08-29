#!/usr/bin/env python3
"""
verify_slot_close.py — Post-close audit for work-end.

Defense-in-depth verification that runs after every close sequence
(branch, main, slot). Checks all expected postconditions against
ground truth. Reports findings — doesn't block.

Usage:
    python3 verify_slot_close.py <project> branch=<name> workspace=<path>
        [covers=N,M] [issue_repo=<repo>] [slot_dir=<path>]
        [on_main=yes] [base_branch=main]

Output: VERIFIED=yes|no with per-check results.
Exit 0 always (verification outcome is data, not an error).
Exit 1 on missing args or operational errors.
"""

import json
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
        return {"status": "pass", "detail": msg}
    return {"status": "fail", "detail": f"tip is: {msg[:60]}"}


def check_landing_sha(project: str, branch: str, base: str = "main") -> dict:
    result = git(project, "log", "-1", "--format=%s", branch)
    if result.returncode != 0:
        return {"status": "fail", "detail": "branch not found"}
    msg = result.stdout.strip()
    sha_match = re.search(r"landed as ([0-9a-f]+)", msg)
    if not sha_match:
        return {"status": "warn", "detail": "no landing SHA in stamp (old format)"}
    sha = sha_match.group(1)
    verify = git(project, "merge-base", "--is-ancestor", sha, base)
    if verify.returncode == 0:
        return {"status": "pass", "detail": f"SHA {sha[:8]} on {base}"}
    return {"status": "fail", "detail": f"LANDING_SHA {sha[:8]} not on {base}"}


def check_main_pushed(project: str, base: str = "main") -> dict:
    result = git(project, "log", f"origin/{base}..{base}", "--oneline")
    if result.returncode != 0:
        return {"status": "pass", "detail": "no remote tracking"}
    unpushed = result.stdout.strip()
    if unpushed:
        count = len(unpushed.splitlines())
        return {"status": "fail", "detail": f"UNPUSHED: {count} commits ahead of origin/{base}"}
    return {"status": "pass"}


def check_workspace_stamped(workspace: str, branch: str) -> dict:
    result = git(workspace, "branch", "--list", branch)
    if result.returncode != 0 or not result.stdout.strip():
        return {"status": "warn", "detail": "workspace branch not found"}
    return check_branch_stamped(workspace, branch)


def check_on_main(repo: str, label: str) -> dict:
    result = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if result.returncode != 0:
        return {"status": "fail", "detail": f"cannot read HEAD for {label}"}
    branch = result.stdout.strip()
    if branch == "main":
        return {"status": "pass"}
    return {"status": "fail", "detail": f"{label} on {branch}, not main"}


def check_no_open_findings(workspace: str) -> dict:
    findings_path = Path(workspace) / ".audit" / "findings.jsonl"
    if not findings_path.exists():
        return {"status": "pass", "detail": "no findings file"}
    open_count = 0
    for line in findings_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if entry.get("status", "open") == "open":
                open_count += 1
        except (json.JSONDecodeError, ValueError):
            pass
    if open_count > 0:
        return {"status": "fail", "detail": f"{open_count} open finding(s)"}
    return {"status": "pass"}


def check_no_stale_scaffold(workspace: str) -> dict:
    stale = []
    for name in [".execute-progress", ".land-ledger.jsonl", ".artifacts-promoted"]:
        if (Path(workspace) / name).exists():
            stale.append(name)
    if stale:
        return {"status": "warn", "detail": f"stale: {', '.join(stale)}"}
    return {"status": "pass"}


def _parse_landed_repos(slot_dir: str) -> set[str]:
    """Parse .landed for repo names — handles both old (landed_shas=) and new (ledger) format."""
    landed = Path(slot_dir) / ".landed"
    if not landed.exists():
        return set()
    repos: set[str] = set()
    for line in landed.read_text().splitlines():
        if line.startswith("landed_shas="):
            shas_str = line.split("=", 1)[1]
            repos.update(entry.split(":")[0] for entry in shas_str.split(",") if ":" in entry)
        if line.startswith("issue="):
            repos.add("_has_ledger_entries")
    return repos


def _parse_landed_issues(slot_dir: str) -> set[int]:
    """Parse .landed ledger for completed issue numbers."""
    landed = Path(slot_dir) / ".landed"
    if not landed.exists():
        return set()
    issues: set[int] = set()
    for line in landed.read_text().splitlines():
        for part in line.split():
            if part.startswith("issue="):
                try:
                    issues.add(int(part.split("=", 1)[1]))
                except ValueError:
                    pass
    return issues


def _parse_slot_repos(slot_dir: str) -> set[str]:
    slot_file = Path(slot_dir) / ".slot"
    if not slot_file.exists():
        return set()
    repos: set[str] = set()
    in_repos = False
    for line in slot_file.read_text().splitlines():
        if line.strip() == "## Repos":
            in_repos = True
            continue
        if in_repos:
            if line.startswith("##"):
                break
            stripped = line.strip()
            if stripped.startswith("- "):
                name = stripped[2:].split("(")[0].strip()
                if name:
                    repos.add(name)
    if not repos:
        skip_prefixes = ("wsp-", ".m2", "attic")
        for entry in sorted(Path(slot_dir).iterdir()):
            if not entry.is_dir() or not (entry / ".git").exists():
                continue
            if any(entry.name.startswith(p) for p in skip_prefixes):
                continue
            repos.add(entry.name)
    return repos


def check_landed_marker(slot_dir: str) -> dict:
    landed = Path(slot_dir) / ".landed"
    if not landed.exists():
        return {"status": "fail", "detail": "no .landed marker"}
    if landed.is_dir():
        return {"status": "fail", "detail": ".landed is a directory, should be a file"}
    content = landed.read_text()
    if "landed_shas=" not in content:
        return {"status": "fail", "detail": "no landed_shas in .landed marker"}
    for line in content.splitlines():
        if line.startswith("failed="):
            failed = line.split("=", 1)[1]
            if failed:
                return {"status": "warn", "detail": f"partial land — failed repos: {failed}"}
    return {"status": "pass"}


def check_landed_shas_populated(slot_dir: str) -> dict:
    """Detect .landed entries with empty sha= — indicates land step never completed."""
    landed = Path(slot_dir) / ".landed"
    if not landed.exists():
        return {"status": "pass", "detail": "no .landed file"}
    empty_sha_issues = []
    for line in landed.read_text().splitlines():
        if "issue=" in line and "sha=" in line:
            for part in line.split():
                if part.startswith("sha=") and part == "sha=":
                    issue_part = next((p for p in line.split() if p.startswith("issue=")), "")
                    empty_sha_issues.append(issue_part.split("=", 1)[1] if "=" in issue_part else "?")
    if empty_sha_issues:
        return {"status": "fail",
                "detail": f"landed entries with no SHA (land step incomplete): issues {', '.join(empty_sha_issues)}"}
    return {"status": "pass"}


def check_landed_completeness(slot_dir: str) -> dict:
    """Verify all repos in .slot have SHAs in .landed."""
    slot_repos = _parse_slot_repos(slot_dir)
    if not slot_repos:
        return {"status": "pass", "detail": "no repos in .slot"}
    landed_repos = _parse_landed_repos(slot_dir)
    missing = slot_repos - landed_repos
    if missing:
        return {"status": "fail", "detail": f"repos not in .landed: {', '.join(sorted(missing))}"}
    extra = landed_repos - slot_repos
    if extra:
        return {"status": "warn", "detail": f"extra repos in .landed: {', '.join(sorted(extra))}"}
    return {"status": "pass", "detail": f"{len(landed_repos)}/{len(slot_repos)} repos landed"}


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
    return {"status": "fail", "detail": f"{repo_name} SHA {landed_sha[:8]} not reachable from main"}


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


def check_slot_marker(slot_dir: str, marker: str) -> dict:
    path = Path(slot_dir) / marker
    if path.exists() and path.is_file():
        return {"status": "pass"}
    if path.exists() and path.is_dir():
        return {"status": "fail", "detail": f"{marker} is a directory, should be a file"}
    return {"status": "fail", "detail": f"{marker} missing"}


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
    on_main: bool = False,
) -> bool:
    checks: list[tuple[str, dict]] = []

    if on_main:
        checks.append(("project_pushed", check_main_pushed(project, base)))
        checks.append(("workspace_pushed", check_main_pushed(workspace, base)))
        checks.append(("no_open_findings", check_no_open_findings(workspace)))
        checks.append(("no_stale_scaffold", check_no_stale_scaffold(workspace)))
    else:
        checks.append(("project_merged", check_branch_merged(project, branch, base)))
        checks.append(("project_stamped", check_branch_stamped(project, branch)))
        checks.append(("project_landing_sha", check_landing_sha(project, branch, base)))
        checks.append(("project_pushed", check_main_pushed(project, base)))
        checks.append(("workspace_merged", check_branch_merged(workspace, branch, base)))
        checks.append(("workspace_stamped", check_workspace_stamped(workspace, branch)))
        checks.append(("workspace_pushed", check_main_pushed(workspace, base)))
        checks.append(("project_on_main", check_on_main(project, "project")))
        checks.append(("workspace_on_main", check_on_main(workspace, "workspace")))
        checks.append(("no_open_findings", check_no_open_findings(workspace)))
        checks.append(("no_stale_scaffold", check_no_stale_scaffold(workspace)))

    if covers and issue_repo:
        checks.append(("issues_closed", check_issues_closed(issue_repo, covers)))

    if slot_dir:
        checks.append(("landed_marker", check_landed_marker(slot_dir)))
        checks.append(("landed_shas_populated", check_landed_shas_populated(slot_dir)))
        checks.append(("landed_completeness", check_landed_completeness(slot_dir)))
        checks.append(("phase_a_marker", check_slot_marker(slot_dir, ".phase-a-complete")))
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
        print(f"  {icon} {name}: {status}{suffix}")
        if status == "fail":
            all_pass = False

    if all_pass:
        print("VERIFIED=yes")
    else:
        print("VERIFIED=no")
    return all_pass


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: verify_slot_close.py <project> branch=<name> workspace=<path> "
              "[covers=N,M] [issue_repo=<repo>] [slot_dir=<path>] [on_main=yes]",
              file=sys.stderr)
        return 1

    project = sys.argv[1]
    opts = parse_args(sys.argv[2:])

    branch = opts.get("branch", "")
    workspace = opts.get("workspace", "")
    base = opts.get("base_branch", "main")
    on_main = opts.get("on_main", "no") == "yes"

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
           slot_dir=slot_dir, original_repos=original_repos,
           on_main=on_main)
    return 0


if __name__ == "__main__":
    sys.exit(main())
