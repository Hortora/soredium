"""Slot lifecycle orchestrators.

create_slot, add_repo, merge_slot, archive_slot, remove_slot, restore_slot.
"""

import datetime
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))
_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)
_soredium_root = str(Path(__file__).resolve().parent.parent)
if _soredium_root not in sys.path:
    sys.path.insert(0, _soredium_root)
try:
    import worklog as _wl
except ImportError:
    _wl = None
from queue_io import parse_covers_qualified

from slot_core import (
    SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME,
    SlotCreationError, run_cmd,
    _resolve_slot_dir_for_number, _get_family_repo_names,
    resolve_canonical_repo, _get_clone_origin,
    get_slot_repos, get_all_slot_repos,
    _cleanup_remnant_dir, _escape_slot_cwd, _has_unmerged_content,
)
_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)
from slot_io import parse_slot, write_slot, set_slot_state
from slot_metadata import (
    is_slot_landed, verify_landed_shas, _fix_stale_checkboxes,
)
from slot_maven import setup_slot_repo, generate_mvn_wrapper
from slot_isx import (
    _check_isx_available, _truncate_instance_name,
    _teardown_isx, _wire_isx_remotes,
)
from slot_claude import (
    relocate_claude_projects, sweep_orphaned_claude_projects, is_claude_session,
)
from slot_git import (
    configure_slot_remotes, configure_update_instead,
    install_post_commit_hook, sync_main,
    _exclude_symlinks,
    _cleanup_inherited_symlinks,
    _repack_broken_alternates,
)
from slot_workspace import (
    validate_slot_wksp, resolve_workspace_source, discover_workspace,
    _unignore_subdir, repoint_wksp, create_proj_symlink, replicate_claude_md,
    validate_claude_md_paths, sanitize_slot_claude_md,
)
from slot_query import find_slot_by_branch
from slot_state import transition as _transition, current_state as _current_state


def _validate_covers_state(issue_repo: str, covers: str) -> None:
    """Warn (don't block) if any covered issue is closed on GitHub."""
    from plan_manager import _check_issue_state
    refs = parse_covers_qualified(covers)
    for ref in refs:
        repo = ref.repo or issue_repo
        state = _check_issue_state(repo, ref.number)
        if state == "CLOSED":
            print(f"WARN=covers_closed_issue ref={repo}#{ref.number}")
        elif state is None:
            print(f"WARN=github_unreachable ref={repo}#{ref.number}")


def _build_epic_plan(branch: str, issue_repo: str, cover_refs: list,
                     date: str) -> str | None:
    """Build a .plan from the epic's child issue list. Fetches titles from GitHub.

    cover_refs: list of CoverRef (from parse_covers_qualified) or plain strings.
    Each CoverRef carries its own repo; bare ints/strings fall back to issue_repo.
    """
    from plan_manager import QueueItem, IssueRef, build_plan_content
    items: list[QueueItem] = []
    for ref in cover_refs:
        # Duck-typed: plan_io and queue_io each define a CoverRef.
        if hasattr(ref, "number"):
            num = ref.number
            repo = getattr(ref, "repo", "") or issue_repo
        else:
            try:
                num = int(ref)
            except (ValueError, TypeError):
                continue
            repo = issue_repo
        rc, title_out, _ = run_cmd([
            "gh", "issue", "view", str(num), "--repo", repo,
            "--json", "title", "--jq", ".title",
        ])
        title = title_out.strip() if rc == 0 and title_out.strip() else f"Issue #{num}"
        items.append(QueueItem(ref=IssueRef(repo, num), title=title))
    if not items:
        return None
    items[0].active = True
    return build_plan_content(branch, items, date)



_LIFECYCLE_FILES = frozenset({".plan", ".queue", ".meta", "JOURNAL.md"})
_LIFECYCLE_PREFIXES = ("HANDOFF",)


def _strip_inherited_lifecycle(ws_dir: Path) -> list[str]:
    """Remove lifecycle files inherited from main after workspace clone.

    Workspace clones from main may carry .plan, HANDOFF.md, .meta, and
    JOURNAL.md from prior work. Strip them so the slot session starts clean
    and scaffold.py writes fresh lifecycle files for the slot's issue.
    """
    stripped: list[str] = []
    for name in sorted(_LIFECYCLE_FILES):
        f = ws_dir / name
        if f.exists() and not f.is_dir():
            f.unlink()
            stripped.append(name)
    for f in sorted(ws_dir.iterdir()):
        if (f.is_file()
                and f.suffix == ".md"
                and any(f.name.startswith(p) for p in _LIFECYCLE_PREFIXES)):
            f.unlink()
            stripped.append(f.name)
    if stripped:
        run_cmd(["git", "-C", str(ws_dir), "add", "-A"])
        run_cmd(["git", "-C", str(ws_dir), "commit", "-m",
                 "chore: strip inherited lifecycle files from main"])
        for name in stripped:
            print(f"STRIPPED_LIFECYCLE={name}")
    return stripped


@dataclass
class RepoPairResult:
    clone_dest: Path
    ws_dir: Path | None
    ws_name: str
    path_map: dict[str, str]


