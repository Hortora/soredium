"""Slot lifecycle orchestrators.

create_slot, add_repo, merge_slot, archive_slot, remove_slot, restore_slot.
"""

import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))
try:
    import worklog as _wl
except ImportError:
    _wl = None

from slot_core import (
    SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME,
    SlotCreationError, run_cmd,
    _resolve_slot_dir_for_number, _get_family_repo_names,
    resolve_original_repo, _get_clone_origin,
    get_slot_repos, get_all_slot_repos,
    _cleanup_remnant_dir, _escape_slot_cwd, _has_unmerged_content,
)
from slot_metadata import (
    parse_slot_md, write_slot_md,
    is_slot_landed, verify_landed_shas, _fix_stale_checkboxes,
)
from slot_maven import setup_slot_repo
from slot_isx import (
    _check_isx_available, _truncate_instance_name,
    _teardown_isx, _wire_isx_remotes,
)
from slot_claude import (
    relocate_claude_projects, sweep_orphaned_claude_projects,
)
from slot_git import (
    configure_slot_remotes, configure_update_instead,
    install_post_commit_hook, sync_main,
    _symlink_gitignored_assets, _exclude_symlinks,
    _repack_broken_alternates, ensure_clone_layout,
)
from slot_workspace import (
    validate_slot_wksp, resolve_workspace_source, discover_workspace,
    _unignore_subdir, repoint_wksp, create_proj_symlink, replicate_claude_md,
)
from slot_query import find_slot_by_branch


def _build_epic_plan(branch: str, issue_repo: str, cover_list: list[str],
                     date: str) -> str | None:
    """Build a .plan from the epic's child issue list. Fetches titles from GitHub."""
    from plan_manager import QueueItem, build_plan_content
    items: list[QueueItem] = []
    for num_str in cover_list:
        try:
            num = int(num_str)
        except ValueError:
            continue
        rc, title_out, _ = run_cmd([
            "gh", "issue", "view", str(num), "--repo", issue_repo,
            "--json", "title", "--jq", ".title",
        ])
        title = title_out.strip() if rc == 0 and title_out.strip() else f"Issue #{num}"
        items.append(QueueItem(issue_number=num, title=title, repo=issue_repo))
    if not items:
        return None
    items[0].active = True
    return build_plan_content(branch, items, date)






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
            if reusable is None:
                slot_num = _wl.reserve_slot_number(conn, str(family_root))
            else:
                for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
                    debris = family_root / dir_name / str(slot_num)
                    if debris.exists():
                        shutil.rmtree(str(debris), ignore_errors=True)
                for other_num in others:
                    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
                        debris = family_root / dir_name / str(other_num)
                        if debris.exists():
                            shutil.rmtree(str(debris), ignore_errors=True)
                    _wl.fail_slot(conn, other_num, str(family_root))
                print(f"REUSED_PENDING={slot_num}")
                return slot_num
        else:
            slot_num = _wl.reserve_slot_number(conn, str(family_root))
    finally:
        conn.close()
    return slot_num


