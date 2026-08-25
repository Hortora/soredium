#!/usr/bin/env python3
"""
Promote workspace artifacts to main branch or project repo, close issues.

Usage: python3 artifact_promote.py <subcommand> <args...>

Subcommands:
    to-workspace-main  <workspace> branch=<name> artifacts=<comma-sep-paths>
    to-project         <project> <workspace> artifacts=<comma-sep-paths>
    close-issues       <repo> covers=<comma-sep-issue-numbers>
    archive-plans      <workspace> branch=<name>

Output (KEY=value lines):
    PROMOTED=<count>   (for to-workspace-main, to-project)
    PUSHED=yes|failed|skipped
    PUSH_VERIFIED=yes|failed  (after successful push, verifies artifacts on origin/main)
    CLOSED=<count>     (for close-issues)

Error output:
    ERROR=<error_code>
    ERROR_DETAIL=<message>

Exit codes:
    0  success
    1  missing required args, I/O error, or operation failure
"""

import shutil
import subprocess
import sys
from pathlib import Path

from common import parse_args, subdir_prefix


def git(*cmd: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", cwd] + list(cmd),
        capture_output=True, text=True, check=True,
    )


def _has_remote(cwd: str) -> bool:
    try:
        r = git("remote", cwd=cwd)
        return bool(r.stdout.strip())
    except subprocess.CalledProcessError:
        return False


def _push_or_report(cwd: str, verify_paths: list[str] | None = None) -> None:
    if not _has_remote(cwd):
        print("PUSHED=skipped")
        return
    try:
        git("push", cwd=cwd)
        print("PUSHED=yes")
    except subprocess.CalledProcessError:
        try:
            branch = subprocess.run(
                ["git", "-C", cwd, "branch", "--show-current"],
                capture_output=True, text=True,
            ).stdout.strip()
            git("push", "-u", "origin", branch, cwd=cwd)
            print("PUSHED=yes")
        except subprocess.CalledProcessError as e2:
            print("PUSHED=failed")
            print(f"PUSH_ERROR={e2.stderr.strip()}")
            return

    if verify_paths:
        try:
            git("fetch", "origin", "main", cwd=cwd)
        except subprocess.CalledProcessError:
            print("PUSH_VERIFIED=failed")
            print("PUSH_VERIFY_DETAIL=fetch origin/main failed after push")
            return
        prefix = subdir_prefix(cwd)
        missing = []
        for path in verify_paths:
            try:
                git("cat-file", "-e", f"origin/main:{prefix}{path}", cwd=cwd)
            except subprocess.CalledProcessError:
                missing.append(path)
        if missing:
            print("PUSH_VERIFIED=failed")
            print(f"PUSH_VERIFY_MISSING={','.join(missing)}")
        else:
            print("PUSH_VERIFIED=yes")


