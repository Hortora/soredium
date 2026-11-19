#!/usr/bin/env python3
"""
Promote workspace artifacts to main branch or project repo, close issues.

Usage: python3 artifact_promote.py <subcommand> <args...>

Subcommands:
    to-workspace-main  <workspace> branch=<name> artifacts=<comma-sep-paths>
    to-project         <project> <workspace> artifacts=<comma-sep-paths>
    close-issues       <repo> covers=<comma-sep-issue-numbers>
    archive-plans      <workspace> branch=<name>

Nothing here pushes or pulls. A promotion is a commit; when it is made on the
base branch of a slot clone it is landed in the canonical repo through
project/canonical_sync.py, and publishing is `canonical_sync.py publish`.

Output (KEY=value lines):
    PROMOTED=<count>   (for to-workspace-main, to-project)
    LANDED=yes         the commit is on the canonical repo's base branch, on disk
    LANDED=branch      the commit is on a working branch and lands when that branch does
    LANDED=no          it could not be landed in canonical (LAND_ERROR= says why)
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
import xml.etree.ElementTree as ET
from pathlib import Path

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)
from common import parse_args
from git_util import git
from plan_io import parse_covers_qualified
import canonical_sync
from canonical_sync import SyncError

# `verification` is imported as a package, so its parent directory goes on the path.
# (The package directory itself was added here before, and every promotion of a
# markdown file died with ModuleNotFoundError after staging it, before the commit.)
_skills_root = str(Path(__file__).resolve().parent.parent)
if _skills_root not in sys.path:
    sys.path.insert(0, _skills_root)


class ImageNotPromoted(Exception):
    """An image the source has did not arrive with the document that refers to it."""


def _copromote_images(md_source: Path, md_dest: Path, repo_cwd: str) -> list[str]:
    """Copy images referenced by a .md file from source to destination, and prove it.

    A reference the source itself cannot resolve is skipped: nothing can be lost.
    An image the source has must be at the destination afterwards, identical and
    staged; otherwise ImageNotPromoted is raised and the caller must not commit.

    Returns the list of repo-relative paths that were staged.
    """
    from verification.repo_checks import extract_image_refs

    if md_source.suffix != ".md":
        return []

    dest_repo = Path(repo_cwd)
    staged: list[str] = []
    for raw_ref, resolved_src in extract_image_refs(md_source):
        if not resolved_src.is_file():
            continue
        if resolved_src.suffix.lower() == ".svg":
            try:
                ET.parse(resolved_src)
            except ET.ParseError as e:
                raise ImageNotPromoted(
                    f"{raw_ref} (for {md_source.name}): invalid SVG XML — {e}")
        if raw_ref.startswith("/"):
            img_dest = dest_repo / raw_ref.lstrip("/")
        else:
            img_dest = md_dest.parent / raw_ref
        try:
            img_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(resolved_src), str(img_dest))
            arrived = img_dest.read_bytes() == resolved_src.read_bytes()
        except OSError as error:
            raise ImageNotPromoted(f"{raw_ref} (for {md_source.name}): {error}") from error
        if not arrived:
            raise ImageNotPromoted(f"{raw_ref} (for {md_source.name}): destination differs")
        try:
            img_rel = str(img_dest.relative_to(dest_repo))
        except ValueError:
            raise ImageNotPromoted(
                f"{raw_ref} (for {md_source.name}): resolves outside {dest_repo.name}")
        if git(repo_cwd, "add", img_rel).returncode != 0:
            raise ImageNotPromoted(f"{raw_ref} (for {md_source.name}): could not be staged")
        staged.append(img_rel)
    return staged


def _abandon_staged(repo_cwd: str) -> None:
    """Unstage what a failed promotion staged. The copied files stay in the working tree
    as untracked files: nothing is deleted, and nothing half-promoted is committed."""
    git(repo_cwd, "reset", "-q")


def _land_or_report(cwd: str) -> None:
    """Say where the commit just made in `cwd` stands, and land it when that is possible.

    Never pushes. A commit on the base branch of the canonical repo is landed
    already. A commit on a slot clone's base branch is landed in canonical now.
    A commit on a working branch lands when the branch does.
    """
    branch = subprocess.run(
        ["git", "-C", cwd, "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        canon = canonical_sync.locate(cwd)
        if branch != canon.base:
            print("LANDED=branch")
            return
        if canonical_sync.is_clone(cwd, canon):
            canonical_sync.land(cwd, branch)
        print("LANDED=yes")
    except SyncError as error:
        print("LANDED=no")
        print(f"LAND_ERROR={error.detail}")



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

    promoted = 0
    skipped: list[str] = []
    try:
      with canonical_sync.checked_out(workspace, "main") as wt:
        wt = Path(wt)
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
            if src.resolve() == dst.resolve():
                pass        # the workspace is on main: the artifact is already in place
            elif src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(str(src), str(dst))
            else:
                shutil.copy2(str(src), str(dst))
            git(str(wt), "add", artifact)
            try:
                _copromote_images(src, dst, str(wt))  # return value unused here
            except ImageNotPromoted as error:
                _abandon_staged(str(wt))
                print("ERROR=image_not_promoted")
                print(f"ERROR_DETAIL={error}")
                print("PROMOTED=0")
                return 1
            promoted += 1

        if promoted > 0:
            r = git(str(wt), "commit", "-m", f"docs(work-end): promote artifacts from {branch}")
            if r.returncode != 0:
                if "nothing to commit" not in r.stdout and "nothing to commit" not in r.stderr:
                    print("ERROR=commit_failed")
                    print(f"ERROR_DETAIL=Failed to commit: {r.stderr.strip()}")
                    return 1

            _land_or_report(str(wt))
    except SyncError as error:
        print("ERROR=worktree_failed")
        print(f"ERROR_DETAIL={error.detail}")
        return 1

    print(f"PROMOTED={promoted}")
    if skipped:
        print(f"SKIPPED={len(skipped)}")
        print(f"SKIPPED_PATHS={','.join(skipped)}")
    return 0


def _commit_msg(prefix: str, covers: str, repo: Path | None = None) -> str:
    from close import _issue_trailer
    issue = ""
    if covers:
        refs = parse_covers_qualified(covers)
        if refs:
            issue = str(refs[0].number) if not refs[0].repo else f"{refs[0].repo}#{refs[0].number}"
    trailer = _issue_trailer(issue, repo)
    return f"{prefix}\n\n{trailer}"


def _rollback_copied(target_cwd: str, copied_paths: list[str]) -> None:
    """Unstage and remove files this run copied. Leave everything else alone."""
    for p in copied_paths:
        git(target_cwd, "reset", "-q", "--", p)
        if git(target_cwd, "cat-file", "-e", f"HEAD:{p}").returncode == 0:
            # The path was already in the branch (an image two entries share,
            # say): put back what was there. Removing it would leave a deletion.
            git(target_cwd, "checkout", "-q", "HEAD", "--", p)
            continue
        full = Path(target_cwd) / p
        if full.exists():
            full.unlink()
            parent = full.parent
            while parent != Path(target_cwd) and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent


def _promote_to_target(ws: Path, target: Path, target_cwd: str,
                       artifacts: list[str], dest_prefix: str,
                       covers: str, dry_run: bool,
                       check_conflicts: bool) -> tuple[int, list[str]]:
    """Returns (exit_code, committed_paths)."""
    promoted = 0
    skipped: list[str] = []
    committed_paths: list[str] = []
    copied_paths: list[str] = []

    for artifact in artifacts:
        src = ws / artifact
        dst_rel = f"{dest_prefix}{artifact}" if dest_prefix else artifact
        dst = target / dst_rel

        if not src.exists():
            skipped.append(artifact)
            print(f"SKIP_DETAIL={artifact}: source not found", file=sys.stderr)
            continue

        if src.is_dir():
            art_copied: list[str] = []
            art_conflicts: list[str] = []
            for src_file in sorted(src.rglob("*")):
                if not src_file.is_file():
                    continue
                rel_in_dir = src_file.relative_to(src)
                file_dst_rel = f"{dst_rel}/{rel_in_dir}"
                file_dst = target / file_dst_rel
                if check_conflicts and file_dst.exists():
                    if file_dst.read_bytes() == src_file.read_bytes():
                        continue
                    print(f"CONFLICT={file_dst_rel}")
                    art_conflicts.append(file_dst_rel)
                    continue
                if dry_run:
                    continue
                file_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src_file), str(file_dst))
                r = git(target_cwd, "add", file_dst_rel)
                if r.returncode == 0:
                    committed_paths.append(file_dst_rel)
                    copied_paths.append(file_dst_rel)
                    art_copied.append(file_dst_rel)
            if dry_run:
                print(f"GAP={artifact} -> {dst_rel}")
                promoted += 1
            elif art_copied:
                promoted += 1
            continue

        if check_conflicts and dst.exists():
            if dst.read_bytes() == src.read_bytes():
                continue
            print(f"CONFLICT={dst_rel}")
            continue

        if dry_run:
            print(f"GAP={artifact} -> {dst_rel}")
            promoted += 1
            continue

        if src.resolve() != dst.resolve():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied_paths.append(dst_rel)

        r = git(target_cwd, "add", dst_rel)
        if r.returncode == 0:
            promoted += 1
            committed_paths.append(dst_rel)
            try:
                img_paths = _copromote_images(src, dst, target_cwd)
                committed_paths.extend(img_paths)
                copied_paths.extend(img_paths)
            except ImageNotPromoted as error:
                _rollback_copied(target_cwd, copied_paths)
                print("ERROR=image_not_promoted")
                print(f"ERROR_DETAIL={error}")
                print("PROMOTED=0")
                return 1, []
        else:
            skipped.append(artifact)
            print(f"SKIP_DETAIL={artifact}: {r.stderr.strip()}", file=sys.stderr)

    if promoted > 0 and not dry_run and committed_paths:
        msg = _commit_msg("docs(work-end): project-promote artifacts from workspace",
                          covers, target)
        r = git(target_cwd, "commit", "-m", msg, "--", *committed_paths)
        if r.returncode != 0:
            if "nothing to commit" not in r.stdout and "nothing to commit" not in r.stderr:
                _rollback_copied(target_cwd, copied_paths)
                print("ERROR=commit_failed")
                print(f"ERROR_DETAIL={r.stderr.strip()}")
                print("PROMOTED=0")
                return 1, []

    if dry_run:
        print("DRY_RUN=yes")
    print(f"PROMOTED={promoted}")
    if skipped:
        print(f"SKIPPED={len(skipped)}")
        print(f"SKIPPED_PATHS={','.join(skipped)}")
    return 0, committed_paths


def to_project(project: str, workspace: str, params: dict[str, str]) -> int:
    artifacts_str = params.get("artifacts", "")
    dest_prefix = params.get("dest-prefix", "")
    covers = params.get("covers", "")
    scope = params.get("scope", "")
    dry_run = params.get("dry_run", "no") == "yes"

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

    if scope == "branch":
        rc, _ = _promote_to_target(ws, proj, project, artifacts, dest_prefix,
                                   covers, dry_run, check_conflicts=False)
        if rc == 0 and not dry_run:
            _land_or_report(project)
        return rc

    try:
        canon = canonical_sync.locate(project)
        base = canon.base
    except SyncError:
        base = "main"

    try:
        with canonical_sync.checked_out(project, base) as wt:
            rc, _ = _promote_to_target(ws, Path(wt), str(wt), artifacts, dest_prefix,
                                       covers, dry_run, check_conflicts=True)
            if rc == 0 and not dry_run:
                _land_or_report(str(wt))
        return rc
    except SyncError as error:
        print("ERROR=worktree_failed")
        print(f"ERROR_DETAIL={error.detail}")
        return 1


def close_issues(repo: str, params: dict[str, str]) -> int:
    covers_str = params.get("covers", "")

    if not covers_str:
        print("ERROR=missing_covers")
        print("ERROR_DETAIL=covers= argument required")
        return 1

    refs = parse_covers_qualified(covers_str)
    if not refs:
        print("CLOSED=0")
        return 0

    closed = 0
    errors = []
    for ref in refs:
        target_repo = ref.repo or repo
        try:
            subprocess.run(
                ["gh", "issue", "close", str(ref.number), "--repo", target_repo],
                capture_output=True, text=True, check=True,
            )
            closed += 1
        except subprocess.CalledProcessError as e:
            errors.append(f"#{ref.number}: {e.stderr.strip()}")

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

    archived = 0
    skipped: list[str] = []
    try:
      with canonical_sync.checked_out(workspace, "main") as target:
        target = Path(target)
        on_main = target.resolve() == ws.resolve()

        target_plans = target / "plans"
        target_plans.mkdir(parents=True, exist_ok=True)

        if not on_main:
            for pf in plan_files:
                src = pf if source_dir else (ws / pf.relative_to(scan_root))
                dst = target_plans / pf.name
                try:
                    shutil.copy2(str(src), str(dst))
                except Exception as e:
                    skipped.append(pf.name)
                    print(f"SKIP_DETAIL={pf.name}: {e}", file=sys.stderr)

        attic_dir = target_plans / "attic" / branch
        attic_dir.mkdir(parents=True, exist_ok=True)
        for pf in plan_files:
            if pf.name in skipped:
                continue
            src = target_plans / pf.name if not on_main else pf
            if src.exists():
                shutil.move(str(src), str(attic_dir / pf.name))
                archived += 1

        if archived > 0:
            git(str(target), "add", "-A", "plans/")
            r = git(str(target), "commit", "-m", f"docs(work-end): archive plans from {branch}")
            if r.returncode != 0:
                if "nothing to commit" not in (r.stdout + r.stderr):
                    print("ERROR=commit_failed")
                    print(f"ERROR_DETAIL={r.stderr.strip()}")
                    return 1

            _land_or_report(str(target))
    except SyncError as error:
        print("ERROR=worktree_failed")
        print(f"ERROR_DETAIL={error.detail}")
        return 1

    print(f"ARCHIVED={archived}")
    if skipped:
        print(f"SKIPPED={len(skipped)}")
        print(f"SKIPPED_PATHS={','.join(skipped)}")
    return 0


def sweep_promotion_gaps(project: str, workspace: str, params: dict[str, str]) -> int:
    """Detect and fix workspace→project promotion gaps.

    Compares workspace blog/specs/images against project docs/ and
    promotes anything missing. Runs as a final sweep after branch-based
    promotion to catch content written directly to workspace main.

    Works in a temporary checkout of the base branch so the project's
    working tree, index and checked-out branch are never touched.
    """
    from verification.cross_checks import SKIP_FILENAMES, _IMG_SUFFIXES

    ws = Path(workspace)
    proj = Path(project)
    covers = params.get("covers", "")
    dry_run = params.get("dry_run", "no") == "yes"

    if not ws.is_dir() or not proj.is_dir():
        print("ERROR=path_not_found")
        return 1

    try:
        canon = canonical_sync.locate(project)
        base = canon.base
    except SyncError:
        base = "main"

    try:
      with canonical_sync.checked_out(project, base) as wt:
        wt_path = Path(wt)

        gap_files: list[tuple[str, Path, str]] = []
        for art_type, ws_sub, proj_sub in [("blog", "blog", "docs/blog"), ("spec", "specs", "docs/specs")]:
            ws_dir = ws / ws_sub
            dest_dir = wt_path / proj_sub
            if not ws_dir.exists():
                continue
            dest_names = set()
            if dest_dir.exists():
                dest_names = {f.name for f in dest_dir.glob("*.md")}
            for f in sorted(ws_dir.glob("*.md")):
                if f.name in SKIP_FILENAMES or f.name in dest_names:
                    continue
                dest_rel = f"{proj_sub}/{f.name}"
                dest_path = wt_path / dest_rel
                if dest_path.exists():
                    if dest_path.read_bytes() == f.read_bytes():
                        continue
                    print(f"CONFLICT={dest_rel}")
                    continue
                gap_files.append((art_type, f, dest_rel))

        for img_sub in ("images", "svg", "assets"):
            ws_imgs = ws / "blog" / img_sub
            dest_imgs = wt_path / "docs" / "blog" / img_sub
            if not ws_imgs.exists():
                continue
            dest_img_names = set()
            if dest_imgs.exists():
                dest_img_names = {f.name for f in dest_imgs.iterdir()
                                  if f.suffix.lower() in _IMG_SUFFIXES}
            for f in ws_imgs.iterdir():
                if f.suffix.lower() in _IMG_SUFFIXES and f.name not in dest_img_names:
                    dest_rel = f"docs/blog/{img_sub}/{f.name}"
                    gap_files.append(("image", f, dest_rel))

        if not gap_files:
            print("PROMOTION_GAPS=0")
            return 0

        print(f"PROMOTION_GAPS={len(gap_files)}")
        for art_type, src, dest_rel in gap_files:
            print(f"GAP=unpromoted-{art_type}: {src.name} -> {dest_rel}")

        if dry_run:
            print("SWEPT=0")
            print("DRY_RUN=yes")
            return 0

        swept = 0
        committed_paths: list[str] = []
        copied_paths: list[str] = []
        for art_type, src, dest_rel in gap_files:
            dest_path = wt_path / dest_rel
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dest_path))
            r = git(str(wt_path), "add", dest_rel)
            if r.returncode != 0:
                _rollback_copied(str(wt_path), copied_paths)
                print("ERROR=stage_failed")
                print(f"ERROR_DETAIL={r.stderr.strip()}")
                print("SWEPT=0")
                return 1
            committed_paths.append(dest_rel)
            copied_paths.append(dest_rel)
            if art_type != "image" and src.suffix == ".md":
                try:
                    img_paths = _copromote_images(src, dest_path, str(wt_path))
                    committed_paths.extend(img_paths)
                    copied_paths.extend(img_paths)
                except ImageNotPromoted as error:
                    _rollback_copied(str(wt_path), copied_paths)
                    print("ERROR=image_not_promoted")
                    print(f"ERROR_DETAIL={error}")
                    print("SWEPT=0")
                    return 1
            swept += 1

        if swept > 0 and committed_paths:
            msg = _commit_msg(
                f"docs(work-end): sweep-promote {swept} workspace artifacts",
                covers, wt_path)
            r = git(str(wt_path), "commit", "-m", msg, "--", *committed_paths)
            if r.returncode != 0:
                if "nothing to commit" not in r.stdout and "nothing to commit" not in r.stderr:
                    _rollback_copied(str(wt_path), copied_paths)
                    print("ERROR=commit_failed")
                    print(f"ERROR_DETAIL={r.stderr.strip()}")
                    print("SWEPT=0")
                    return 1
            else:
                _land_or_report(str(wt_path))

        print(f"SWEPT={swept}")
        return 0
    except SyncError as error:
        print("ERROR=worktree_failed")
        print(f"ERROR_DETAIL={error.detail}")
        return 1


SUBCOMMANDS = {
    "to-workspace-main": lambda args: to_workspace_main(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
    "to-project": lambda args: to_project(args[0], args[1], parse_args(args[2:])) if len(args) >= 2 else _usage(),
    "close-issues": lambda args: close_issues(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
    "archive-plans": lambda args: archive_plans(args[0], parse_args(args[1:])) if len(args) >= 1 else _usage(),
    "sweep-gaps": lambda args: sweep_promotion_gaps(args[0], args[1], parse_args(args[2:])) if len(args) >= 2 else _usage(),
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