def clone_repo_pair(
    target_dir: Path,
    repo_path: Path,
    branch: str,
    *,
    m2_dir: Path | None = None,
    strip_lifecycle: bool = True,
    ws_info: tuple[Path, str] | None = None,
) -> RepoPairResult:
    """Clone a project repo and its workspace into target_dir.

    Clones repo_path into target_dir/<repo_name> with --shared, checks out
    branch (if non-empty), configures remotes, installs the post-commit hook,
    discovers or uses the provided workspace, and sets up wksp/proj symlinks.

    ws_info: None -> auto-discover workspace from repo_path's wksp symlink.
             (source, name) -> use this workspace; if the directory already
             exists it is reused without cloning.

    When auto-discovering (ws_info is None) and the workspace directory
    already exists, raises SlotCreationError (workspace name collision).

    When ws_info is provided, workspace clone failure is not raised -- the
    function returns with ws_dir=None so the caller can proceed.

    Repointing (repoint_wksp, create_proj_symlink, replicate_claude_md) is
    only performed in auto-discover mode; callers that pre-resolve workspace
    info handle repointing themselves.
    """
    repo_name = repo_path.name
    clone_dest = target_dir / repo_name
    path_map: dict[str, str] = {}
    auto_discover = ws_info is None

    # --- project clone ---
    rc, _, stderr = run_cmd([
        "git", "clone", "--shared", "--branch", "main",
        str(repo_path), str(clone_dest),
    ])
    if rc != 0:
        raise SlotCreationError(f"clone_failed repo={repo_name} stderr={stderr.strip()}")

    if branch:
        rc, _, _ = run_cmd(["git", "-C", str(clone_dest), "checkout", "-b", branch])
        if rc != 0:
            raise SlotCreationError(f"branch_create_failed repo={repo_name}")

    _cleanup_inherited_symlinks(clone_dest, target_dir)
    _exclude_symlinks(clone_dest)
    configure_slot_remotes(clone_dest, repo_path)
    configure_update_instead(repo_path)
    install_post_commit_hook(clone_dest)
    path_map[str(repo_path.resolve())] = str(clone_dest)

    if m2_dir:
        gi_changed = setup_slot_repo(clone_dest, m2_dir)
        if gi_changed:
            run_cmd(["git", "-C", str(clone_dest), "add", ".gitignore"])
            run_cmd(["git", "-C", str(clone_dest), "commit", "-m",
                     "chore: add slot infrastructure to .gitignore"])

    # --- workspace ---
    # A local wksp/ directory inside the project clone. Not a git clone of the
    # canonical workspace: no remote, no updateInstead, no contamination path.
    # git-inited so code that commits pipeline state still works.
    if auto_discover:
        ws_info = resolve_workspace_source(repo_path)
        if not ws_info:
            ws_info = discover_workspace(repo_path)
            if ws_info:
                print(f"DISCOVERED_WORKSPACE={ws_info[1]} repo={repo_name}")

    ws_dir: Path | None = None
    ws_name = "wksp"

    if ws_info:
        ws_source, _ws_canonical_name = ws_info
        ws_slot_dir = clone_dest / "wksp"

        if ws_slot_dir.exists() and (ws_slot_dir / ".git").exists():
            ws_dir = ws_slot_dir
        else:
            ws_slot_dir.mkdir(exist_ok=True)
            _exclude_symlinks(clone_dest)
            run_cmd(["git", "init", "-q", str(ws_slot_dir)])
            if branch:
                run_cmd(["git", "-C", str(ws_slot_dir),
                         "checkout", "-b", branch])
            else:
                run_cmd(["git", "-C", str(ws_slot_dir),
                         "commit", "--allow-empty", "-m", "init workspace"])

            (ws_slot_dir / ".workspace").write_text(f"project: {clone_dest}\n")
            path_map[str(ws_source.resolve())] = str(ws_slot_dir)
            ws_dir = ws_slot_dir

        if auto_discover and ws_dir:
            create_proj_symlink(ws_slot_dir, clone_dest)
            replicate_claude_md(repo_path, ws_slot_dir, clone_dest)

    return RepoPairResult(
        clone_dest=clone_dest, ws_dir=ws_dir, ws_name=ws_name,
        path_map=path_map)


_SLOT_DEBRIS = {".m2", ".mvn", "mvn", "mvnw", "mvnw.cmd"}


def _slot_dir_has_content(slot_dir: Path) -> bool:
    """True if slot_dir contains anything beyond creation debris.

    A slot with only .m2, .mvn, or Maven wrapper files is debris from a
    failed creation and can be safely removed. Anything else is real work.
    """
    if not slot_dir.exists():
        return False
    try:
        return any(c.name not in _SLOT_DEBRIS for c in slot_dir.iterdir())
    except OSError:
        return True


def _safe_remove_debris(slot_dir: Path, slot_num: int) -> bool:
    """Remove a slot directory only if it is empty debris. Returns True if removed."""
    if not slot_dir.exists():
        return True
    if _slot_dir_has_content(slot_dir):
        print(f"WARN=occupied_slot slot={slot_num} path={slot_dir} — "
              f"directory has content, refusing to delete")
        return False
    shutil.rmtree(str(slot_dir), ignore_errors=True)
    return True