def to_workspace_main(workspace: str, params: dict[str, str]) -> int:
    branch = params.get("branch", "")
    artifacts_str = params.get("artifacts", "")
    source_dir = params.get("source-dir", "")

    if not branch:
        print("ERROR=missing_branch")
        print("ERROR_DETAIL=branch= argument required")
        return 1
    if not artifacts_str:
        print("ERROR=missing_artifacts")
        print("ERROR_DETAIL=artifacts= argument required")
        return 1

    artifacts = [a.strip() for a in artifacts_str.split(",") if a.strip()]
    if not artifacts:
        print("PROMOTED=0")
        return 0

    ws = Path(workspace)
    if not ws.is_dir():
        print("ERROR=workspace_not_found")
        print(f"ERROR_DETAIL=Workspace directory not found: {workspace}")
        return 1

    wt = ws / ".promote-tmp"
    try:
        git("worktree", "add", str(wt), "main", cwd=workspace)
    except subprocess.CalledProcessError as e:
        print("ERROR=worktree_failed")
        print(f"ERROR_DETAIL=Failed to create worktree for main: {e.stderr.strip()}")
        return 1

    try:
        try:
            git("pull", "--rebase", "origin", "main", cwd=str(wt))
        except subprocess.CalledProcessError:
            pass

        promoted = 0
        skipped: list[str] = []
        for artifact in artifacts:
            if source_dir:
                src = Path(source_dir) / artifact
            else:
                src = ws / artifact
            if not src.exists():
                skipped.append(artifact)
                print(f"SKIP_DETAIL={artifact}: not found", file=sys.stderr)
                continue
            dst = wt / artifact
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(str(src), str(dst))
            else:
                shutil.copy2(str(src), str(dst))
            git("add", artifact, cwd=str(wt))
            promoted += 1

        promoted_paths = [a for a in artifacts if a not in skipped]

        if promoted > 0:
            try:
                git("commit", "-m", f"docs(work-end): promote artifacts from {branch}", cwd=str(wt))
            except subprocess.CalledProcessError as e:
                if "nothing to commit" not in e.stdout and "nothing to commit" not in e.stderr:
                    print("ERROR=commit_failed")
                    print(f"ERROR_DETAIL=Failed to commit: {e.stderr.strip()}")
                    return 1

            _push_or_report(str(wt), verify_paths=promoted_paths)
    finally:
        try:
            git("worktree", "remove", str(wt), "--force", cwd=workspace)
        except subprocess.CalledProcessError:
            if wt.exists():
                shutil.rmtree(wt, ignore_errors=True)
                try:
                    git("worktree", "prune", cwd=workspace)
                except subprocess.CalledProcessError:
                    pass

    # Switch back to branch
    try:
        git("checkout", branch, cwd=workspace)
    except subprocess.CalledProcessError:
        pass

    print(f"PROMOTED={promoted}")
    if skipped:
        print(f"SKIPPED={len(skipped)}")
        print(f"SKIPPED_PATHS={','.join(skipped)}")
    return 0


def to_project(project: str, workspace: str, params: dict[str, str]) -> int:
    artifacts_str = params.get("artifacts", "")
    dest_prefix = params.get("dest-prefix", "")

    if not artifacts_str:
        print("ERROR=missing_artifacts")
        print("ERROR_DETAIL=artifacts= argument required")
        return 1

    artifacts = [a.strip() for a in artifacts_str.split(",") if a.strip()]
    if not artifacts:
        print("PROMOTED=0")
        return 0

    proj = Path(project)
    ws = Path(workspace)

    if not proj.is_dir():
        print("ERROR=project_not_found")
        print(f"ERROR_DETAIL=Project directory not found: {project}")
        return 1
    if not ws.is_dir():
        print("ERROR=workspace_not_found")
        print(f"ERROR_DETAIL=Workspace directory not found: {workspace}")
        return 1

    promoted = 0
    skipped: list[str] = []
    for artifact in artifacts:
        src = ws / artifact
        dst_rel = f"{dest_prefix}{artifact}" if dest_prefix else artifact
        dst = proj / dst_rel

        if not src.exists():
            skipped.append(artifact)
            print(f"SKIP_DETAIL={artifact}: source not found", file=sys.stderr)
            continue

        if src.resolve() == dst.resolve():
            pass
        elif src.is_dir():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        try:
            git("add", dst_rel, cwd=project)
            promoted += 1
        except subprocess.CalledProcessError as e:
            skipped.append(artifact)
            print(f"SKIP_DETAIL={artifact}: {e.stderr.strip()}", file=sys.stderr)

    promoted_paths = [
        f"{dest_prefix}{a}" if dest_prefix else a
        for a in artifacts if a not in skipped
    ]

    if promoted > 0:
        try:
            git("commit", "-m", "docs(work-end): project-promote artifacts from workspace to project", cwd=project)
        except subprocess.CalledProcessError as e:
            if "nothing to commit" not in e.stdout and "nothing to commit" not in e.stderr:
                print("ERROR=commit_failed")
                print(f"ERROR_DETAIL=Failed to commit: {e.stderr.strip()}")
                return 1

        _push_or_report(project, verify_paths=promoted_paths)

    print(f"PROMOTED={promoted}")
    if skipped:
        print(f"SKIPPED={len(skipped)}")
        print(f"SKIPPED_PATHS={','.join(skipped)}")
    return 0


