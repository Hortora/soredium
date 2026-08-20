#!/usr/bin/env python3
"""
slot_manager.py — Clone-based slot operations for multi-repo families

Subcommands:
  create-slot <family-root> repos=<csv> branch=<name> issue=<N> issue-repo=<o/r> [covers=<csv>] [context=<text>]
  list-slots <family-root> [--all]
  remove-slot <family-root> slot=<N> [--force]
  scan-ready <family-root>
  merge-slot <family-root> slot=<N>
  archive-slot <family-root> slot=<N> [--force]
  restore-slot <family-root> slot=<N>
  check-cross-deps <family-root> slot=<N>
  sync-isx [<slot-dir>] [slot=<N>]
  migrate-remotes <family-root>

Note: remove-slot always archives to slots/attic/. --force skips the .landed check.

All commands output KEY=VALUE pairs on stdout for easy parsing.
"""

import datetime
import json
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

_work_end = Path(__file__).parent.parent / "work-end"
if _work_end.exists():
    sys.path.insert(0, str(_work_end))
try:
    from common import detect_topology as _detect_topology
except ImportError:
    _detect_topology = None


_IDE_ARTIFACTS = {".idea", ".run", ".settings", ".project", ".classpath", ".vscode"}

_REGENERABLE_DIRS = {
    "node_modules", ".gradle", "build", "dist", "target", "out",
    ".next", ".nuxt", ".cache", ".parcel-cache", ".turbo",
    *_IDE_ARTIFACTS,
}

SLOT_DIR_NAME = "slots"
LEGACY_SLOT_DIR_NAME = "worktrees"


def _resolve_slots_dir(family_root: Path) -> Path:
    """Return the slots directory, preferring slots/ over legacy worktrees/."""
    new = family_root / SLOT_DIR_NAME
    old = family_root / LEGACY_SLOT_DIR_NAME
    if new.exists():
        return new
    if old.exists():
        return old
    return new


def _resolve_slot_dir_for_number(family_root: Path, slot_num: int) -> Path:
    """Find a specific slot by number, checking slots/ then worktrees/."""
    for name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        candidate = family_root / name / str(slot_num)
        if candidate.exists():
            return candidate
    return family_root / SLOT_DIR_NAME / str(slot_num)


def _get_family_repo_names(family_root: Path) -> set[str]:
    """Return names of all top-level git directories in the family root."""
    excluded = {"slots", "worktrees", "attic", ".m2"}
    names: set[str] = set()
    if not family_root.is_dir():
        return names
    for entry in family_root.iterdir():
        if not entry.is_dir() or entry.name in excluded or entry.name.startswith("."):
            continue
        if (entry / ".git").exists() or (entry / ".git").is_file():
            names.add(entry.name)
    return names


def validate_slot_wksp(slot_dir: Path, repo_names: list[str] | None = None) -> list[str]:
    """Validate wksp/ symlinks in slot repo clones.
    Returns list of failure descriptions (empty = all OK)."""
    failures: list[str] = []
    names = repo_names if repo_names is not None else get_slot_repos(slot_dir)
    for repo_name in names:
        clone = slot_dir / repo_name
        if not clone.is_dir() or not (clone / ".git").exists():
            continue
        original = resolve_original_repo(clone)
        original_wksp = original / "wksp"
        if not original_wksp.is_symlink():
            continue
        clone_wksp = clone / "wksp"
        if not clone_wksp.is_symlink():
            failures.append(f"{repo_name}: wksp/ symlink missing")
        elif not clone_wksp.resolve().exists():
            failures.append(f"{repo_name}: wksp/ symlink dangling -> {clone_wksp.resolve()}")
    return failures


def is_slot_path(path: str) -> bool:
    """Check if a path is inside a slot directory (not a git/Claude Code worktree)."""
    if "/slots/" in path:
        return True
    if "/worktrees/" in path and "/.claude/worktrees/" not in path and "/.worktrees/" not in path:
        return True
    return False


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
        items.append(QueueItem(issue_number=num, title=title))
    if not items:
        return None
    items[0].active = True
    return build_plan_content(branch, items, date)


def _read_promotion_stamp(slot_dir: Path) -> tuple[list[str], list[str], str]:
    """Read artifact promotion data from .artifacts-promoted stamps in the slot.
    Returns (promoted_files, published_blogs, publish_dest)."""
    promoted: list[str] = []
    published: list[str] = []
    pub_dest = ""

    for sub in slot_dir.iterdir():
        if not sub.is_dir():
            continue
        stamp = sub / ".artifacts-promoted"
        if not stamp.exists():
            stamp = sub / "design" / ".artifacts-promoted"
        if not stamp.exists():
            continue
        stamp_data: dict[str, str] = {}
        for line in stamp.read_text().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                stamp_data[k.strip()] = v.strip()

        ws_count = int(stamp_data.get("workspace_promoted", "0"))
        proj_count = int(stamp_data.get("project_promoted", "0"))
        blog_count = int(stamp_data.get("blog_published", "0"))
        plans_count = int(stamp_data.get("plans_archived", "0"))

        if ws_count > 0:
            promoted.append(f"workspace:{ws_count}")
        if proj_count > 0:
            promoted.append(f"project:{proj_count}")
        if plans_count > 0:
            promoted.append(f"plans:{plans_count}")
        if blog_count > 0:
            published.append(f"blog:{blog_count}")

    return promoted, published, pub_dest


def _cleanup_remnant_dir(path: Path) -> bool:
    """Remove IDE artifacts and empty directories left after git operations.
    Recurses into subdirectories. Returns True if path no longer exists."""
    if not path.exists():
        return True
    for item in list(path.iterdir()):
        if item.is_dir() and item.name in _IDE_ARTIFACTS:
            shutil.rmtree(str(item), ignore_errors=True)
        elif item.is_dir():
            _cleanup_remnant_dir(item)
    try:
        path.rmdir()
        return True
    except OSError:
        return False


def _escape_slot_cwd(slot_dir: Path, escape_to: Path) -> tuple[bool, Path | None]:
    """If CWD is inside slot_dir, chdir to escape_to.

    Returns (escaped, relative_offset) where relative_offset is the path
    from slot_dir to the original CWD (e.g. Path('platform') if CWD was
    slots/98/platform). Callers use this to compute the equivalent path
    in the archive destination.
    """
    try:
        cwd = Path.cwd().resolve()
        slot_resolved = slot_dir.resolve()
        if cwd == slot_resolved or slot_resolved in cwd.parents:
            relative = cwd.relative_to(slot_resolved)
            os.chdir(escape_to)
            return True, relative
    except OSError:
        pass
    return False, None