def allocate_slot_number(family_root: Path) -> int:
    """Reserve next slot number via DB. Reuses pending/failed slots if available."""
    if _wl is None:
        print("ERROR=worklog_unavailable")
        print("ERROR_DETAIL=worklog module required for slot numbering — "
              "ensure scripts/worklog.py is importable")
        sys.exit(1)
    conn = _wl.connect()
    try:
        reusable = _wl.find_reusable_slot(conn, str(family_root))
        if reusable is not None:
            slot_num, others = reusable
            # Guard: never reuse a number that exists in the attic — that
            # creates a split-brain where both slots/N/ and slots/attic/N/ exist.
            for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
                attic_entry = family_root / dir_name / "attic" / str(slot_num)
                if attic_entry.exists():
                    print(f"WARN=attic_collision slot={slot_num} — skipping reuse, attic entry exists")
                    reusable = None
                    break
            # Guard: never reuse a number whose directory has content on disk.
            if reusable is not None:
                for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
                    candidate = family_root / dir_name / str(slot_num)
                    if _slot_dir_has_content(candidate):
                        print(f"WARN=occupied_reusable slot={slot_num} — "
                              f"directory has content, skipping reuse")
                        reusable = None
                        break
            if reusable is None:
                slot_num = _wl.reserve_slot_number(conn, str(family_root))
            else:
                for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
                    debris = family_root / dir_name / str(slot_num)
                    _safe_remove_debris(debris, slot_num)
                for other_num in others:
                    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
                        debris = family_root / dir_name / str(other_num)
                        _safe_remove_debris(debris, other_num)
                    _wl.fail_slot(conn, other_num, str(family_root))
                print(f"REUSED_PENDING={slot_num}")
                return slot_num
        else:
            slot_num = _wl.reserve_slot_number(conn, str(family_root))
    finally:
        conn.close()
    return slot_num


def _run_post_creation_checks(slot_dir: Path) -> None:
    """Run validation on a successfully created slot. Warns on failure, never destroys."""
    try:
        wksp_failures = validate_slot_wksp(slot_dir)
        for f in wksp_failures:
            print(f"WARN=wksp_validation {f}")
    except Exception as e:
        print(f"WARN=wksp_validation_error {e}")

    try:
        for ws_clone in sorted(slot_dir.iterdir()):
            ws_claude = ws_clone / "CLAUDE.md"
            if ws_clone.is_dir() and ws_claude.exists():
                for w in validate_claude_md_paths(ws_claude, slot_dir):
                    print(f"WARN=absolute_path_in_claude_md {w}")
    except Exception as e:
        print(f"WARN=claude_md_check_error {e}")

    try:
        from verification.postconditions import post_create_slot
        vfindings = post_create_slot(slot_dir)
        for f in vfindings:
            print(f"VERIFY_{f.severity}={f.category} {f.message}")
    except ImportError:
        print("WARN=verification_module_unavailable postcondition checks skipped")
    except Exception as e:
        print(f"WARN=postcondition_error {e}")


def create_slot(family_root: Path, repos: list[str], branch: str,
                issue: str, issue_repo: str, covers: str,
                context: str, title: str = "", description: str = "",
                isx: bool = False, isx_template: str = "",
                isx_instance: str = "") -> dict:
    if isx and not _check_isx_available():
        raise SlotCreationError("isx is not on PATH. Install with: brew install sanne/tap/incus-spawn")

    result = find_slot_by_branch(family_root, branch)
    if result is not None:
        existing_num, landed = result
        if landed:
            raise SlotCreationError(
                f"Slot {existing_num} has branch `{branch}` (landed, not yet archived). "
                f"Archive it first.")
        raise SlotCreationError(
            f"Slot {existing_num} already has branch `{branch}`. "
            f"Use that slot or archive it first.")

    slots_dir = family_root / SLOT_DIR_NAME
    slots_dir.mkdir(exist_ok=True)
    slot_num = allocate_slot_number(family_root)
    slot_dir = slots_dir / str(slot_num)

    if slot_dir.exists():
        raise SlotCreationError(
            f"Slot directory {slot_dir} already exists after allocation. "
            f"This indicates a DB/disk state mismatch — refusing to overwrite. "
            f"Inspect the directory and reconcile manually.")

    try:
        slot_dir.mkdir()
        m2_dir = slot_dir / ".m2"
        m2_dir.mkdir()
        generate_mvn_wrapper(slot_dir)
        path_map: dict[str, str] = {}

        for repo_name in repos:
            repo_path = family_root / repo_name
            if not repo_path.is_dir():
                raise SlotCreationError(f"repo_not_found repo={repo_name}")

            sync_main(str(repo_path))

            pair_result = clone_repo_pair(slot_dir, repo_path, branch,
                                          m2_dir=m2_dir)
            path_map.update(pair_result.path_map)

        sanitized = sanitize_slot_claude_md(slot_dir, path_map)
        for s in sanitized:
            print(f"SANITIZED_CLAUDE_MD={s}")
        if sanitized:
            for sub in sorted(slot_dir.iterdir()):
                if sub.is_dir() and (sub / ".git").is_dir() and (sub / "CLAUDE.md").exists():
                    rc_check, _, _ = run_cmd(["git", "-C", str(sub), "diff", "--quiet", "CLAUDE.md"])
                    if rc_check != 0:
                        run_cmd(["git", "-C", str(sub), "add", "CLAUDE.md"])
                        run_cmd(["git", "-C", str(sub), "commit", "-m", "chore: sanitize CLAUDE.md paths for slot isolation"])

        import queue_home
        queue_home.mark(slot_dir)

        primary_repo = repos[0]
        primary_wksp = slot_dir / primary_repo / "wksp"
        if not primary_wksp.exists():
            raise SlotCreationError(
                f"primary_no_workspace repo={primary_repo}: "
                f"primary repo has no workspace — .plan cannot be scaffolded. "
                f"Add a wksp symlink to {family_root / primary_repo} pointing to its workspace.")
        if primary_wksp.exists():
            ws_path = primary_wksp.resolve()
            scaffold_script = Path.home() / ".claude" / "skills" / "work-start" / "scaffold.py"
            if scaffold_script.exists():
                scaffold_args = [
                    sys.executable, str(scaffold_script), str(ws_path),
                    f"branch={branch}",
                    f"project-sha=slot-creation",
                    f"date={datetime.date.today().isoformat()}",
                    f"issue={issue}",
                    f"issue-repo={issue_repo}",
                    f"covers={covers}",
                    "force=yes",
                ]
                cover_refs = parse_covers_qualified(covers)
                if len(cover_refs) > 1:
                    plan_content = _build_epic_plan(
                        branch, issue_repo, cover_refs,
                        datetime.date.today().isoformat(),
                    )
                    if plan_content:
                        scaffold_args.append("plan=yes")
                        scaffold_args.append(f"plan-content={plan_content}")
                run_cmd(scaffold_args)

        instance_name = ""
        if isx:
            instance_name = isx_instance or _truncate_instance_name(branch)
            rc, _, stderr = run_cmd(["isx", "branch", instance_name, "--from", isx_template])
            if rc != 0:
                raise SlotCreationError(f"isx_branch_failed instance={instance_name} err={stderr.strip()}")

        write_slot(slot_dir, slot_number=slot_num, repos=repos, branch=branch,
                   issue=issue, issue_repo=issue_repo, covers=covers,
                   context=context, title=title, description=description,
                   isolation_type="isx" if isx else "",
                   isx_instance=instance_name if isx else "",
                   isx_template=isx_template if isx else "")

        if isx:
            _wire_isx_remotes(slot_dir, repos, instance_name)

        repo_paths = [str(family_root / r) for r in repos]
        _transition(
            slot_dir, "active",
            family_root=family_root, slot_number=slot_num,
            repos=repo_paths, branch=branch,
            issue_number=int(issue) if issue else 0,
            issue_repo=issue_repo, covers=covers,
            force=True,  # initial creation, no prior state
        )
    except Exception:
        if slot_dir.exists():
            shutil.rmtree(str(slot_dir), ignore_errors=True)
        if _wl:
            try:
                conn = _wl.connect()
                _wl.fail_slot(conn, slot_num, str(family_root))
                conn.close()
            except Exception:
                pass
        raise

    _run_post_creation_checks(slot_dir)

    if covers:
        _validate_covers_state(issue_repo, covers)

    return {
        "slot_number": slot_num,
        "slot_dir": str(slot_dir),
        "branch": branch,
        "repos": repos,
    }


