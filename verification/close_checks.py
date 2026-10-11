"""Close-time verification checks.

Pure functions that verify postconditions after a work-end close sequence.
Each check returns list[Finding]. No side effects, no fixes.

Migrated from verify_slot_close.py to unify with the verification/ library.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import sys

from verification import Finding, NOT_APPLICABLE, git, is_git_repo, read_file_safe

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)
from slot_io import parse_slot as _parse_slot, parse_landed as _parse_landed

STAMP_PREFIX = "chore: branch closed"

CEREMONY_PREFIXES = (
    "chore: branch closed",
    "chore: commit lifecycle state",
    "chore: strip lifecycle files",
    "chore: commit pending workspace state",
    "chore(work-end): cleanup branch scaffold",
    "chore: cleanup branch scaffold",
)

LIFECYCLE_FILES = {
    ".plan", "JOURNAL.md", ".execute-progress",
    ".land-ledger.jsonl", ".artifacts-promoted",
    ".close-progress", ".close-report.json",
    ".close-log.jsonl", ".wrap-log.jsonl",
    ".close-progress.done", ".close-progress.tmp",
    ".squash-plan-soredium.json",
}

LIFECYCLE_PREFIXES = ("plans/", "specs/", ".squash-plan-")


def _is_ceremony_commit(subject: str) -> bool:
    return any(subject.startswith(p) for p in CEREMONY_PREFIXES)


def _is_lifecycle_file(path: str) -> bool:
    basename = path.split("/")[-1] if "/" in path else path
    if basename in LIFECYCLE_FILES:
        return True
    return any(path.startswith(p) for p in LIFECYCLE_PREFIXES)


def check_issues_closed(issue_repo: str, covers: list[int] | None) -> list[Finding]:
    if not covers:
        return []
    open_issues: list[str] = []
    for issue_num in covers:
        result = subprocess.run(
            ["gh", "issue", "view", str(issue_num), "--repo", issue_repo,
             "--json", "state", "--jq", ".state"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            open_issues.append(f"#{issue_num} (gh failed)")
        elif result.stdout.strip() != "CLOSED":
            open_issues.append(f"#{issue_num}")
    if open_issues:
        return [Finding("ERROR", "issues-not-closed",
                         f"OPEN: {', '.join(open_issues)}")]
    return []


def check_on_main(repo_path: Path) -> list[Finding]:
    result = git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    if result.returncode != 0:
        return [Finding("ERROR", "on-main", f"cannot read HEAD for {repo_path.name}")]
    branch = result.stdout.strip()
    if branch != "main":
        return [Finding("ERROR", "on-main", f"{repo_path.name} on {branch}, not main")]
    return []


def check_main_pushed(repo_path: Path, base: str = "main") -> list[Finding]:
    result = git(repo_path, "log", f"origin/{base}..{base}", "--oneline")
    if result.returncode != 0:
        return []
    unpushed = result.stdout.strip()
    if unpushed:
        count = len(unpushed.splitlines())
        return [Finding("ERROR", "unpushed-main",
                         f"{count} commits ahead of origin/{base}")]
    return []


def check_landed_marker(slot_dir: Path) -> list[Finding]:
    landed = slot_dir / ".landed"
    if not landed.exists():
        return [Finding("ERROR", "landed-marker", "no .landed marker")]
    if landed.is_dir():
        return [Finding("ERROR", "landed-marker", ".landed is a directory, should be a file")]
    content = landed.read_text()
    findings: list[Finding] = []
    if "landed_shas=" not in content:
        findings.append(Finding("ERROR", "landed-marker", "no landed_shas in .landed marker"))
        return findings
    for line in content.splitlines():
        if line.startswith("failed="):
            failed = line.split("=", 1)[1]
            if failed:
                findings.append(Finding("WARN", "landed-partial",
                                         f"partial land — failed repos: {failed}"))
    for line in content.splitlines():
        if "issue=" in line and "sha=" in line:
            for part in line.split():
                if part.startswith("sha=") and part == "sha=":
                    issue_part = next((p for p in line.split() if p.startswith("issue=")), "")
                    issue_id = issue_part.split("=", 1)[1] if "=" in issue_part else "?"
                    findings.append(Finding("ERROR", "landed-empty-sha",
                                             f"landed entry with no SHA for issue {issue_id}"))
    return findings


def _find_tree_on_ref(repo_path: Path, tree_sha: str, ref: str, max_commits: int = 500) -> str | None:
    result = git(repo_path, "log", ref, f"--format=%H %T", f"--max-count={max_commits}")
    if result.returncode != 0:
        return None
    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == tree_sha:
            return parts[0]
    return None


def _verify_sha_on_ref(repo_path: Path, sha: str, ref: str) -> list[Finding]:
    direct = git(repo_path, "merge-base", "--is-ancestor", sha, ref)
    if direct.returncode == 0:
        return []
    tree_result = git(repo_path, "rev-parse", f"{sha}^{{tree}}")
    if tree_result.returncode != 0:
        return [Finding("ERROR", "stamp-sha-not-on-base",
                         f"SHA {sha[:8]} not resolvable")]
    tree_sha = tree_result.stdout.strip()
    match = _find_tree_on_ref(repo_path, tree_sha, ref)
    if match:
        return []
    diff_result = git(repo_path, "diff", "--stat", sha, ref)
    if diff_result.returncode == 0 and not diff_result.stdout.strip():
        return []
    return [Finding("ERROR", "stamp-sha-not-on-base",
                     f"SHA {sha[:8]} not on {ref}")]


def check_branch_stamp(
    repo_path: Path, branch: str, base: str = "main",
    verify_sha: bool = True,
) -> list[Finding]:
    result = git(repo_path, "log", "-5", "--format=%s", branch)
    if result.returncode != 0:
        return [Finding("ERROR", "branch-not-found", f"branch {branch} not found")]
    stamp_msg = ""
    for line in result.stdout.strip().splitlines():
        if line.startswith(STAMP_PREFIX):
            stamp_msg = line
            break
    if not stamp_msg:
        tip = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        return [Finding("ERROR", "branch-not-stamped", f"tip is: {tip[:60]}")]
    if not verify_sha:
        return []
    sha_match = re.search(r"landed as ([0-9a-f]+)", stamp_msg)
    if not sha_match:
        return [Finding("WARN", "stamp-no-sha", "no landing SHA in stamp (old format)")]
    sha = sha_match.group(1)
    return _verify_sha_on_ref(repo_path, sha, base)


def _find_landing_sha_from_stamp(repo_path: Path, branch: str) -> str | None:
    result = git(repo_path, "log", "-5", "--format=%s", branch)
    if result.returncode != 0:
        return None
    for line in result.stdout.strip().splitlines():
        if line.startswith("chore: branch closed") and "landed as " in line:
            m = re.search(r"landed as ([0-9a-f]+)", line)
            if m:
                return m.group(1)
    return None


def check_branch_merged(repo_path: Path, branch: str, base: str = "main") -> list[Finding]:
    result = git(repo_path, "log", "--oneline", f"{base}..{branch}")
    if result.returncode != 0:
        return [Finding("ERROR", "branch-not-merged", f"branch {branch} not found")]
    unmerged = [
        line for line in result.stdout.strip().splitlines()
        if line and not _is_ceremony_commit(line.split(" ", 1)[-1])
    ]
    if unmerged:
        return [Finding("ERROR", "branch-not-merged",
                         f"UNMERGED: {len(unmerged)} commits not on {base}")]
    main_tree = git(repo_path, "rev-parse", f"{base}^{{tree}}")
    if main_tree.returncode != 0:
        return [Finding("ERROR", "branch-not-merged",
                         "cannot resolve tree SHAs for content verification")]
    tip_tree = git(repo_path, "rev-parse", f"{branch}^{{tree}}")
    if tip_tree.returncode == 0 and tip_tree.stdout.strip() == main_tree.stdout.strip():
        return []
    pre_stamp_tree = git(repo_path, "rev-parse", f"{branch}~1^{{tree}}")
    if pre_stamp_tree.returncode == 0 and pre_stamp_tree.stdout.strip() == main_tree.stdout.strip():
        return []
    diff_result = git(repo_path, "diff", "--name-only", f"{base}..{branch}")
    if diff_result.returncode == 0 and diff_result.stdout.strip():
        diff_files = [f.strip() for f in diff_result.stdout.strip().splitlines() if f.strip()]
        if all(_is_lifecycle_file(f) for f in diff_files):
            return []
    ancestor = git(repo_path, "merge-base", "--is-ancestor", f"{branch}~1", base)
    if ancestor.returncode == 0:
        return []
    landing_sha = _find_landing_sha_from_stamp(repo_path, branch)
    if landing_sha:
        on_main = git(repo_path, "merge-base", "--is-ancestor", landing_sha, base)
        if on_main.returncode == 0:
            return []
    return [Finding("ERROR", "branch-not-merged",
                     f"branch content not on {base} (tree mismatch)")]


def _parse_landed_sha(slot_dir: Path, repo_name: str) -> str:
    landed = slot_dir / ".landed"
    if not landed.exists():
        return ""
    for line in landed.read_text().splitlines():
        if line.startswith("landed_shas="):
            shas_str = line.split("=", 1)[1]
            for entry in shas_str.split(","):
                if ":" in entry:
                    name, sha = entry.split(":", 1)
                    if name == repo_name:
                        return sha
    return ""


def check_canonical_sync(
    slot_dir: Path, repo_name: str, canonical_path: Path,
    branch: str = "", base: str = "main",
) -> list[Finding]:
    landed = slot_dir / ".landed"
    if not landed.exists():
        return [Finding("ERROR", "canonical-sync", "no .landed marker")]
    landed_sha = _parse_landed_sha(slot_dir, repo_name)
    if not landed_sha:
        clone_path = slot_dir / repo_name
        if branch and clone_path.is_dir():
            has_branch = git(clone_path, "rev-parse", "--verify", f"refs/heads/{branch}")
            if has_branch.returncode != 0:
                return []
            ahead = git(clone_path, "rev-list", "--count", f"main..{branch}")
            if ahead.returncode == 0 and ahead.stdout.strip() == "0":
                return []
        return [Finding("ERROR", "canonical-sync", f"no landed SHA for {repo_name}")]
    clone_path = slot_dir / repo_name
    direct = git(canonical_path, "merge-base", "--is-ancestor", landed_sha, base)
    if direct.returncode == 0:
        return []
    tree_result = git(clone_path, "rev-parse", f"{landed_sha}^{{tree}}")
    if tree_result.returncode != 0:
        tree_result = git(canonical_path, "rev-parse", f"{landed_sha}^{{tree}}")
    if tree_result.returncode != 0:
        return [Finding("ERROR", "canonical-sync",
                         f"{repo_name} SHA {landed_sha[:8]} not resolvable")]
    tree_sha = tree_result.stdout.strip()
    match = _find_tree_on_ref(canonical_path, tree_sha, base)
    if match:
        return []
    if git(canonical_path, "rev-parse", landed_sha).returncode == 0:
        diff_result = git(canonical_path, "diff", "--stat", landed_sha, base)
        if diff_result.returncode == 0 and not diff_result.stdout.strip():
            return []
    return [Finding("ERROR", "canonical-sync",
                     f"{repo_name} SHA {landed_sha[:8]} not reachable from {base}")]


def check_no_open_findings(workspace: Path) -> list[Finding]:
    findings_path = workspace / ".audit" / "findings.jsonl"
    if not findings_path.exists():
        return []
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
        return [Finding("ERROR", "open-findings", f"{open_count} open finding(s)")]
    return []


def check_artifacts_promoted(workspace: Path, on_main: bool = False) -> list[Finding]:
    if on_main:
        return []
    for candidate in [
        workspace / ".artifacts-promoted",
        workspace / "design" / ".artifacts-promoted",
    ]:
        if candidate.exists():
            return []
    result = git(workspace, "log", "--oneline", "--all", "-1",
                 "--grep=workspace and project promotion stamp")
    if result.returncode == 0 and result.stdout.strip():
        return []
    return [Finding("WARN", "artifacts-not-promoted",
                     "no .artifacts-promoted stamp found")]


def check_no_stale_scaffold(workspace: Path) -> list[Finding]:
    stale = []
    for name in [".execute-progress", ".land-ledger.jsonl", ".artifacts-promoted"]:
        if (workspace / name).exists():
            stale.append(name)
    if stale:
        return [Finding("WARN", "stale-scaffold", f"stale: {', '.join(stale)}")]
    return []


def check_landed_completeness(
    slot_dir: Path,
    repos: set[str] | None = None,
    branch: str = "",
) -> list[Finding]:
    if repos is not None:
        slot_repos = repos
    else:
        si = _parse_slot(slot_dir)
        slot_repos = set(si.repos) if si else set()
    if not slot_repos:
        return []
    li = _parse_landed(slot_dir)
    landed_repos = set(li.shas.keys()) if li else set()
    missing = slot_repos - landed_repos
    if missing and branch:
        auto_passed: list[str] = []
        for repo_name in sorted(missing):
            clone_path = slot_dir / repo_name
            if not clone_path.is_dir():
                auto_passed.append(repo_name)
                continue
            has_branch = git(clone_path, "rev-parse", "--verify", f"refs/heads/{branch}")
            if has_branch.returncode != 0:
                auto_passed.append(repo_name)
                continue
            ahead = git(clone_path, "rev-list", "--count", f"main..{branch}")
            if ahead.returncode == 0 and ahead.stdout.strip() == "0":
                auto_passed.append(repo_name)
        missing -= set(auto_passed)
    if missing:
        return [Finding("ERROR", "landed-incomplete",
                         f"repos not in .landed: {', '.join(sorted(missing))}")]
    extra = landed_repos - slot_repos
    if extra:
        return [Finding("WARN", "landed-extra",
                         f"extra repos in .landed: {', '.join(sorted(extra))}")]
    return []


def check_slot_archive_status(slot_dir: Path, attic_dir: str) -> list[Finding]:
    if Path(attic_dir).is_dir():
        return []
    slot_path = slot_dir if isinstance(slot_dir, Path) else Path(slot_dir)
    if slot_path.is_dir() and (slot_path / ".landed").exists():
        return [Finding("WARN", "not-archived", "landed but not archived")]
    if slot_path.is_dir():
        return [Finding("WARN", "not-archived", "active — not landed")]
    return [Finding("ERROR", "slot-not-found", "slot not found")]


def check_slot_marker(slot_dir: Path, marker: str) -> list[Finding]:
    path = slot_dir / marker
    if path.exists() and path.is_file():
        return []
    if path.exists() and path.is_dir():
        return [Finding("ERROR", "slot-marker", f"{marker} is a directory, should be a file")]
    return [Finding("ERROR", "slot-marker", f"{marker} missing")]


def resolve_canonical_repos(
    slot_dir: Path,
    covers_repos: set[str] | None = None,
) -> dict[str, str]:
    result = {}
    slot_path = slot_dir if isinstance(slot_dir, Path) else Path(slot_dir)
    for sub in sorted(slot_path.iterdir()):
        if not sub.is_dir() or not (sub / ".git").exists():
            continue
        if sub.name in (".m2", "attic") or sub.name.startswith("wsp-"):
            continue
        if covers_repos and sub.name not in covers_repos:
            continue
        local_url = git(sub, "remote", "get-url", "local")
        if local_url.returncode == 0 and local_url.stdout.strip():
            orig_path = local_url.stdout.strip()
            if Path(orig_path).is_dir():
                result[sub.name] = orig_path
    return result