def close_issues(repo: str, params: dict[str, str]) -> int:
    covers_str = params.get("covers", "")

    if not covers_str:
        print("ERROR=missing_covers")
        print("ERROR_DETAIL=covers= argument required")
        return 1

    issues = [n.strip() for n in covers_str.split(",") if n.strip()]
    if not issues:
        print("CLOSED=0")
        return 0

    closed = 0
    errors = []
    for issue_num in issues:
        try:
            subprocess.run(
                ["gh", "issue", "close", issue_num, "--repo", repo],
                capture_output=True, text=True, check=True,
            )
            closed += 1
        except subprocess.CalledProcessError as e:
            errors.append(f"#{issue_num}: {e.stderr.strip()}")

    if errors and closed == 0:
        print("ERROR=gh_failed")
        print(f"ERROR_DETAIL=All issue closes failed: {'; '.join(errors)}")
        return 1

    print(f"CLOSED={closed}")
    if errors:
        print(f"ERRORS={'; '.join(errors)}")
    return 0


def archive_plans(workspace: str, params: dict[str, str]) -> int:
    branch = params.get("branch", "")
    source_dir = params.get("source-dir", "")
    if not branch:
        print("ERROR=missing_branch")
        print("ERROR_DETAIL=branch= argument required")
        return 1

    ws = Path(workspace)
    scan_root = Path(source_dir) if source_dir else ws
    plans_dir = scan_root / "plans"
    if not plans_dir.is_dir():
        print("ARCHIVED=0")
        return 0

    plan_files = [
        f for f in plans_dir.iterdir()
        if f.is_file() and f.suffix == ".md" and f.name != "INDEX.md"
    ]
    if not plan_files:
        print("ARCHIVED=0")
        return 0

    wt = ws / ".promote-tmp"
    try:
        git("worktree", "add", str(wt), "main", cwd=workspace)
    except subprocess.CalledProcessError as e:
        print("ERROR=worktree_failed")
        print(f"ERROR_DETAIL=Failed to create worktree for main: {e.stderr.strip()}")
        return 1

    try:
        try:
            git("pull", "--rebase", "origin", "main", cwd=str(wt))
        except subprocess.CalledProcessError:
            pass

        wt_plans = wt / "plans"
        wt_plans.mkdir(parents=True, exist_ok=True)

        skipped: list[str] = []
        for pf in plan_files:
            src = pf if source_dir else (ws / pf.relative_to(scan_root))
            dst = wt_plans / pf.name
            try:
                shutil.copy2(str(src), str(dst))
            except Exception as e:
                skipped.append(pf.name)
                print(f"SKIP_DETAIL={pf.name}: {e}", file=sys.stderr)

        attic_dir = wt_plans / "attic" / branch
        attic_dir.mkdir(parents=True, exist_ok=True)
        archived = 0
        for pf in plan_files:
            if pf.name in skipped:
                continue
            src = wt_plans / pf.name
            if src.exists():
                shutil.move(str(src), str(attic_dir / pf.name))
                archived += 1

        if archived > 0:
            try:
                git("add", "-A", "plans/", cwd=str(wt))
                git("commit", "-m", f"docs(work-end): archive plans from {branch}", cwd=str(wt))
            except subprocess.CalledProcessError as e:
                if "nothing to commit" not in (e.stdout + e.stderr):
                    print("ERROR=commit_failed")
                    print(f"ERROR_DETAIL={e.stderr.strip()}")
                    return 1

            _push_or_report(str(wt))
    finally:
        try:
            git("worktree", "remove", str(wt), "--force", cwd=workspace)
        except subprocess.CalledProcessError:
            if wt.exists():
                shutil.rmtree(wt, ignore_errors=True)
                try:
                    git("worktree", "prune", cwd=workspace)
                except subprocess.CalledProcessError:
                    pass

    print(f"ARCHIVED={archived}")
    if skipped:
        print(f"SKIPPED={len(skipped)}")
        print(f"SKIPPED_PATHS={','.join(skipped)}")
    return 0


SUBCOMMANDS = {
    "to-workspace-main": lambda args: to_workspace_main(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
    "to-project": lambda args: to_project(args[0], args[1], parse_args(args[2:])) if len(args) >= 2 else _usage(),
    "close-issues": lambda args: close_issues(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
    "archive-plans": lambda args: archive_plans(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
}


def _usage() -> int:
    print(__doc__, file=sys.stderr)
    return 1


def main() -> int:
    if len(sys.argv) < 2:
        return _usage()

    subcmd = sys.argv[1]
    if subcmd not in SUBCOMMANDS:
        print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
        return _usage()

    return SUBCOMMANDS[subcmd](sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