def create_slot(family_root: Path, repos: list[str], branch: str,
                issue: str, issue_repo: str, covers: str,
                context: str,
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

    try:
        slot_dir.mkdir()
        m2_dir = slot_dir / ".m2"
        m2_dir.mkdir()

        for repo_name in repos:
            repo_path = family_root / repo_name
            if not repo_path.is_dir():
                raise SlotCreationError(f"repo_not_found repo={repo_name}")

            sync_main(str(repo_path))

            clone_dest = slot_dir / repo_name
            rc, _, stderr = run_cmd([
                "git", "clone", "--shared", "--branch", "main",
                str(repo_path), str(clone_dest),
            ])
            if rc != 0:
                raise SlotCreationError(f"clone_failed repo={repo_name} stderr={stderr.strip()}")
            rc, _, _ = run_cmd(["git", "-C", str(clone_dest), "checkout", "-b", branch])
            if rc != 0:
                raise SlotCreationError(f"branch_create_failed repo={repo_name}")
            _exclude_symlinks(clone_dest)
            _symlink_gitignored_assets(repo_path, clone_dest)
            configure_slot_remotes(clone_dest, repo_path)
            configure_update_instead(repo_path)
            install_post_commit_hook(clone_dest)

            gi_changed = setup_slot_repo(clone_dest, m2_dir)
            if gi_changed:
                run_cmd(["git", "-C", str(clone_dest), "add", ".gitignore"])
                run_cmd(["git", "-C", str(clone_dest), "commit", "-m",
                         "chore: add slot infrastructure to .gitignore"])

            ws_info = resolve_workspace_source(repo_path)
            if not ws_info:
                ws_info = discover_workspace(repo_path)
                if ws_info:
                    print(f"DISCOVERED_WORKSPACE={ws_info[1]} repo={repo_name}")
            if ws_info:
                ws_source, ws_name = ws_info
                ws_slot_dir = slot_dir / ws_name

                if ws_slot_dir.exists():
                    raise SlotCreationError(
                        f"workspace_name_collision ws={ws_name} repo={repo_name}: "
                        f"Workspace clone name '{ws_name}' already exists in slot.")

                sync_main(str(ws_source))
                rc, _, stderr = run_cmd([
                    "git", "clone", "--shared", "--branch", "main",
                    str(ws_source), str(ws_slot_dir),
                ])
                if rc != 0:
                    raise SlotCreationError(f"workspace_clone_failed ws={ws_name} stderr={stderr.strip()}")
                rc, _, _ = run_cmd(["git", "-C", str(ws_slot_dir), "checkout", "-b", branch])
                if rc != 0:
                    raise SlotCreationError(f"workspace_branch_failed ws={ws_name}")
                _exclude_symlinks(ws_slot_dir)
                configure_slot_remotes(ws_slot_dir, ws_source)
                configure_update_instead(ws_source)
                install_post_commit_hook(ws_slot_dir)
                (ws_slot_dir / ".workspace").touch()

                repoint_wksp(clone_dest, ws_slot_dir)
                create_proj_symlink(ws_slot_dir, clone_dest)
                replicate_claude_md(repo_path, ws_slot_dir, clone_dest)

        primary_repo = repos[0]
        primary_wksp = slot_dir / primary_repo / "wksp"
        if not primary_wksp.is_symlink():
            raise SlotCreationError(
                f"primary_no_workspace repo={primary_repo}: "
                f"primary repo has no workspace clone — .plan cannot be scaffolded. "
                f"Add a wksp symlink to {family_root / primary_repo} pointing to its workspace.")
        if primary_wksp.is_symlink():
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
                cover_list = [c.strip() for c in covers.split(",") if c.strip()]
                if len(cover_list) > 1:
                    plan_content = _build_epic_plan(
                        branch, issue_repo, cover_list,
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

        write_slot_md(slot_dir, slot_num, repos, branch, issue,
                      issue_repo, covers, context,
                      isolation_type="isx" if isx else "",
                      isx_instance=instance_name if isx else "",
                      isx_template=isx_template if isx else "")

        if isx:
            _wire_isx_remotes(slot_dir, repos, instance_name)

        conn = _wl.connect()
        try:
            repo_paths = [str(family_root / r) for r in repos]
            _wl.confirm_slot_create(
                conn, slot_num, str(family_root),
                repos=repo_paths, branch=branch,
                issue_number=int(issue) if issue else 0,
                issue_repo=issue_repo, covers=covers,
            )
        finally:
            conn.close()

        wksp_failures = validate_slot_wksp(slot_dir)
        if wksp_failures:
            raise SlotCreationError(
                "wksp_validation_failed: " + "; ".join(wksp_failures))
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

    rc, _, stderr = run_cmd([
        "git", "clone", "--shared", "--branch", "main",
        str(repo_path), str(clone_dest),
    ])
    if rc != 0:
        print(f"ERROR=clone_failed repo={repo_name} stderr={stderr.strip()}")
        sys.exit(1)

    rc, _, _ = run_cmd(["git", "-C", str(clone_dest), "checkout", "-b", branch])
    if rc != 0:
        print(f"ERROR=branch_create_failed repo={repo_name}")
        sys.exit(1)

    _exclude_symlinks(clone_dest)
    _symlink_gitignored_assets(repo_path, clone_dest)
    install_post_commit_hook(clone_dest)
    gi_changed = setup_slot_repo(clone_dest, m2_dir)
    if gi_changed:
        run_cmd(["git", "-C", str(clone_dest), "add", ".gitignore"])
        run_cmd(["git", "-C", str(clone_dest), "commit", "-m",
                 "chore: add slot infrastructure to .gitignore"])

    slot_info = parse_slot_md(slot_dir)
    if slot_info.get("isolation_type") == "isx":
        instance = slot_info.get("isx_instance", "")
        if instance:
            _wire_isx_remotes(slot_dir, [repo_name], instance)

    ws_info = resolve_workspace_source(repo_path)
    if not ws_info:
        ws_info = discover_workspace(repo_path)
        if ws_info:
            print(f"DISCOVERED_WORKSPACE={ws_info[1]} repo={repo_name}")
    if ws_info:
        ws_source, ws_name = ws_info
        family_repo_names = _get_family_repo_names(family_root)
        if ws_name in family_repo_names:
            ws_name = f"work-{ws_source.name}"
        ws_slot_dir = slot_dir / ws_name
        if ws_slot_dir.exists():
            existing_origin = _get_clone_origin(ws_slot_dir)
            if existing_origin and str(ws_source) not in existing_origin:
                ws_name = f"work-{ws_source.name}"
                ws_slot_dir = slot_dir / ws_name
        if not ws_slot_dir.exists():
            sync_main(str(ws_source))
            rc, _, _ = run_cmd([
                "git", "clone", "--shared", "--branch", "main",
                str(ws_source), str(ws_slot_dir),
            ])
            if rc == 0:
                run_cmd(["git", "-C", str(ws_slot_dir), "checkout", "-b", branch])
                _exclude_symlinks(ws_slot_dir)
                configure_slot_remotes(ws_slot_dir, ws_source)
                configure_update_instead(ws_source)
                install_post_commit_hook(ws_slot_dir)
                (ws_slot_dir / ".workspace").touch()

        wksp_target = repo_path / "wksp"
        if wksp_target.is_symlink():
            orig_target = wksp_target.resolve()
            try:
                rel_subdir = orig_target.relative_to(ws_source)
                ws_subdir = ws_slot_dir / rel_subdir
            except ValueError:
                ws_subdir = ws_slot_dir
            ws_subdir.mkdir(parents=True, exist_ok=True)
            if rel_subdir != Path("."):
                _unignore_subdir(ws_slot_dir, str(rel_subdir.parts[0]))
            repoint_wksp(clone_dest, ws_subdir)
            create_proj_symlink(ws_subdir, clone_dest)
            replicate_claude_md(repo_path, ws_subdir, clone_dest)

    configure_slot_remotes(clone_dest, repo_path)
    configure_update_instead(repo_path)

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

    slot_info = parse_slot_md(slot_dir)
    repos = slot_info.get("repos", [])
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
    slot_dir = _resolve_slot_dir_for_number(family_root, slot_num)
    if not slot_dir.exists():
        print(f"ERROR=slot_not_found slot={slot_num}")
        return 1
    ensure_clone_layout(slot_dir)
    if not (slot_dir / ".phase-a-complete").exists():
        print(f"ERROR=not_ready slot={slot_num}")
        return 1
    if (slot_dir / ".landed").exists():
        print(f"ERROR=already_landed slot={slot_num}")
        return 1

    slot_info = parse_slot_md(slot_dir)
    _slot_is_epic = slot_info.get("is_epic", False)
    if _slot_is_epic:
        try:
            from plan_manager import detect as _plan_detect
            plan_info = _plan_detect(slot_dir)
            if plan_info:
                _done = plan_info.get("completed_count", 0)
                _total = plan_info.get("total_count", 0)
                print(f"EPIC_STATUS={_done} completed, {_total - _done} remaining")
        except Exception:
            pass

    branch = ""
    for line in (slot_dir / ".phase-a-complete").read_text().splitlines():
        if line.startswith("branch="):
            branch = line.split("=", 1)[1]
    if not branch:
        print("ERROR=no_branch_in_marker")
        return 1

    # Build batch and land via shared flow
    from land_flow import build_slot_batch, land_batch

    descriptors = build_slot_batch(slot_dir, branch=branch)
    if not descriptors:
        print("ERROR=no_repos_in_slot")
        print("HINT=no repos have the feature branch — check slot setup")
        return 1

    progress_file = slot_dir / ".execute-progress"
    result = land_batch(descriptors, branch, progress_file)

    # Collect landed repos (may be partial if some repos failed)
    project_repos = [d.repo_path.name for d in descriptors if not d.is_workspace]
    landed_shas = {s.repo_path.name: s.landed_sha for s in result.repos if s.landed_sha}
    # github_push_failed with pushed=True is non-blocking — local push succeeded
    failed_repos = [
        s.repo_path.name for s in result.repos
        if s.error and not (s.error == "github_push_failed" and s.pushed)
    ]
    stamped_repos = [s.repo_path.name for s in result.repos if s.stamped]
    shas_str = ",".join(f"{r}:{s}" for r, s in landed_shas.items())

    # Write .landed marker when at least one repo landed successfully.
    # The marker records which repos succeeded and which failed — the
    # verify step uses this to report partial success accurately.
    if landed_shas:
        marker_lines = [
            f"branch={branch}",
            f"repos={','.join(project_repos)}",
            f"landed_shas={shas_str}",
            f"stamped={','.join(stamped_repos)}",
            f"timestamp={datetime.datetime.now(datetime.timezone.utc).isoformat()}",
        ]
        if failed_repos:
            marker_lines.append(f"failed={','.join(failed_repos)}")
        (slot_dir / ".landed").write_text("\n".join(marker_lines) + "\n")
    else:
        # Nothing landed at all — hard failure
        for s in result.repos:
            if s.error:
                print(f"ERROR={s.error} repo={s.repo_path.name}")
        print("ERROR=no_repos_landed")
        return 1

    if _wl:
        try:
            _conn = _wl.connect()
            _wl.record_slot_merge(
                _conn, slot_num, str(family_root),
                landed_shas=landed_shas,
            )
            _conn.close()
        except Exception:
            pass

    if _slot_is_epic:
        epic_num = int(slot_info.get("issue", "0"))
        epic_repo = slot_info.get("issue_repo", "")
        covers_str = slot_info.get("covers", "")
        completed = [int(x) for x in covers_str.split(",") if x.strip()]
        if epic_num and epic_repo and completed:
            try:
                from plan_manager import _tick_github_checkboxes
                ok = _tick_github_checkboxes(epic_repo, epic_num, completed)
                if not ok:
                    print("WARN=epic_tick_failed")
            except (ImportError, Exception):
                print("WARN=epic_tick_skipped")

    # Report
    for s in result.repos:
        icon = "OK" if not s.error else "FAIL"
        stamped_flag = " STAMPED" if s.stamped else ""
        print(f"RESULT={s.repo_path.name} STATUS={'ok' if not s.error else s.error} SHA={s.landed_sha}{stamped_flag} ICON={icon}")
    ok_count = sum(1 for s in result.repos if not s.error)
    fail_count = len(failed_repos)
    print(f"SUMMARY=ok:{ok_count} fail:{fail_count}")
    print(f"LANDED_SHAS={shas_str}")
    if failed_repos:
        print(f"WARN=partial_land failed_repos={','.join(failed_repos)}")
        return 1
    return 0


def archive_slot(family_root: Path, slot_num: int, force: bool = False,
                  resolution: str | None = None) -> None:
    slot_dir = _resolve_slot_dir_for_number(family_root, slot_num)
    if not slot_dir.exists():
        print(f"ERROR=slot_not_found slot={slot_num}")
        sys.exit(1)
    ensure_clone_layout(slot_dir)
    unmerged = _has_unmerged_content(slot_dir)
    if unmerged:
        print(f"ERROR=unmerged_content slot={slot_num}")
        print(f"ERROR_DETAIL=repos with unmerged branch content: {', '.join(unmerged)}")
        print("HINT=land the branch content first, or manually verify it's already on main under different SHAs")
        sys.exit(1)
    if not force and not is_slot_landed(slot_dir):
        print(f"ERROR=slot_not_landed slot={slot_num}")
        print("ERROR_DETAIL=slot has no .landed marker — work may be in progress")
        print("HINT=pass --force to override, or run merge-slot first")
        sys.exit(1)
    if not force:
        verified, failures = verify_landed_shas(slot_dir, family_root)
        if not verified:
            print(f"ERROR=sha_not_on_main slot={slot_num}")
            for f in failures:
                print(f"ERROR_DETAIL={f}")
            print("HINT=pass --force to override, or investigate the failed merge")
            sys.exit(1)
    has_promotion_stamp = any(
        (sub / ".artifacts-promoted").exists() or (sub / "design" / ".artifacts-promoted").exists()
        for sub in slot_dir.iterdir()
        if sub.is_dir()
    ) or (slot_dir / ".artifacts-promoted").exists() or (slot_dir / "design" / ".artifacts-promoted").exists()
    if not has_promotion_stamp:
        print(f"WARN=artifacts_not_promoted slot={slot_num}")

    slot_info = parse_slot_md(slot_dir)
    if slot_info.get("is_epic"):
        covers_str = slot_info.get("covers", "")
        completed = [int(x) for x in covers_str.split(",") if x.strip()]
        if completed:
            fixed = _fix_stale_checkboxes(slot_dir / ".slot", completed)
            if fixed:
                print(f"CHECKBOXES_FIXED={fixed}")
                print(f"WARN=stale_checkboxes issues={','.join(str(c) for c in completed)}")
            epic_num = int(slot_info.get("issue", "0"))
            epic_repo = slot_info.get("issue_repo", "")
            if epic_num and epic_repo:
                try:
                    from plan_manager import _tick_github_checkboxes
                    ok = _tick_github_checkboxes(epic_repo, epic_num, completed)
                    if not ok:
                        print("WARN=github_unreachable_for_checkbox_verify")
                except (ImportError, Exception):
                    print("WARN=github_unreachable_for_checkbox_verify")

    repacked = _repack_broken_alternates(slot_dir, family_root)
    if repacked:
        print(f"ALTERNATES_REPACKED={repacked}")

    _teardown_isx(slot_dir)

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

    if _wl:
        try:
            _conn = _wl.connect()
            _wl.record_slot_archiving(
                _conn, slot_num, str(family_root),
                pid=os.getppid(),
                archived_from=str(slot_dir),
                archived_to=str(dest),
                resolution=resolution,
            )
            _conn.close()
        except Exception:
            pass

    print(f"ARCHIVING={slot_num}")
    print(f"PID={os.getppid()}")


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
    ensure_clone_layout(dest)
    if _wl:
        try:
            _conn = _wl.connect()
            _wl.record_slot_create(
                _conn, slot_num, str(family_root),
                branch="restored", repos="", issue=0,
            )
            _conn.close()
        except Exception:
            pass
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
    shutil.move(str(slot_dir), str(dest))
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
    if _wl:
        try:
            _conn = _wl.connect()
            _wl.record_slot_archiving(
                _conn, slot_num, str(family_root),
                pid=os.getppid(),
                archived_from=str(slot_dir),
                archived_to=str(dest),
                resolution=resolution,
            )
            _conn.close()
        except Exception:
            pass
    print(f"ARCHIVING={slot_num}")
    print(f"PID={os.getppid()}")


def migrate_remotes(family_root: Path) -> int:
    """Add GitHub remotes + updateInstead to all active (non-archived) slots."""
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
                original = resolve_original_repo(clone)
                result = configure_slot_remotes(clone, original)
                if result["origin"]:
                    migrated += 1
                configure_update_instead(original)
    print(f"MIGRATED={migrated}")
    return migrated