def add_repo(family_root: Path, slot_number: int, repo_name: str,
             branch: str) -> None:
    slot_dir = family_root / SLOT_DIR_NAME / str(slot_number)
    if not slot_dir.is_dir():
        print(f"ERROR=slot_not_found slot={slot_number}")
        sys.exit(1)

    repo_path = family_root / repo_name
    if not repo_path.is_dir():
        print(f"ERROR=repo_not_found repo={repo_name}")
        sys.exit(1)

    clone_dest = slot_dir / repo_name
    if clone_dest.exists():
        print(f"ERROR=repo_already_in_slot repo={repo_name}")
        sys.exit(1)

    sync_main(str(repo_path))

    m2_dir = slot_dir / ".m2"
    m2_dir.mkdir(exist_ok=True)

    # Pre-resolve workspace with collision handling
    ws_raw = resolve_workspace_source(repo_path)
    if not ws_raw:
        ws_raw = discover_workspace(repo_path)
        if ws_raw:
            print(f"DISCOVERED_WORKSPACE={ws_raw[1]} repo={repo_name}")
    ws_resolved = None
    if ws_raw:
        ws_source, ws_name = ws_raw
        family_repo_names = _get_family_repo_names(family_root)
        if ws_name in family_repo_names:
            ws_name = f"work-{ws_source.name}"
        ws_slot_dir = slot_dir / ws_name
        if ws_slot_dir.exists():
            existing_origin = _get_clone_origin(ws_slot_dir)
            if existing_origin and str(ws_source) not in existing_origin:
                ws_name = f"work-{ws_source.name}"
        ws_resolved = (ws_source, ws_name)

    try:
        pair_result = clone_repo_pair(slot_dir, repo_path, branch,
                                      m2_dir=m2_dir, strip_lifecycle=False,
                                      ws_info=ws_resolved)
    except SlotCreationError as e:
        print(f"ERROR={e}")
        sys.exit(1)

    slot_info = parse_slot(slot_dir)
    if slot_info and slot_info.isolation_type == "isx":
        instance = slot_info.isx_instance
        if instance:
            _wire_isx_remotes(slot_dir, [repo_name], instance)

    # Workspace: clone_repo_pair created wksp/ inside the project clone.
    # Finish repointing if it wasn't done inside clone_repo_pair (non-auto mode).
    ws_slot_dir = pair_result.ws_dir
    if ws_slot_dir and not (ws_slot_dir / "proj").exists():
        create_proj_symlink(ws_slot_dir, pair_result.clone_dest)
        replicate_claude_md(repo_path, ws_slot_dir, pair_result.clone_dest)

    add_path_map = dict(pair_result.path_map)
    if ws_resolved and ws_slot_dir and ws_slot_dir.is_dir():
        ws_source, _ = ws_resolved
        add_path_map[str(ws_source.resolve())] = str(ws_slot_dir)
    sanitized = sanitize_slot_claude_md(slot_dir, add_path_map)
    for s in sanitized:
        print(f"SANITIZED_CLAUDE_MD={s}")
    if sanitized:
        subs_to_check = [pair_result.clone_dest]
        if ws_slot_dir and ws_slot_dir.is_dir():
            subs_to_check.append(ws_slot_dir)
        for sub in subs_to_check:
            if (sub / ".git").is_dir() and (sub / "CLAUDE.md").exists():
                rc_check, _, _ = run_cmd(["git", "-C", str(sub), "diff", "--quiet", "CLAUDE.md"])
                if rc_check != 0:
                    run_cmd(["git", "-C", str(sub), "add", "CLAUDE.md"])
                    run_cmd(["git", "-C", str(sub), "commit", "-m", "chore: sanitize CLAUDE.md paths for slot isolation"])

    _update_slot_repos(slot_dir, repo_name, add=True)

    wksp_failures = validate_slot_wksp(slot_dir, repo_names=[repo_name])
    if wksp_failures:
        for f in wksp_failures:
            print(f"ERROR=wksp_validation_failed detail={f}")
        sys.exit(1)

    print(f"ADDED={repo_name} SLOT={slot_number}")