def run_cmd(args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    result = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    return result.returncode, result.stdout, result.stderr


def _check_isx_available() -> bool:
    return shutil.which("isx") is not None


def _truncate_instance_name(name: str, max_len: int = 63) -> str:
    if len(name) <= max_len:
        return name
    return name[:max_len].rstrip("-")


def _teardown_isx(slot_dir: Path) -> None:
    info = parse_slot_md(slot_dir)
    if info.get("isolation_type") != "isx":
        return
    instance = info.get("isx_instance", "")
    if not instance:
        return
    rc, _, stderr = run_cmd(["isx", "destroy", instance])
    if rc != 0:
        print(f"WARN=isx_destroy_failed instance={instance} err={stderr.strip()}")


def _wire_isx_remotes(slot_dir: Path, repos: list[str], instance: str) -> None:
    for repo_name in repos:
        clone_path = slot_dir / repo_name
        if not clone_path.is_dir():
            continue
        remote_url = f"isx://{instance}/home/agentuser/{repo_name}"
        run_cmd(["git", "-C", str(clone_path), "remote", "add", "isx", remote_url])


def sync_isx(slot_dir: Path) -> int:
    info = parse_slot_md(slot_dir)
    if info.get("isolation_type") != "isx":
        print("ERROR=not_isx_slot")
        print("ERROR_DETAIL=This slot has no ISX isolation.")
        return 1

    branch = info.get("branch", "")
    repos = get_slot_repos(slot_dir)

    for repo_name in repos:
        clone_path = slot_dir / repo_name
        if not clone_path.is_dir():
            continue
        rc, _, _ = run_cmd(["git", "-C", str(clone_path), "remote", "get-url", "isx"])
        if rc != 0:
            print(f"WARN=no_isx_remote repo={repo_name}")
            continue
        rc, _, stderr = run_cmd(["git", "-C", str(clone_path), "fetch", "isx", branch])
        if rc != 0:
            print(f"WARN=fetch_failed repo={repo_name} err={stderr.strip()}")
            continue
        rc, _, stderr = run_cmd(["git", "-C", str(clone_path), "merge", "--ff-only", f"isx/{branch}"])
        if rc != 0:
            print(f"ERROR=merge_failed repo={repo_name} err={stderr.strip()}")
            print("ERROR_DETAIL=Histories have diverged. Resolve manually or reset.")
            return 1
        print(f"SYNCED={repo_name}")

    return 0


def allocate_slot_number(family_root: Path) -> int:
    """Reserve next slot number via DB. Hard fail if DB unavailable."""
    if _wl is None:
        print("ERROR=worklog_unavailable")
        print("ERROR_DETAIL=worklog module required for slot numbering — "
              "ensure scripts/worklog.py is importable")
        sys.exit(1)
    conn = _wl.connect()
    try:
        slot_num = _wl.reserve_slot_number(conn, str(family_root))
    finally:
        conn.close()
    return slot_num


def _get_clone_origin(clone_path: Path) -> str | None:
    """Get the origin URL of a git clone, or None if not a git repo."""
    rc, stdout, _ = run_cmd(["git", "-C", str(clone_path), "remote", "get-url", "origin"])
    return stdout.strip() if rc == 0 else None


def resolve_workspace_source(repo_path: Path) -> tuple[Path, str] | None:
    wksp = repo_path / "wksp"
    if not wksp.is_symlink():
        return None
    target = wksp.resolve()
    if not target.is_dir():
        return None

    rc, stdout, _ = run_cmd(["git", "-C", str(target), "rev-parse", "--show-toplevel"])
    if rc != 0:
        return None
    ws_root = Path(stdout.strip())

    rc, url_out, _ = run_cmd(["git", "-C", str(ws_root), "remote", "get-url", "origin"])
    if rc == 0 and url_out.strip():
        name = Path(url_out.strip().rstrip("/")).stem
        return ws_root, name

    parent_name = ws_root.parent.name
    return ws_root, f"wsp-{parent_name}-{ws_root.name}"


def _write_slot_settings(slot_dir: Path) -> Path:
    """Generate a slot-specific settings.xml that adds the global ~/.m2/repository
    as a file:// fallback remote. This lets Maven resolve artifacts from the host
    cache without polluting it — writes go to the slot .m2, reads fall through."""
    settings_path = slot_dir / "slot-settings.xml"
    if settings_path.exists():
        return settings_path
    global_m2 = Path.home() / ".m2" / "repository"
    settings_path.write_text(f"""\
<settings>
  <profiles>
    <profile>
      <id>slot-host-fallback</id>
      <repositories>
        <repository>
          <id>host-m2</id>
          <url>file://{global_m2}</url>
          <releases><enabled>true</enabled></releases>
          <snapshots><enabled>true</enabled><updatePolicy>always</updatePolicy></snapshots>
        </repository>
      </repositories>
      <pluginRepositories>
        <pluginRepository>
          <id>host-m2-plugins</id>
          <url>file://{global_m2}</url>
          <releases><enabled>true</enabled></releases>
          <snapshots><enabled>true</enabled><updatePolicy>always</updatePolicy></snapshots>
        </pluginRepository>
      </pluginRepositories>
    </profile>
  </profiles>
  <activeProfiles>
    <activeProfile>slot-host-fallback</activeProfile>
  </activeProfiles>
</settings>
""")
    return settings_path


def setup_slot_repo(repo_worktree: Path, m2_path: Path) -> bool:
    slot_dir = m2_path.parent
    slot_settings = _write_slot_settings(slot_dir)

    mvn_dir = repo_worktree / ".mvn"
    mvn_dir.mkdir(parents=True, exist_ok=True)

    # Copy slot-settings.xml into .mvn/ so maven.config can use a short relative
    # path with --settings= (equals form).  Maven 3.9.x mangles "-s <path>" in
    # .mvn/maven.config by prepending basedir with a space separator — see
    # GE-20260805-ffef3b.
    local_settings = mvn_dir / "slot-settings.xml"
    if not local_settings.exists():
        shutil.copy2(slot_settings, local_settings)

    config_file = mvn_dir / "maven.config"
    repo_line = f"-Dmaven.repo.local={m2_path}"
    settings_line = "--settings=.mvn/slot-settings.xml"
    if config_file.exists():
        content = config_file.read_text()
        # Fix legacy "-s <path>" format (GE-20260805-ffef3b)
        lines = content.splitlines()
        fixed = [settings_line if l.strip().startswith("-s ") else l for l in lines]
        content = "\n".join(fixed) + "\n" if fixed else ""
        lines_to_add = []
        if repo_line not in content:
            lines_to_add.append(repo_line)
        if settings_line not in content:
            lines_to_add.append(settings_line)
        if lines_to_add:
            content = content.rstrip() + "\n" + "\n".join(lines_to_add) + "\n"
        config_file.write_text(content)
    else:
        config_file.write_text(repo_line + "\n" + settings_line + "\n")
    BASELINE_PATTERNS = [
        ".mvn/maven.config",
        ".mvn/slot-settings.xml",
        ".worktrees",
        ".worktrees/",
        ".claude",
        ".claude/",
    ]
    gitignore = repo_worktree / ".gitignore"
    if gitignore.exists():
        existing_lines = {line.strip() for line in gitignore.read_text().splitlines()}
        to_add = [p for p in BASELINE_PATTERNS if p not in existing_lines]
        if to_add:
            content = gitignore.read_text().rstrip()
            gitignore.write_text(content + "\n" + "\n".join(to_add) + "\n")
            return True
        return False
    else:
        gitignore.write_text("\n".join(BASELINE_PATTERNS) + "\n")
        return True


def _unignore_subdir(ws_clone: Path, subdir_name: str) -> None:
    """Remove a gitignore entry that hides a workspace subdirectory in a slot clone.
    In the main workspace, children like /claudony are separate git repos and correctly
    gitignored. In a slot clone, they're plain directories that must be tracked."""
    gitignore = ws_clone / ".gitignore"
    if not gitignore.exists():
        return
    lines = gitignore.read_text().splitlines()
    patterns_to_remove = {f"/{subdir_name}", subdir_name, f"/{subdir_name}/"}
    filtered = [line for line in lines if line.strip() not in patterns_to_remove]
    if len(filtered) != len(lines):
        gitignore.write_text("\n".join(filtered) + "\n" if filtered else "")


def repoint_wksp(repo_worktree: Path, ws_subdir: Path) -> None:
    wksp = repo_worktree / "wksp"
    if wksp.is_symlink() or wksp.exists():
        wksp.unlink()
    rel = os.path.relpath(ws_subdir, repo_worktree)
    wksp.symlink_to(rel)


def create_proj_symlink(ws_subdir: Path, repo_worktree: Path) -> None:
    proj = ws_subdir / "proj"
    if proj.is_symlink() or proj.exists():
        proj.unlink()
    rel = os.path.relpath(repo_worktree, ws_subdir)
    proj.symlink_to(rel)


def _exclude_symlinks(clone_path: Path) -> None:
    exclude_file = clone_path / ".git" / "info" / "exclude"
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    entries = {"wksp", "proj"}
    if exclude_file.exists():
        existing_lines = {
            line.strip() for line in exclude_file.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        entries -= existing_lines
    if entries:
        with open(exclude_file, "a") as f:
            for entry in sorted(entries):
                f.write(f"{entry}\n")


def _symlink_gitignored_assets(source_repo: Path, clone_dest: Path) -> list[str]:
    """Symlink gitignored asset directories from source into clone.
    Skips regenerable directories (node_modules, build output, IDE artifacts)."""
    linked: list[str] = []
    for entry in sorted(source_repo.iterdir()):
        if entry.name == ".git" or not entry.is_dir():
            continue
        if entry.name in _REGENERABLE_DIRS:
            continue
        clone_entry = clone_dest / entry.name
        if clone_entry.exists() or clone_entry.is_symlink():
            continue
        rc, _, _ = run_cmd(["git", "-C", str(source_repo), "check-ignore", "-q", entry.name])
        if rc == 0:
            clone_entry.symlink_to(str(entry.resolve()))
            linked.append(entry.name)
    return linked


def replicate_claude_md(repo_path: Path, ws_subdir: Path, repo_worktree: Path) -> None:
    orig_wksp = repo_path / "wksp"
    if not orig_wksp.is_symlink():
        return
    orig_ws_target = orig_wksp.resolve()
    orig_claude = orig_ws_target / "CLAUDE.md"
    if not orig_claude.exists():
        return

    ws_claude = ws_subdir / "CLAUDE.md"
    proj_claude = repo_worktree / "CLAUDE.md"

    if orig_claude.is_symlink():
        # Workspace symlink → project real file (most repos).
        # Project worktree already has the file (git-tracked).
        if not ws_claude.exists():
            ws_claude.symlink_to("proj/CLAUDE.md")
    else:
        # Workspace real file → project symlink (e.g. pages).
        # Copy to workspace subdir, symlink from project worktree.
        if not ws_claude.exists():
            shutil.copy2(str(orig_claude), str(ws_claude))
        if not proj_claude.exists():
            proj_claude.symlink_to("wksp/CLAUDE.md")


def sync_main(repo_path: str) -> None:
    rc, _, _ = run_cmd(["git", "-C", repo_path, "fetch", "origin"])
    if rc != 0:
        print(f"WARN=fetch_failed repo={repo_path}")
        return
    rc, _, _ = run_cmd(["git", "-C", repo_path, "remote", "get-url", "upstream"])
    if rc == 0:
        run_cmd(["git", "-C", repo_path, "fetch", "upstream"])
        run_cmd(["git", "-C", repo_path, "rebase", "upstream/main"])
        run_cmd(["git", "-C", repo_path, "push", "origin", "main"])
    else:
        run_cmd(["git", "-C", repo_path, "rebase", "origin/main"])


def write_slot_md(slot_dir: Path, slot_number: int, repos: list[str],
                  branch: str, issue: str, issue_repo: str,
                  covers: str, context: str,
                  isolation_type: str = "", isx_instance: str = "",
                  isx_template: str = "") -> None:
    content = f"""# Slot {slot_number} — {branch}

## Issue
{issue_repo}#{issue}
Covers: {covers}

## What to do
{context}

## Repos
"""
    for i, repo in enumerate(repos):
        primary = " (primary)" if i == 0 else ""
        content += f"- {repo}{primary}\n"
    if isolation_type:
        content += f"\n## Isolation\ntype: {isolation_type}\ninstance: {isx_instance}\ntemplate: {isx_template}\n"
    content += f"\n## Created\n{datetime.date.today().isoformat()}, branch: {branch}\n"
    (slot_dir / ".slot").write_text(content)


def create_slot(family_root: Path, repos: list[str], branch: str,
                issue: str, issue_repo: str, covers: str,
                context: str,
                isx: bool = False, isx_template: str = "",
                isx_instance: str = "") -> dict:
    if isx and not _check_isx_available():
        print("ERROR=isx_not_found")
        print("ERROR_DETAIL=isx is not on PATH. Install with: brew install sanne/tap/incus-spawn")
        sys.exit(1)

    slots_dir = family_root / SLOT_DIR_NAME
    slots_dir.mkdir(exist_ok=True)
    slot_num = allocate_slot_number(family_root)
    slot_dir = slots_dir / str(slot_num)
    slot_dir.mkdir()
    m2_dir = slot_dir / ".m2"
    m2_dir.mkdir()

    for repo_name in repos:
        repo_path = family_root / repo_name
        if not repo_path.is_dir():
            print(f"ERROR=repo_not_found repo={repo_name}")
            sys.exit(1)

        sync_main(str(repo_path))

        clone_dest = slot_dir / repo_name
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
        configure_slot_remotes(clone_dest, repo_path)
        configure_update_instead(repo_path)

        gi_changed = setup_slot_repo(clone_dest, m2_dir)
        if gi_changed:
            run_cmd(["git", "-C", str(clone_dest), "add", ".gitignore"])
            run_cmd(["git", "-C", str(clone_dest), "commit", "-m",
                     "chore: add slot infrastructure to .gitignore"])

        ws_info = resolve_workspace_source(repo_path)
        if ws_info:
            ws_source, ws_name = ws_info
            ws_slot_dir = slot_dir / ws_name

            if ws_slot_dir.exists():
                print(f"ERROR=workspace_name_collision ws={ws_name} repo={repo_name}")
                print(f"ERROR_DETAIL=Workspace clone name '{ws_name}' already exists in slot. "
                      f"Two project repos may share a workspace, or a naming collision occurred.")
                sys.exit(1)

            sync_main(str(ws_source))
            rc, _, stderr = run_cmd([
                "git", "clone", "--shared", "--branch", "main",
                str(ws_source), str(ws_slot_dir),
            ])
            if rc != 0:
                print(f"ERROR=workspace_clone_failed ws={ws_name} stderr={stderr.strip()}")
                sys.exit(1)
            rc, _, _ = run_cmd(["git", "-C", str(ws_slot_dir), "checkout", "-b", branch])
            if rc != 0:
                print(f"ERROR=workspace_branch_failed ws={ws_name}")
                sys.exit(1)
            _exclude_symlinks(ws_slot_dir)
            configure_slot_remotes(ws_slot_dir, ws_source)
            configure_update_instead(ws_source)
            (ws_slot_dir / ".workspace").touch()

            repoint_wksp(clone_dest, ws_slot_dir)
            create_proj_symlink(ws_slot_dir, clone_dest)
            replicate_claude_md(repo_path, ws_slot_dir, clone_dest)

    primary_repo = repos[0]
    primary_wksp = slot_dir / primary_repo / "wksp"
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
            print(f"ERROR=isx_branch_failed instance={instance_name} err={stderr.strip()}")
            sys.exit(1)

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
        for f in wksp_failures:
            print(f"ERROR=wksp_validation_failed detail={f}")
        sys.exit(1)

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
    if ws_info:
        ws_source, ws_name = ws_info
        family_repo_names = _get_family_repo_names(family_root)
        if ws_name in family_repo_names:
            ws_name = f"work-{ws_source.name}"
        ws_slot_dir = slot_dir / ws_name
        # Disambiguate when directory exists but belongs to a different workspace
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


def is_project_repo(name: str) -> bool:
    if name in (".m2", "attic"):
        return False
    if name == "work" or name.startswith("work-"):
        return False
    return True


def is_workspace_clone(repo_path: Path) -> bool:
    """Detect whether a repo clone is a workspace (not a project repo).

    Primary: .workspace marker file (#239, #255).
    Transition fallback (remove after #255 Phase 3): proj symlink, work-* naming.
    """
    if not repo_path.is_dir():
        return False
    if (repo_path / ".workspace").exists():
        return True
    if (repo_path / "proj").is_symlink():
        return True
    return not is_project_repo(repo_path.name)


def get_slot_repos(slot_dir: Path) -> list[str]:
    return [
        d.name for d in sorted(slot_dir.iterdir())
        if d.is_dir() and (d / ".git").exists()
        and is_project_repo(d.name) and not is_workspace_clone(d)
    ]


def get_all_slot_repos(slot_dir: Path) -> list[str]:
    """All git repos in the slot — project + workspace."""
    return [
        d.name for d in sorted(slot_dir.iterdir())
        if d.is_dir() and (d / ".git").exists()
        and d.name not in (".m2", "attic")
    ]


def configure_slot_remotes(clone_path: Path, original_path: Path) -> dict[str, str]:
    """Reconfigure clone remotes: local=clone-source, origin=fork, upstream=blessed."""
    if _detect_topology is None:
        return {"origin": "", "upstream": "", "local": str(original_path)}

    fork_remote, blessed_remote = _detect_topology(str(original_path))
    if not fork_remote:
        return {"origin": "", "upstream": "", "local": str(original_path)}

    rc, fork_url, _ = run_cmd(
        ["git", "-C", str(original_path), "remote", "get-url", fork_remote])
    if rc != 0:
        return {"origin": "", "upstream": "", "local": str(original_path)}
    fork_url = fork_url.strip()

    run_cmd(["git", "-C", str(clone_path), "remote", "rename", "origin", "local"])
    run_cmd(["git", "-C", str(clone_path), "remote", "add", "origin", fork_url])
    run_cmd(["git", "-C", str(clone_path), "fetch", "origin"])
    run_cmd(["git", "-C", str(clone_path), "branch",
             "--set-upstream-to=origin/main", "main"])

    upstream_url = ""
    if blessed_remote:
        rc, blessed_url, _ = run_cmd(
            ["git", "-C", str(original_path), "remote", "get-url", blessed_remote])
        if rc == 0:
            upstream_url = blessed_url.strip()
            run_cmd(["git", "-C", str(clone_path), "remote", "add",
                     "upstream", upstream_url])

    return {"origin": fork_url, "upstream": upstream_url, "local": str(original_path)}


def configure_update_instead(original_path: Path) -> None:
    """Set receive.denyCurrentBranch=updateInstead on original repo."""
    run_cmd(["git", "-C", str(original_path), "config",
             "receive.denyCurrentBranch", "updateInstead"])


def parse_slot_md(slot_dir: Path) -> dict:
    slot_md = slot_dir / ".slot"
    if not slot_md.exists():
        return {}
    content = slot_md.read_text()
    result: dict = {"repos": [], "context": "", "issue": "", "issue_repo": "", "covers": "", "is_epic": False, "isolation_type": "", "isx_instance": "", "isx_template": ""}

    in_issue = False
    in_what = False
    in_repos = False
    in_isolation = False
    context_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("# Slot") and "—" in line:
            result["branch"] = line.split("—", 1)[1].strip()
        if line.startswith("Covers:"):
            result["covers"] = line.split(":", 1)[1].strip()
        if line.startswith("## Issue"):
            in_issue, in_what, in_repos, in_isolation = True, False, False, False
            continue
        if line.startswith("## What to do"):
            in_issue, in_what, in_repos, in_isolation = False, True, False, False
            continue
        if line.startswith("## Repos"):
            in_issue, in_what, in_repos, in_isolation = False, False, True, False
            continue
        if line.startswith("## Isolation"):
            in_issue, in_what, in_repos, in_isolation = False, False, False, True
            continue
        if line.startswith("## "):
            in_issue, in_what, in_repos, in_isolation = False, False, False, False
            continue
        if in_issue and line.strip().startswith("Type:"):
            result["is_epic"] = line.strip().split(":", 1)[1].strip() == "epic"
        if in_issue and "#" in line and not line.startswith("Covers:"):
            parts = line.strip().split("#")
            if len(parts) == 2:
                result["issue_repo"] = parts[0]
                result["issue"] = parts[1]
        if in_what:
            context_lines.append(line.strip())
        if in_repos and line.strip().startswith("- "):
            repo_name = line.strip().lstrip("- ").split(" ")[0].strip()
            if repo_name:
                result["repos"].append(repo_name)
        if in_isolation:
            stripped = line.strip()
            if stripped.startswith("type:"):
                result["isolation_type"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("instance:"):
                result["isx_instance"] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("template:"):
                result["isx_template"] = stripped.split(":", 1)[1].strip()

    result["context"] = " ".join(l for l in context_lines if l).strip()
    return result


def get_repo_stats(repo_path: Path) -> dict:
    rc, log_out, _ = run_cmd(
        ["git", "-C", str(repo_path), "log", "--oneline", "origin/main..HEAD"]
    )
    commits = len(log_out.strip().splitlines()) if rc == 0 and log_out.strip() else 0
    rc, stat_out, _ = run_cmd(
        ["git", "-C", str(repo_path), "diff", "--shortstat", "origin/main..HEAD"]
    )
    diff = stat_out.strip() if rc == 0 else ""
    return {"commits": commits, "diff": diff}


def scan_ready(family_root: Path) -> list[dict]:
    slots = []
    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        slots_dir = family_root / dir_name
        if not slots_dir.exists():
            continue
        for d in sorted(slots_dir.iterdir()):
            if not d.is_dir() or not d.name.isdigit():
                continue
            if not (d / ".phase-a-complete").exists():
                continue
            if (d / ".landed").exists():
                continue
            timestamp = ""
            for line in (d / ".phase-a-complete").read_text().splitlines():
                if line.startswith("timestamp="):
                    timestamp = line.split("=", 1)[1]
            md = parse_slot_md(d)
            repo_names = md.get("repos", [])
            repo_data = []
            for repo_name in repo_names:
                repo_path = d / repo_name
                if repo_path.is_dir() and (repo_path / ".git").exists():
                    stats = get_repo_stats(repo_path)
                    repo_data.append({"name": repo_name, **stats})
                else:
                    repo_data.append({"name": repo_name, "commits": 0, "diff": ""})
            slots.append({
                "number": int(d.name),
                "branch": md.get("branch", ""),
                "repos": repo_data,
                "issue": md.get("issue", ""),
                "issue_repo": md.get("issue_repo", ""),
                "covers": md.get("covers", ""),
                "context": md.get("context", ""),
                "phase_a_timestamp": timestamp,
            })
    return slots


def is_worktree(repo_path: Path) -> bool:
    git_path = repo_path / ".git"
    return git_path.is_file()


def resolve_original_repo(repo_path: Path) -> Path:
    if is_worktree(repo_path):
        rc, common_dir, _ = run_cmd(
            ["git", "-C", str(repo_path), "rev-parse", "--git-common-dir"]
        )
        if rc == 0:
            common = Path(common_dir.strip())
            if not common.is_absolute():
                common = (repo_path / common).resolve()
            return common.parent

    for remote in ("local", "origin"):
        rc, url, _ = run_cmd(
            ["git", "-C", str(repo_path), "remote", "get-url", remote]
        )
        if rc == 0 and url.strip():
            origin_path = Path(url.strip())
            if origin_path.is_dir():
                return origin_path.resolve()

    return repo_path


def _migrate_worktree_to_clone(worktree_path: Path) -> bool:
    """Migrate a single worktree to a git clone --shared. Returns True on success."""
    import tempfile

    branch_rc, branch_out, _ = run_cmd(
        ["git", "-C", str(worktree_path), "branch", "--show-current"]
    )
    branch = branch_out.strip() if branch_rc == 0 else ""
    if not branch:
        return False

    original = resolve_original_repo(worktree_path)
    if original == worktree_path:
        return False

    status_rc, status_out, _ = run_cmd(
        ["git", "-C", str(worktree_path), "status", "--short"]
    )
    if status_rc == 0 and status_out.strip():
        run_cmd(["git", "-C", str(worktree_path), "add", "-A"])
        run_cmd(["git", "-C", str(worktree_path), "commit", "-m", "WIP: pre-migration"])

    with tempfile.TemporaryDirectory() as tmpdir:
        clone_tmp = Path(tmpdir) / worktree_path.name
        rc, _, stderr = run_cmd([
            "git", "clone", "--shared", str(original), str(clone_tmp),
        ])
        if rc != 0:
            print(f"WARN=migration_clone_failed path={worktree_path} stderr={stderr.strip()}")
            return False

        rc, _, _ = run_cmd(["git", "-C", str(clone_tmp), "checkout", branch])
        if rc != 0:
            rc, _, _ = run_cmd(["git", "-C", str(clone_tmp), "checkout", "-b", branch, f"origin/{branch}"])
            if rc != 0:
                print(f"WARN=migration_branch_failed path={worktree_path} branch={branch}")
                return False

        orig_rc, orig_tree, _ = run_cmd(
            ["git", "-C", str(worktree_path), "rev-parse", "HEAD^{tree}"]
        )
        clone_rc, clone_tree, _ = run_cmd(
            ["git", "-C", str(clone_tmp), "rev-parse", "HEAD^{tree}"]
        )
        if orig_rc != 0 or clone_rc != 0 or orig_tree.strip() != clone_tree.strip():
            print(f"WARN=migration_tree_mismatch path={worktree_path}")
            return False

        rc, _, stderr = run_cmd(["git", "-C", str(original), "worktree", "remove", "--force", str(worktree_path)])
        if worktree_path.exists():
            _cleanup_remnant_dir(worktree_path)
        if rc != 0 and worktree_path.exists():
            print(f"WARN=migration_worktree_remove_failed path={worktree_path} stderr={stderr.strip()}")
            return False

        shutil.move(str(clone_tmp), str(worktree_path))
        _exclude_symlinks(worktree_path)

    return True


def ensure_clone_layout(slot_dir: Path) -> int:
    """Migrate any worktree repos in a slot to git clone --shared. Returns count migrated."""
    migrated = 0
    for sub in slot_dir.iterdir():
        if sub.is_dir() and (sub / ".git").exists() and is_worktree(sub):
            if _migrate_worktree_to_clone(sub):
                migrated += 1
                print(f"MIGRATED={sub.name}")
    return migrated


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

    descriptors = build_slot_batch(slot_dir)
    if not descriptors:
        print("ERROR=no_repos_in_slot")
        return 1

    progress_file = slot_dir / ".execute-progress"
    result = land_batch(descriptors, branch, progress_file)

    if not result.success:
        for s in result.repos:
            if s.error:
                print(f"ERROR={s.error} repo={s.repo_path.name}")
        return 1

    # Write .landed marker
    project_repos = [d.repo_path.name for d in descriptors if not d.is_workspace]
    landed_shas = {s.repo_path.name: s.landed_sha for s in result.repos if s.landed_sha}
    shas_str = ",".join(f"{r}:{s}" for r, s in landed_shas.items())
    (slot_dir / ".landed").write_text(
        f"branch={branch}\n"
        f"repos={','.join(project_repos)}\n"
        f"landed_shas={shas_str}\n"
        f"timestamp={datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
    )

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
        print(f"RESULT={s.repo_path.name} STATUS={'ok' if not s.error else s.error} SHA={s.landed_sha} ICON={icon}")
    ok_count = sum(1 for s in result.repos if not s.error)
    print(f"SUMMARY=ok:{ok_count} warn:0 fail:0")
    print(f"LANDED_SHAS={shas_str}")
    return 0


def _claude_project_matches(proj_name: str, slot_path_encoded: str) -> bool:
    """Check if a Claude project directory name matches a slot path.
    Uses boundary-aware matching to prevent /worktrees/1 matching /worktrees/10."""
    if proj_name == slot_path_encoded:
        return True
    if proj_name.startswith(slot_path_encoded + "-"):
        return True
    return False


def relocate_claude_projects(slot_dir: Path, dest_dir: Path) -> int:
    """Move .claude/projects/ directories to match the slot's new attic path."""
    claude_projects = Path.home() / ".claude" / "projects"
    if not claude_projects.is_dir():
        return 0

    slot_path_encoded = str(slot_dir.resolve()).replace("/", "-")
    dest_path_encoded = str(dest_dir.resolve()).replace("/", "-")
    moved = 0

    for proj_dir in claude_projects.iterdir():
        if not proj_dir.is_dir():
            continue
        if _claude_project_matches(proj_dir.name, slot_path_encoded):
            new_name = proj_dir.name.replace(slot_path_encoded, dest_path_encoded, 1)
            new_path = claude_projects / new_name
            if not new_path.exists():
                shutil.move(str(proj_dir), str(new_path))
                moved += 1
    return moved


def remove_claude_projects(slot_dir: Path) -> int:
    """Remove .claude/projects/ directories that reference a slot being destroyed."""
    claude_projects = Path.home() / ".claude" / "projects"
    if not claude_projects.is_dir():
        return 0

    slot_path_encoded = str(slot_dir.resolve()).replace("/", "-")
    removed = 0

    for proj_dir in list(claude_projects.iterdir()):
        if not proj_dir.is_dir():
            continue
        if _claude_project_matches(proj_dir.name, slot_path_encoded):
            shutil.rmtree(str(proj_dir), ignore_errors=True)
            removed += 1
    return removed


def is_slot_landed(slot_dir: Path) -> bool:
    return (slot_dir / ".landed").exists()


def verify_landed_shas(slot_dir: Path, family_root: Path) -> tuple[bool, list[str]]:
    landed_file = slot_dir / ".landed"
    if not landed_file.exists():
        return False, ["no .landed marker"]
    shas_line = ""
    for line in landed_file.read_text().splitlines():
        if line.startswith("landed_shas="):
            shas_line = line.split("=", 1)[1]
    if not shas_line:
        return False, ["no landed_shas in .landed marker"]
    failures = []
    for entry in shas_line.split(","):
        if ":" not in entry:
            continue
        repo_name, sha = entry.split(":", 1)
        if sha == "unknown":
            failures.append(f"{repo_name}: SHA is 'unknown'")
            continue
        original = family_root / repo_name
        if not original.is_dir():
            failures.append(f"{repo_name}: original repo not found at {original}")
            continue
        run_cmd(["git", "-C", str(original), "fetch", "origin", "main"])
        rc, _, _ = run_cmd([
            "git", "-C", str(original), "merge-base", "--is-ancestor", sha, "origin/main",
        ])
        if rc != 0:
            failures.append(f"{repo_name}: SHA {sha[:12]} not reachable from main")
    return len(failures) == 0, failures


def _fix_stale_checkboxes(slot_path: Path, issues_to_tick: list[int]) -> int:
    """Tick unchecked boxes for completed issues. Returns count fixed."""
    content = slot_path.read_text()
    fixed = 0
    lines = content.splitlines()
    result = []
    for line in lines:
        for n in issues_to_tick:
            if f"- [ ] #{n} " in line or line.rstrip().endswith(f"- [ ] #{n}"):
                line = line.replace("- [ ]", "- [x]", 1)
                fixed += 1
                break
        result.append(line)
    if fixed:
        slot_path.write_text("\n".join(result))
    return fixed


def archive_slot(family_root: Path, slot_num: int, force: bool = False) -> None:
    slot_dir = _resolve_slot_dir_for_number(family_root, slot_num)
    if not slot_dir.exists():
        print(f"ERROR=slot_not_found slot={slot_num}")
        sys.exit(1)
    ensure_clone_layout(slot_dir)
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

    _teardown_isx(slot_dir)

    attic_dir = slot_dir.parent / "attic"
    attic_dir.mkdir(exist_ok=True)
    dest = attic_dir / str(slot_num)
    merge_into_existing = dest.exists()
    if merge_into_existing:
        print(f"WARN=attic_slot_exists slot={slot_num} — merging into existing attic entry")
    moved = relocate_claude_projects(slot_dir, dest)
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
    if moved:
        print(f"CLAUDE_PROJECTS_MOVED={moved}")

    if _wl:
        try:
            _conn = _wl.connect()
            promoted, published, pub_dest = _read_promotion_stamp(dest)
            _wl.record_slot_archive(
                _conn, slot_num, str(family_root),
                promoted=promoted,
                published=published,
                publish_dest=pub_dest,
                archived_from=str(slot_dir),
                archived_to=str(dest),
            )
            _conn.close()
        except Exception:
            pass

    print(f"ARCHIVED={slot_num}")


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
    moved = relocate_claude_projects(attic_dir, dest)
    shutil.move(str(attic_dir), str(dest))
    if attic_dir.exists():
        if not _cleanup_remnant_dir(attic_dir):
            print(f"WARN=remnant_dir_persists path={attic_dir}")
    if moved:
        print(f"CLAUDE_PROJECTS_MOVED={moved}")
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


def list_slots(family_root: Path, include_archived: bool = False) -> list[dict]:
    slots = []
    seen: set[int] = set()

    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        slots_dir = family_root / dir_name
        if not slots_dir.exists():
            continue

        attic_dir = slots_dir / "attic"
        archived_nums: set[int] = set()
        if attic_dir.exists():
            archived_nums = {
                int(d.name) for d in attic_dir.iterdir()
                if d.is_dir() and d.name.isdigit()
            }

        for d in sorted(slots_dir.iterdir()):
            if not d.is_dir() or not d.name.isdigit():
                continue
            num = int(d.name)
            if num in archived_nums or num in seen:
                continue
            seen.add(num)
            repos = [
                sub.name for sub in sorted(d.iterdir())
                if sub.is_dir() and (sub / ".git").exists() and is_project_repo(sub.name)
            ]
            branch = ""
            slot_md = d / ".slot"
            if slot_md.exists():
                for line in slot_md.read_text().splitlines():
                    if line.startswith("# Slot") and "—" in line:
                        branch = line.split("—", 1)[1].strip()
                        break

            if (d / ".landed").exists():
                state = "landed"
            elif (d / ".phase-a-complete").exists():
                state = "ready to land"
            else:
                state = "active"

            isolation = "none"
            if slot_md.exists():
                md = parse_slot_md(d)
                isolation = md.get("isolation_type", "") or "none"

            wksp_ok = True
            if state not in ("archived", "landed"):
                wksp_failures = validate_slot_wksp(d)
                wksp_ok = len(wksp_failures) == 0

            slots.append({
                "number": num,
                "branch": branch,
                "repos": repos,
                "state": state,
                "isolation": isolation,
                "wksp_ok": wksp_ok,
            })

        if include_archived and attic_dir.exists():
            for d in sorted(attic_dir.iterdir()):
                if not d.is_dir() or not d.name.isdigit():
                    continue
                num = int(d.name)
                if num in seen:
                    continue
                seen.add(num)
                md = parse_slot_md(d)
                slots.append({
                    "number": num,
                    "branch": md.get("branch", ""),
                    "repos": md.get("repos", []),
                    "state": "archived",
                    "isolation": md.get("isolation_type", "") or "none",
                    "wksp_ok": True,
                })

    _check_drift(family_root, slots, include_archived)

    return slots


def _map_db_to_disk_state(db_state: str) -> str:
    mapping = {
        "active": "active",
        "pending": "active",
        "ready": "ready to land",
        "landed": "landed",
        "archived": "archived",
    }
    return mapping.get(db_state, db_state)


def _check_drift(family_root: Path, slots: list[dict],
                  include_archived: bool) -> None:
    if _wl is None:
        return
    try:
        conn = _wl.connect()
        db_rows = _wl.slot_status(conn, family_root=str(family_root))
        conn.close()
    except Exception:
        return

    db_slots: dict[int, str] = {r["slot_number"]: r["state"] for r in db_rows}
    disk_nums: dict[int, str] = {s["number"]: s["state"] for s in slots}

    has_slot_file: set[int] = set()
    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        slots_dir = family_root / dir_name
        if not slots_dir.exists():
            continue
        for d in slots_dir.iterdir():
            if not d.is_dir() or not d.name.isdigit() or d.name == "attic":
                continue
            num = int(d.name)
            if (d / ".slot").exists():
                has_slot_file.add(num)

    for num, db_state in db_slots.items():
        if db_state == "pending":
            if num in disk_nums:
                print(f"WARN=db_drift type=pending slot={num}")
            continue
        if num not in disk_nums:
            if not include_archived:
                attic_exists = any(
                    (family_root / dn / "attic" / str(num)).exists()
                    for dn in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME)
                )
                if attic_exists and db_state in ("archived", "landed"):
                    continue
            print(f"WARN=db_drift type=db-only slot={num}")
        else:
            disk_state = disk_nums[num]
            db_mapped = _map_db_to_disk_state(db_state)
            if db_mapped != disk_state:
                print(f"WARN=db_drift type=state-mismatch slot={num} db={db_state} disk={disk_state}")

    for num in disk_nums:
        if num not in db_slots:
            if num not in has_slot_file:
                print(f"WARN=db_drift type=ghost slot={num}")
            else:
                print(f"WARN=db_drift type=disk-only slot={num}")


def remove_slot(family_root: Path, slot_num: int, force: bool = False) -> None:
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
    moved = relocate_claude_projects(slot_dir, dest)
    shutil.move(str(slot_dir), str(dest))
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
    if moved:
        print(f"CLAUDE_PROJECTS_MOVED={moved}")
    if _wl:
        try:
            _conn = _wl.connect()
            promoted, published, pub_dest = _read_promotion_stamp(dest)
            _wl.record_slot_archive(
                _conn, slot_num, str(family_root),
                promoted=promoted, published=published,
                publish_dest=pub_dest,
                archived_from=str(slot_dir), archived_to=str(dest),
            )
            _conn.close()
        except Exception:
            pass
    print(f"ARCHIVED={slot_num}")


def check_cross_deps(family_root: Path, slot_num: int) -> int:
    """Check if cross-repo Maven dependencies in a slot have landed on main."""
    slot_dir = _resolve_slot_dir_for_number(family_root, slot_num)
    if not slot_dir.exists():
        print(f"ERROR=slot_not_found slot={slot_num}")
        return 1

    repos = get_slot_repos(slot_dir)
    if len(repos) < 2:
        print("CHECK=skip (single repo, no cross-deps)")
        return 0

    group_ids: dict[str, set[str]] = {}
    dep_graph: dict[str, set[str]] = {}

    for repo_name in repos:
        slot_repo = slot_dir / repo_name
        group_ids[repo_name] = set()
        dep_graph[repo_name] = set()

        for pom in slot_repo.rglob("pom.xml"):
            try:
                content = pom.read_text()
            except Exception:
                continue
            import re
            for m in re.finditer(r"<groupId>([^<]+)</groupId>", content):
                if pom.parent == slot_repo:
                    group_ids[repo_name].add(m.group(1))

    for repo_name in repos:
        slot_repo = slot_dir / repo_name
        for pom in slot_repo.rglob("pom.xml"):
            try:
                content = pom.read_text()
            except Exception:
                continue
            import re
            for m in re.finditer(r"<dependency>[^<]*<groupId>([^<]+)</groupId>", content, re.DOTALL):
                dep_gid = m.group(1)
                for other_repo, gids in group_ids.items():
                    if other_repo != repo_name and dep_gid in gids:
                        dep_graph[repo_name].add(other_repo)

    if not any(dep_graph.values()):
        print("CHECK=pass (no cross-repo Maven dependencies detected)")
        return 0

    issues = []
    for consumer, providers in dep_graph.items():
        for provider in providers:
            original = resolve_original_repo(slot_dir / provider)
            rc, branch_out, _ = run_cmd(["git", "-C", str(original), "branch", "--show-current"])
            current = branch_out.strip() if rc == 0 else "unknown"
            slot_repo = slot_dir / provider
            rc, slot_branch, _ = run_cmd(["git", "-C", str(slot_repo), "branch", "--show-current"])
            slot_br = slot_branch.strip() if rc == 0 else "unknown"
            if current == "main":
                rc, _, _ = run_cmd(["git", "-C", str(original), "log", f"--grep={slot_br}", "--oneline", "-1"])
                print(f"DEP={consumer} → {provider} STATUS=on-main")
            else:
                issues.append((consumer, provider, slot_br))
                print(f"DEP={consumer} → {provider} STATUS=not-on-main branch={slot_br}")

    if issues:
        print(f"CHECK=fail BLOCKING={len(issues)}")
        for consumer, provider, branch in issues:
            print(f"BLOCK={provider} must land on main before {consumer} can be pushed (branch={branch})")
        return 1
    else:
        print("CHECK=pass (all provider repos on main)")
        return 0


def parse_args() -> dict[str, str]:
    parsed = {}
    for arg in sys.argv[1:]:
        if "=" in arg:
            key, val = arg.split("=", 1)
            parsed[key] = val
        else:
            if "subcommand" not in parsed:
                parsed["subcommand"] = arg
            elif "target" not in parsed:
                parsed["target"] = arg
    return parsed


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


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    args = parse_args()
    subcommand = args.get("subcommand")

    if subcommand == "create-slot":
        family_root = Path(args.get("target", "."))
        repos = [r.strip() for r in args.get("repos", "").split(",") if r.strip()]
        if not repos:
            print("ERROR=missing_repos")
            sys.exit(1)
        branch = args.get("branch", "")
        if not branch:
            print("ERROR=missing_branch")
            sys.exit(1)
        result = create_slot(
            family_root=family_root,
            repos=repos,
            branch=branch,
            issue=args.get("issue", ""),
            issue_repo=args.get("issue-repo", ""),
            covers=args.get("covers", args.get("issue", "")),
            context=args.get("context", ""),
            isx=args.get("isx", "").lower() in ("yes", "true", "1"),
            isx_template=args.get("template", ""),
            isx_instance=args.get("instance", ""),
        )
        print(f"SLOT_NUMBER={result['slot_number']}")
        print(f"SLOT_DIR={result['slot_dir']}")
        print(f"BRANCH={result['branch']}")

    elif subcommand == "list-slots":
        family_root = Path(args.get("target", "."))
        include_archived = "--all" in sys.argv
        slots = list_slots(family_root, include_archived=include_archived)
        for s in slots:
            repos_str = ",".join(s["repos"]) if isinstance(s["repos"], list) else s["repos"]
            wksp = "ok" if s.get("wksp_ok", True) else "broken"
            print(f"SLOT={s['number']} BRANCH={s['branch']} REPOS={repos_str} STATE={s['state']} ISOLATION={s.get('isolation', 'none')} WKSP={wksp}")
        print(f"COUNT={len(slots)}")

    elif subcommand == "remove-slot":
        family_root = Path(args.get("target", "."))
        slot_num = int(args.get("slot", "0"))
        if slot_num == 0:
            print("ERROR=missing_slot_number")
            sys.exit(1)
        force = "--force" in sys.argv or "--force-delete" in sys.argv
        remove_slot(family_root, slot_num, force=force)

    elif subcommand == "scan-ready":
        family_root = Path(args.get("target", "."))
        slots = scan_ready(family_root)
        print(json.dumps({"slots": slots}, indent=2))

    elif subcommand == "merge-slot":
        family_root = Path(args.get("target", "."))
        slot_num = int(args.get("slot", "0"))
        if slot_num == 0:
            print("ERROR=missing_slot_number")
            sys.exit(1)
        sys.exit(merge_slot(family_root, slot_num))

    elif subcommand == "archive-slot":
        family_root = Path(args.get("target", "."))
        slot_num = int(args.get("slot", "0"))
        if slot_num == 0:
            print("ERROR=missing_slot_number")
            sys.exit(1)
        force = "--force" in sys.argv
        archive_slot(family_root, slot_num, force=force)

    elif subcommand == "restore-slot":
        family_root = Path(args.get("target", "."))
        slot_num = int(args.get("slot", "0"))
        if slot_num == 0:
            print("ERROR=missing_slot_number")
            sys.exit(1)
        restore_slot(family_root, slot_num)

    elif subcommand == "ensure-clone-layout":
        family_root = Path(args.get("target", "."))
        slot_num = int(args.get("slot", "0"))
        if slot_num == 0:
            print("ERROR=missing_slot_number")
            sys.exit(1)
        slot_dir = _resolve_slot_dir_for_number(family_root, slot_num)
        if not slot_dir.exists():
            print(f"ERROR=slot_not_found slot={slot_num}")
            sys.exit(1)
        count = ensure_clone_layout(slot_dir)
        print(f"MIGRATED_COUNT={count}")

    elif subcommand == "check-cross-deps":
        family_root = Path(args.get("target", "."))
        slot_num = int(args.get("slot", "0"))
        if slot_num == 0:
            print("ERROR=missing_slot_number")
            sys.exit(1)
        sys.exit(check_cross_deps(family_root, slot_num))

    elif subcommand == "migrate-remotes":
        family_root = Path(args.get("target", "."))
        count = migrate_remotes(family_root)
        print(f"COUNT={count}")

    elif subcommand == "sync-isx":
        target = args.get("target", "")
        slot_num_str = args.get("slot", "")
        if slot_num_str:
            family_root = Path(target) if target else Path(".")
            slot_dir = _resolve_slot_dir_for_number(family_root, int(slot_num_str))
        elif target:
            slot_dir = Path(target)
        else:
            slot_dir = Path(".")
        if not slot_dir.exists():
            print("ERROR=slot_not_found")
            sys.exit(1)
        sys.exit(sync_isx(slot_dir))

    else:
        print(f"ERROR=unknown_subcommand subcommand={subcommand}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
