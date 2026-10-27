"""Three-valued outcome verification for the work-end pipeline.

Replaces bool postconditions (step_postconditions.py) and overlapping
Finding-based checks (close_checks.py) with a unified layer.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from verification import Finding

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)
from git_util import git as _canonical_git


def _git(repo_path, *args: str, **kwargs) -> subprocess.CompletedProcess:
    return _canonical_git(repo_path, *args, timeout=kwargs.get("timeout", 10))


SOURCE_EXTENSIONS = (
    ".java", ".kt", ".xml", ".yaml", ".yml", ".json",
    ".properties", ".sql", ".py", ".ts", ".tsx", ".js",
    ".jsx", ".css", ".scss", ".html",
)


class VerifyResult(Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Verification:
    check: str
    result: VerifyResult
    evidence: dict
    repo: str


def compose_verifications(check: str, *verifications: Verification) -> Verification:
    worst = VerifyResult.PASS
    composite_evidence: dict = {}
    for v in verifications:
        composite_evidence[v.check] = {
            "result": v.result.value,
            "evidence": v.evidence,
            "repo": v.repo,
        }
        if v.result == VerifyResult.FAIL:
            worst = VerifyResult.FAIL
        elif v.result == VerifyResult.UNKNOWN and worst != VerifyResult.FAIL:
            worst = VerifyResult.UNKNOWN
    repo = verifications[0].repo if verifications else ""
    return Verification(check, worst, composite_evidence, repo)


def verification_to_findings(v: Verification) -> list[Finding]:
    if v.result == VerifyResult.PASS:
        return []
    severity = "ERROR" if v.result == VerifyResult.FAIL else "WARN"
    evidence_summary = "; ".join(f"{k}={val}" for k, val in v.evidence.items())
    return [Finding(severity, v.check, evidence_summary)]


def verify_content_landed(repo_path: Path, landed_sha: str,
                          base_branch: str) -> Verification:
    repo_name = Path(repo_path).name
    if not landed_sha:
        return Verification("content_landed", VerifyResult.UNKNOWN,
                            {"reason": "no_landed_sha"}, repo_name)

    result = _git(repo_path, "merge-base", "--is-ancestor", landed_sha, base_branch)
    if result.returncode == 0:
        return Verification("content_landed", VerifyResult.PASS,
                            {"method": "ancestry", "sha": landed_sha}, repo_name)

    diff = _git(repo_path, "diff", f"{base_branch}..{landed_sha}",
                "--", *[f"*{ext}" for ext in SOURCE_EXTENSIONS])
    if diff.returncode == 0 and not diff.stdout.strip():
        return Verification("content_landed", VerifyResult.PASS,
                            {"method": "empty_source_diff", "sha": landed_sha},
                            repo_name)

    if diff.returncode == 0:
        diff_names = _git(repo_path, "diff", "--name-only",
                          f"{base_branch}..{landed_sha}",
                          "--", *[f"*{ext}" for ext in SOURCE_EXTENSIONS])
        files = [f for f in diff_names.stdout.strip().split("\n") if f]
        return Verification("content_landed", VerifyResult.FAIL,
                            {"method": "diff_check", "diff_files": files,
                             "sha": landed_sha}, repo_name)

    return Verification("content_landed", VerifyResult.UNKNOWN,
                        {"reason": "diff_failed", "sha": landed_sha,
                         "stderr": diff.stderr[:200] if diff.stderr else ""},
                        repo_name)


def verify_push(repo_path: Path, base_branch: str) -> Verification:
    repo_name = Path(repo_path).name
    result = _git(repo_path, "log", f"origin/{base_branch}..{base_branch}",
                  "--oneline")
    if result.returncode != 0:
        return Verification("push", VerifyResult.UNKNOWN,
                            {"reason": "remote_unreachable",
                             "stderr": result.stderr[:200] if result.stderr else ""},
                            repo_name)
    unpushed = result.stdout.strip()
    if unpushed:
        count = len(unpushed.splitlines())
        return Verification("push", VerifyResult.FAIL,
                            {"unpushed_count": count}, repo_name)
    return Verification("push", VerifyResult.PASS,
                        {"method": "no_unpushed"}, repo_name)


STAMP_PREFIX = "chore: branch closed"


def verify_rebase(repo_path: Path, branch: str,
                  base_branch: str) -> Verification:
    repo_name = Path(repo_path).name
    result = _git(repo_path, "merge-base", "--is-ancestor", base_branch, branch)
    if result.returncode == 0:
        return Verification("rebase", VerifyResult.PASS,
                            {"method": "ancestry"}, repo_name)
    if result.returncode == 128 or (result.stderr and "Not a valid" in result.stderr):
        return Verification("rebase", VerifyResult.UNKNOWN,
                            {"reason": "ref_not_found", "branch": branch}, repo_name)
    return Verification("rebase", VerifyResult.FAIL,
                        {"method": "ancestry_failed", "branch": branch,
                         "base": base_branch}, repo_name)


def verify_branch_stamped(repo_path: Path, branch: str,
                          base_branch: str) -> Verification:
    repo_name = Path(repo_path).name
    result = _git(repo_path, "log", "-5", "--format=%s", branch)
    if result.returncode != 0:
        return Verification("branch_stamped", VerifyResult.UNKNOWN,
                            {"reason": "branch_not_found"}, repo_name)
    for line in result.stdout.strip().splitlines():
        if line.startswith(STAMP_PREFIX):
            sha_match = re.search(r"landed as ([0-9a-f]+)", line)
            if not sha_match:
                return Verification("branch_stamped", VerifyResult.PASS,
                                    {"method": "stamp_found_no_sha"}, repo_name)
            sha = sha_match.group(1)
            check = _git(repo_path, "merge-base", "--is-ancestor", sha, base_branch)
            if check.returncode == 0:
                return Verification("branch_stamped", VerifyResult.PASS,
                                    {"method": "stamp_sha_verified", "sha": sha},
                                    repo_name)
            return Verification("branch_stamped", VerifyResult.UNKNOWN,
                                {"reason": "stamp_sha_not_on_base", "sha": sha},
                                repo_name)
    return Verification("branch_stamped", VerifyResult.FAIL,
                        {"method": "no_stamp_found"}, repo_name)


def verify_artifacts_promoted(workspace: Path, project: Path,
                              branch: str, base_branch: str) -> Verification:
    repo_name = Path(workspace).name
    for candidate in [workspace / ".artifacts-promoted",
                      workspace / "design" / ".artifacts-promoted"]:
        if candidate.exists():
            return Verification("artifacts_promoted", VerifyResult.PASS,
                                {"method": "stamp_file"}, repo_name)
    result = _git(workspace, "log", "--oneline", "--all", "-1",
                  "--grep=workspace and project promotion stamp")
    if result.returncode == 0 and result.stdout.strip():
        return Verification("artifacts_promoted", VerifyResult.PASS,
                            {"method": "promotion_commit"}, repo_name)
    diff = _git(project, "diff", "--stat", f"{base_branch}..{branch}")
    if diff.returncode == 0 and not diff.stdout.strip():
        return Verification("artifacts_promoted", VerifyResult.PASS,
                            {"method": "no_diff"}, repo_name)
    return Verification("artifacts_promoted", VerifyResult.FAIL,
                        {"method": "no_evidence"}, repo_name)


def verify_issues_closed(issue_repo: str, covers: str,
                         plan_path: Path | None = None) -> Verification:
    if not covers or not issue_repo:
        return Verification("issues_closed", VerifyResult.PASS, {"reason": "no_covers"}, "")

    from plan_io import parse_covers
    closable = set(parse_covers(covers))

    if plan_path and plan_path.exists():
        try:
            _slot_dir = str(Path(__file__).resolve().parent.parent / "work-slot")
            if _slot_dir not in sys.path:
                sys.path.insert(0, _slot_dir)
            from plan_manager import parse_plan
            tree = parse_plan(plan_path)
            queue_closable = set()
            for item in tree.queue:
                if item.ref and (item.completed or item.active):
                    queue_closable.add(item.ref.number)
            if queue_closable:
                closable = closable & queue_closable
        except Exception:
            pass

    open_issues: list[str] = []
    for issue_num in closable:
        result = subprocess.run(
            ["gh", "issue", "view", str(issue_num), "--repo", issue_repo,
             "--json", "state", "--jq", ".state"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return Verification("issues_closed", VerifyResult.UNKNOWN,
                                {"reason": "gh_failed", "issue": issue_num,
                                 "stderr": result.stderr[:200] if result.stderr else ""},
                                "")
        if result.stdout.strip() != "CLOSED":
            open_issues.append(f"#{issue_num}")
    if open_issues:
        return Verification("issues_closed", VerifyResult.FAIL,
                            {"open_issues": open_issues}, "")
    return Verification("issues_closed", VerifyResult.PASS,
                        {"method": "all_closed", "count": len(closable)}, "")


def verify_checkout_main(project: Path, workspace: Path,
                         extra_repos: list[Path] | None = None) -> Verification:
    repos = [project, workspace] + (extra_repos or [])
    for repo in repos:
        if not repo.is_dir():
            continue
        result = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        if result.returncode != 0 or result.stdout.strip() != "main":
            branch = result.stdout.strip() if result.returncode == 0 else "unknown"
            return Verification("checkout_main", VerifyResult.FAIL,
                                {"repo": repo.name, "branch": branch}, repo.name)
    return Verification("checkout_main", VerifyResult.PASS,
                        {"method": "all_on_main", "count": len(repos)}, "")


def verify_landed_marker(slot_path: Path) -> Verification:
    if not slot_path:
        return Verification("landed_marker", VerifyResult.FAIL,
                            {"reason": "no_slot_path"}, "")
    landed = slot_path / ".landed"
    if not landed.exists():
        return Verification("landed_marker", VerifyResult.FAIL,
                            {"reason": "no_landed_file"}, slot_path.name)
    content = landed.read_text()
    if "landed_shas=" not in content:
        return Verification("landed_marker", VerifyResult.FAIL,
                            {"reason": "no_landed_shas_field"}, slot_path.name)
    for line in content.splitlines():
        if line.startswith("landed_shas="):
            shas = line.split("=", 1)[1]
            if not shas.strip():
                return Verification("landed_marker", VerifyResult.FAIL,
                                    {"reason": "empty_shas"}, slot_path.name)
            pairs = [p for p in shas.split(",") if ":" in p]
            if pairs and all(p.split(":", 1)[1].strip() for p in pairs):
                return Verification("landed_marker", VerifyResult.PASS,
                                    {"method": "valid_shas", "count": len(pairs)},
                                    slot_path.name)
            return Verification("landed_marker", VerifyResult.FAIL,
                                {"reason": "invalid_sha_pairs"}, slot_path.name)
    return Verification("landed_marker", VerifyResult.FAIL,
                        {"reason": "landed_shas_not_parsed"}, slot_path.name)


def verify_slot_phase_complete(slot_path: Path, marker: str) -> Verification:
    if not slot_path:
        return Verification("slot_phase_complete", VerifyResult.FAIL,
                            {"reason": "no_slot_path"}, "")
    path = slot_path / marker
    if path.exists() and path.is_file():
        return Verification("slot_phase_complete", VerifyResult.PASS,
                            {"method": "marker_exists", "marker": marker},
                            slot_path.name)
    return Verification("slot_phase_complete", VerifyResult.FAIL,
                        {"reason": "marker_missing", "marker": marker},
                        slot_path.name)


def verify_fork_next(workspace: Path, progress) -> Verification:
    fork_branch = progress.get("fork_next_branch", "")
    if not fork_branch:
        return Verification("fork_next", VerifyResult.FAIL,
                            {"reason": "no_fork_branch_in_progress"}, workspace.name)
    result = _git(workspace, "branch", "--list", fork_branch)
    if result.returncode == 0 and fork_branch in result.stdout:
        return Verification("fork_next", VerifyResult.PASS,
                            {"method": "branch_exists", "branch": fork_branch},
                            workspace.name)
    return Verification("fork_next", VerifyResult.FAIL,
                        {"reason": "branch_not_found", "branch": fork_branch},
                        workspace.name)


def verify_checkout_fork(workspace: Path, progress) -> Verification:
    fork_branch = progress.get("fork_next_branch", "")
    if not fork_branch:
        return Verification("checkout_fork", VerifyResult.PASS,
                            {"reason": "no_fork_branch"}, workspace.name)
    result = _git(workspace, "branch", "--show-current")
    if result.returncode == 0 and result.stdout.strip() == fork_branch:
        return Verification("checkout_fork", VerifyResult.PASS,
                            {"method": "on_fork_branch", "branch": fork_branch},
                            workspace.name)
    current = result.stdout.strip() if result.returncode == 0 else "unknown"
    return Verification("checkout_fork", VerifyResult.FAIL,
                        {"reason": "wrong_branch", "expected": fork_branch,
                         "actual": current}, workspace.name)


def verify_cleanup_scaffold(workspace: Path) -> Verification:
    scaffold = ["JOURNAL.md", ".execute-progress", ".land-ledger.jsonl",
                ".artifacts-promoted"]
    remaining = [f for f in scaffold if (workspace / f).exists()]
    if remaining:
        return Verification("cleanup_scaffold", VerifyResult.FAIL,
                            {"remaining": remaining}, workspace.name)
    plan = workspace / ".plan"
    if plan.exists():
        try:
            content = plan.read_text()
            for line in content.splitlines():
                if line.strip().startswith("state:"):
                    state = line.split(":", 1)[1].strip()
                    if state.startswith("closing:") or state == "idle":
                        return Verification("cleanup_scaffold", VerifyResult.FAIL,
                                            {"reason": "stale_plan_state", "state": state},
                                            workspace.name)
        except OSError:
            pass
    return Verification("cleanup_scaffold", VerifyResult.PASS,
                        {"method": "clean"}, workspace.name)


def verify_promote_plan_next(workspace: Path) -> Verification:
    if (workspace / ".plan-next").exists():
        return Verification("promote_plan_next", VerifyResult.FAIL,
                            {"reason": "plan_next_exists"}, workspace.name)
    return Verification("promote_plan_next", VerifyResult.PASS,
                        {"method": "no_plan_next"}, workspace.name)