def remove_repo(family_root: Path, slot_number: int, repo_name: str) -> None:
    slot_dir = family_root / SLOT_DIR_NAME / str(slot_number)
    if not slot_dir.is_dir():
        print(f"ERROR=slot_not_found slot={slot_number}")
        sys.exit(1)

    clone_dest = slot_dir / repo_name
    if not clone_dest.is_dir():
        print(f"ERROR=repo_not_in_slot repo={repo_name}")
        sys.exit(1)

    slot_info = parse_slot(slot_dir)
    repos = slot_info.repos if slot_info else []
    if repos and repos[0] == repo_name:
        raise ValueError(f"Cannot remove primary repo '{repo_name}' from slot {slot_number}")

    status_result = subprocess.run(
        ["git", "-C", str(clone_dest), "diff", "--quiet", "HEAD"],
        capture_output=True, text=True,
    )
    staged_result = subprocess.run(
        ["git", "-C", str(clone_dest), "diff", "--cached", "--quiet"],
        capture_output=True, text=True,
    )
    if status_result.returncode != 0 or staged_result.returncode != 0:
        print(f"ERROR=uncommitted_changes repo={repo_name}")
        sys.exit(1)

    shutil.rmtree(str(clone_dest), ignore_errors=True)
    _update_slot_repos(slot_dir, repo_name, add=False)
    print(f"REMOVED={repo_name} SLOT={slot_number}")


def _update_slot_repos(slot_dir: Path, repo_name: str, add: bool) -> None:
    slot_file = slot_dir / ".slot"
    if not slot_file.exists():
        return
    content = slot_file.read_text()
    lines = content.splitlines()
    new_lines = []
    in_repos = False
    for line in lines:
        if line.strip() == "## Repos":
            in_repos = True
            new_lines.append(line)
            continue
        if in_repos and line.startswith("## "):
            if add:
                new_lines.append(f"- {repo_name}")
            in_repos = False
        if in_repos and not add and line.strip() == f"- {repo_name}":
            continue
        new_lines.append(line)
    if in_repos and add:
        new_lines.append(f"- {repo_name}")
    slot_file.write_text("\n".join(new_lines) + "\n")






def merge_slot(family_root: Path, slot_num: int) -> int:
    """Removed. Kept as a stub so an old session or script gets a clear answer.

    This was a second landing path with its own preflight, rebase and push logic,
    including hard resets to the remote. Nothing has written the marker it needed
    (.phase-a-complete) since the close ceremony was rewritten, so it could not run.
    A slot is landed by `work end` inside it; close.py writes .landed when the
    slot's queue drains, and archive-slot verifies that marker.
    """
    print(f"ERROR=merge_slot_removed slot={slot_num}")
    print("HINT=run `work end` in the slot; it lands the work and marks the slot landed")
    return 1


def _has_active_plan(slot_dir: Path) -> str | None:
    """Check if any repo in the slot has an active .plan. Returns the path or None."""
    for sub in sorted(slot_dir.iterdir()):
        if not sub.is_dir():
            continue
        plan_file = sub / ".plan"
        if not plan_file.exists():
            continue
        try:
            content = plan_file.read_text()
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("state:"):
                    state = stripped.split(":", 1)[1].strip()
                    if state in ("active", "scaffolded", "transitioning"):
                        return str(plan_file)
        except OSError:
            continue
    return None


def _converge_state(slot_dir: Path, family_root: Path, slot_num: int) -> str | None:
    """Sync .slot state with disk reality. Returns the converged state, or None if no change."""
    cur = _current_state(slot_dir)
    has_landed = (slot_dir / ".landed").exists()
    has_phase_a = (slot_dir / ".phase-a-complete").exists()

    if has_landed and cur not in ("landed", "archived"):
        _transition(slot_dir, "landed", family_root=family_root,
                    slot_number=slot_num, force=True)
        print(f"STATE_CONVERGED=landed from={cur} slot={slot_num}")
        return "landed"
    if has_phase_a and cur == "active":
        _transition(slot_dir, "ready", family_root=family_root,
                    slot_number=slot_num, force=True)
        print(f"STATE_CONVERGED=ready from={cur} slot={slot_num}")
        return "ready"
    return None


def _tick_epic(epic_repo: str, epic_num: int, completed: list[int]) -> bool:
    """Tick the completed issues' checkboxes on the epic's GitHub issue.

    True when there was nothing to tick or GitHub accepted the update.
    """
    if not epic_repo or not epic_num or not completed:
        return True
    import plan_manager
    return plan_manager._tick_github_checkboxes(
        plan_manager.IssueRef(epic_repo, epic_num), completed)


def _tree_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def _purge_build_outputs(slot_dir: Path) -> tuple[int, int]:
    """Delete regenerable build outputs inside a slot: every .m2 directory, and every
    Maven target/ directory (sibling pom.xml, nothing tracked by git inside it).

    Never follows a symlink: a symlinked .m2 or target is unlinked and its destination
    is left alone. Returns (entries removed, bytes freed). Failures warn and continue.
    """
    removed = 0
    freed = 0

    def _remove(path: Path) -> None:
        nonlocal removed, freed
        try:
            if path.is_symlink():
                path.unlink()
            else:
                size = _tree_size(path)
                shutil.rmtree(path)
                freed += size
            removed += 1
        except OSError as e:
            print(f"WARN=purge_failed path={path} detail={e}")

    for root, dirs, _files in os.walk(slot_dir, topdown=True, followlinks=False):
        root_path = Path(root)
        for name in list(dirs):
            path = root_path / name
            if name == ".git":
                dirs.remove(name)
            elif name == ".m2":
                dirs.remove(name)
                _remove(path)
            elif name == "target" and (root_path / "pom.xml").is_file():
                dirs.remove(name)
                if not path.is_symlink():
                    rc, tracked, _ = run_cmd(["git", "-C", str(root_path), "ls-files", "--", "target"])
                    if rc == 0 and tracked.strip():
                        print(f"WARN=target_has_tracked_files path={path} — left in place")
                        continue
                _remove(path)
    return removed, freed


def archive_slot(family_root: Path, slot_num: int, force: bool = False,
                  resolution: str | None = None) -> None:
    slot_dir = _resolve_slot_dir_for_number(family_root, slot_num)
    if not slot_dir.exists():
        for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
            attic_entry = family_root / dir_name / "attic" / str(slot_num)
            if attic_entry.exists():
                print(f"NOTE=already_archived slot={slot_num}")
                print(f"ARCHIVED={slot_num}")
                return
        print(f"ERROR=slot_not_found slot={slot_num}")
        sys.exit(1)

    _converge_state(slot_dir, family_root, slot_num)

    from slot_claude import find_active_sessions, check_occupant_pid
    alive, occupant_pid = check_occupant_pid(slot_dir)
    if alive:
        print(f"OCCUPANT_PID={occupant_pid}")
        print(f"ERROR=occupant_pid_alive slot={slot_num}")
        print(f"ERROR_DETAIL=session PID {occupant_pid} is still running in this slot")
        print("HINT=wait for the session to end, or verify the PID is stale before retrying")
        sys.exit(1)

    active_plan = _has_active_plan(slot_dir)
    if active_plan and not force:
        print(f"ERROR=active_plan slot={slot_num}")
        print(f"ERROR_DETAIL=active .plan at {active_plan} — work is in progress")
        print("HINT=complete or pause the work first, or pass --force to override")
        sys.exit(1)
    shas_verified = False
    if is_slot_landed(slot_dir):
        shas_verified, _ = verify_landed_shas(slot_dir, family_root)
    unmerged = _has_unmerged_content(slot_dir)
    if unmerged and not shas_verified and not force:
        print(f"ERROR=unmerged_content slot={slot_num}")
        print(f"ERROR_DETAIL=repos with unmerged branch content: {', '.join(unmerged)}")
        print("HINT=land the branch content first, or manually verify it's already on main under different SHAs")
        sys.exit(1)
    if unmerged and (shas_verified or force):
        print(f"NOTE=unmerged_content_bypassed slot={slot_num} repos={','.join(unmerged)} reason={'shas_verified' if shas_verified else 'force'}")
    if not force and not is_slot_landed(slot_dir):
        print(f"ERROR=slot_not_landed slot={slot_num}")
        print("ERROR_DETAIL=slot has no .landed marker — work may be in progress")
        print("HINT=pass --force to override, or run merge-slot first")
        sys.exit(1)
    if not force:
        if not shas_verified:
            shas_verified, failures = verify_landed_shas(slot_dir, family_root)
        else:
            failures = []
        if not shas_verified:
            print(f"ERROR=sha_not_on_main slot={slot_num}")
            for f in failures:
                print(f"ERROR_DETAIL={f}")
            print("HINT=pass --force to override, or investigate the failed merge")
            sys.exit(1)
    active = find_active_sessions(slot_dir)
    if active:
        claude_sessions = [(pid, cmd, path) for pid, cmd, path in active if is_claude_session(cmd)]
        other_sessions = [(pid, cmd, path) for pid, cmd, path in active if not is_claude_session(cmd)]
        if claude_sessions:
            # Hard stop regardless of --force: moving the slot while a Claude Code
            # session is running corrupts its conversation history.
            for pid, cmd, path in claude_sessions:
                print(f"ACTIVE_CLAUDE_SESSION={pid}:{cmd}:{path}")
            print(f"ERROR=active_claude_sessions slot={slot_num}")
            print(f"ERROR_DETAIL={len(claude_sessions)} Claude Code session(s) running in slot — conversation history would be corrupted")
            print("HINT=close the Claude Code session first; --force does not bypass this check")
            sys.exit(1)
        if other_sessions:
            if not force:
                for pid, cmd, path in other_sessions:
                    print(f"ACTIVE_SESSION={pid}:{cmd}:{path}")
                print(f"ERROR=active_sessions slot={slot_num}")
                print(f"ERROR_DETAIL={len(other_sessions)} active process(es) in slot directory")
                print("HINT=close the session first, or pass --force to override")
                sys.exit(1)
            else:
                for pid, cmd, path in other_sessions:
                    print(f"WARN_ACTIVE_SESSION={pid}:{cmd}:{path}")
                print(f"WARN=active_sessions_overridden slot={slot_num}")

    has_promotion_stamp = any(
        (sub / ".artifacts-promoted").exists() or (sub / "design" / ".artifacts-promoted").exists()
        for sub in slot_dir.iterdir()
        if sub.is_dir()
    ) or (slot_dir / ".artifacts-promoted").exists() or (slot_dir / "design" / ".artifacts-promoted").exists()
    if not has_promotion_stamp:
        print(f"WARN=artifacts_not_promoted slot={slot_num}")

    slot_info = parse_slot(slot_dir)
    if slot_info and slot_info.is_epic:
        covers_str = slot_info.covers
        completed = [ref.number for ref in parse_covers_qualified(covers_str)]
        if completed:
            fixed = _fix_stale_checkboxes(slot_dir / ".slot", completed)
            if fixed:
                print(f"CHECKBOXES_FIXED={fixed}")
                print(f"WARN=stale_checkboxes issues={','.join(str(c) for c in completed)}")
            epic_num = int(slot_info.issue or "0")
            epic_repo = slot_info.issue_repo
            if not _tick_epic(epic_repo, epic_num, completed):
                print("WARN=github_unreachable_for_checkbox_verify")

    repacked = _repack_broken_alternates(slot_dir, family_root)
    if repacked:
        print(f"ALTERNATES_REPACKED={repacked}")

    _teardown_isx(slot_dir)

    purged, freed = _purge_build_outputs(slot_dir)
    if purged:
        print(f"BUILD_OUTPUTS_PURGED={purged} freed_mb={freed // (1024 * 1024)}")

    attic_dir = slot_dir.parent / "attic"
    attic_dir.mkdir(exist_ok=True)
    dest = attic_dir / str(slot_num)
    merge_into_existing = dest.exists()
    if merge_into_existing:
        print(f"WARN=attic_slot_exists slot={slot_num} — merging into existing attic entry")
    swept = sweep_orphaned_claude_projects(family_root)
    escaped, cwd_offset = _escape_slot_cwd(slot_dir, family_root)
    if escaped:
        print(f"CWD_ESCAPED={family_root}")

    prior_state = _current_state(slot_dir)
    set_slot_state(slot_dir, "archived")

    try:
        if merge_into_existing:
            for item in sorted(slot_dir.iterdir()):
                target = dest / item.name
                if target.exists():
                    if item.is_dir() and target.is_dir():
                        shutil.rmtree(target)
                    elif item.is_file() or item.is_symlink():
                        target.unlink()
                shutil.move(str(item), str(target))
            _cleanup_remnant_dir(slot_dir)
        else:
            shutil.move(str(slot_dir), str(dest))
    except Exception:
        if slot_dir.exists():
            set_slot_state(slot_dir, prior_state)
        raise

    relocate_claude_projects(slot_dir, dest)
    if slot_dir.exists():
        if not _cleanup_remnant_dir(slot_dir):
            print(f"WARN=remnant_dir_persists path={slot_dir}")
    if escaped and cwd_offset is not None:
        relocated = dest / cwd_offset
        if relocated.exists():
            os.chdir(relocated)
            print(f"CWD_RELOCATED={relocated}")
        else:
            print(f"CWD_RELOCATED={dest}")
    if swept:
        print(f"CLAUDE_PROJECTS_SWEPT={swept}")

    _transition(
        dest, "archived",
        family_root=family_root, slot_number=slot_num,
        resolution=resolution,
        archived_from=str(slot_dir),
        archived_to=str(dest),
        force=True,
    )

    print(f"ARCHIVED={slot_num}")


def process_archive_requests(family_root: Path) -> list[dict]:
    """Find slots with .archive-requested markers and archive if no active sessions."""
    from slot_claude import find_active_sessions, check_occupant_pid
    results = []
    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        slots_dir = family_root / dir_name
        if not slots_dir.is_dir():
            continue
        for entry in sorted(slots_dir.iterdir()):
            if not entry.is_dir() or entry.name == "attic":
                continue
            marker = entry / ".archive-requested"
            if not marker.exists():
                continue
            try:
                slot_num = int(entry.name)
            except ValueError:
                continue
            alive, pid = check_occupant_pid(entry)
            if alive:
                results.append({"slot": slot_num, "action": "deferred",
                                "reason": f"occupant PID {pid} still alive"})
                continue
            active = find_active_sessions(entry)
            if active:
                pids = [str(p) for p, _, _ in active]
                results.append({"slot": slot_num, "action": "deferred",
                                "reason": f"active sessions: {','.join(pids)}"})
                continue
            marker.unlink(missing_ok=True)
            archive_slot(family_root, slot_num, force=True)
            results.append({"slot": slot_num, "action": "archived"})
    return results


def restore_slot(family_root: Path, slot_num: int) -> None:
    attic_dir = family_root / SLOT_DIR_NAME / "attic" / str(slot_num)
    if not attic_dir.exists():
        legacy = family_root / LEGACY_SLOT_DIR_NAME / "attic" / str(slot_num)
        if legacy.exists():
            attic_dir = legacy
        else:
            print(f"ERROR=slot_not_in_attic slot={slot_num}")
            sys.exit(1)
    dest = attic_dir.parent.parent / str(slot_num)
    if dest.exists():
        print(f"ERROR=active_slot_exists slot={slot_num}")
        print(f"ERROR_DETAIL=slots/{slot_num}/ already exists — cannot restore on top of it")
        sys.exit(1)
    slot_file = attic_dir / ".slot"
    if not slot_file.exists():
        print(f"WARN=no_slot_file slot={slot_num}")
    copied = relocate_claude_projects(attic_dir, dest)
    shutil.move(str(attic_dir), str(dest))
    if attic_dir.exists():
        if not _cleanup_remnant_dir(attic_dir):
            print(f"WARN=remnant_dir_persists path={attic_dir}")
    if copied:
        print(f"CLAUDE_PROJECTS_COPIED={copied}")
    (dest / ".m2").mkdir(exist_ok=True)  # purged at archive; the slot's Maven settings point here
    _transition(
        dest, "active",
        family_root=family_root, slot_number=slot_num,
        force=True,  # restoring from archived
    )
    print(f"RESTORED={slot_num}")


def remove_slot(family_root: Path, slot_num: int, force: bool = False,
                 resolution: str | None = None) -> None:
    """Archive a slot to attic.  Always archives — never deletes.

    --force / --force-delete both skip the .landed check but still
    archive to slots/attic/<N>/.  There is no permanent deletion path.
    """
    slot_dir = _resolve_slot_dir_for_number(family_root, slot_num)
    if not slot_dir.exists():
        print(f"ERROR=slot_not_found slot={slot_num}")
        sys.exit(1)

    _converge_state(slot_dir, family_root, slot_num)

    if not force and not is_slot_landed(slot_dir):
        print(f"ERROR=slot_not_landed slot={slot_num}")
        print("ERROR_DETAIL=slot has no .landed marker — work may be in progress")
        print("HINT=run work-end first, or pass --force to archive without .landed check")
        sys.exit(1)

    _teardown_isx(slot_dir)

    escaped, cwd_offset = _escape_slot_cwd(slot_dir, family_root)
    if escaped:
        print(f"CWD_ESCAPED={family_root}")

    attic_dir = slot_dir.parent / "attic"
    attic_dir.mkdir(exist_ok=True)
    dest = attic_dir / str(slot_num)
    if dest.exists():
        print(f"ERROR=attic_slot_exists slot={slot_num}")
        print(f"ERROR_DETAIL=attic/{slot_num}/ already exists — would nest. Remove the existing attic entry first.")
        sys.exit(1)
    swept = sweep_orphaned_claude_projects(family_root)

    prior_state = _current_state(slot_dir)
    set_slot_state(slot_dir, "archived")

    try:
        shutil.move(str(slot_dir), str(dest))
    except Exception:
        if slot_dir.exists():
            set_slot_state(slot_dir, prior_state)
        raise

    relocate_claude_projects(slot_dir, dest)
    if slot_dir.exists():
        if not _cleanup_remnant_dir(slot_dir):
            print(f"WARN=remnant_dir_persists path={slot_dir}")
    if escaped and cwd_offset is not None:
        relocated = dest / cwd_offset
        if relocated.exists():
            os.chdir(relocated)
            print(f"CWD_RELOCATED={relocated}")
        else:
            print(f"CWD_RELOCATED={dest}")
    if swept:
        print(f"CLAUDE_PROJECTS_SWEPT={swept}")
    _transition(
        dest, "archived",
        family_root=family_root, slot_number=slot_num,
        resolution=resolution,
        archived_from=str(slot_dir),
        archived_to=str(dest),
        force=True,
    )
    print(f"ARCHIVED={slot_num}")


def migrate_remotes(family_root: Path) -> int:
    """Give every active slot clone that lacks one a `local` remote naming its canonical
    repo, and no GitHub remote. Returns how many clones were changed.

    For clones made before slots carried `local`. Clones that still hold GitHub
    remotes alongside `local` are handled by `scripts/slot_backup_setup.py detach`,
    which backs their branches up into canonical first."""
    migrated = 0
    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        slots_dir = family_root / dir_name
        if not slots_dir.exists():
            continue
        for d in sorted(slots_dir.iterdir()):
            if not d.is_dir() or not d.name.isdigit():
                continue
            for repo_name in get_all_slot_repos(d):
                clone = d / repo_name
                rc, _, _ = run_cmd(
                    ["git", "-C", str(clone), "remote", "get-url", "local"])
                if rc == 0:
                    continue
                canonical = resolve_canonical_repo(clone)
                configure_slot_remotes(clone, canonical)
                rc, _, _ = run_cmd(
                    ["git", "-C", str(clone), "remote", "get-url", "local"])
                if rc == 0:
                    migrated += 1
                configure_update_instead(canonical)
    print(f"MIGRATED={migrated}")
    return migrated


