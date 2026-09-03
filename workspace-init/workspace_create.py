#!/usr/bin/env python3
"""
Create workspace directories, INDEX.md files, and stub files.

Called by workspace-init Steps 2-4 and Step 8. Replaces mkdir + heredoc
blocks that trigger Claude Code permission prompts.

Usage:
    python3 workspace_create.py <subcommand> <workspace_path> [key=value args...]

Subcommands:
    create-dirs     Create standard workspace directories
    create-indexes  Create INDEX.md in snapshots/, adr/, blog/
    create-stubs    Create HANDOFF.md and IDEAS.md stubs
    init-repo       Initialise git repo and optionally create GitHub remote

Output (KEY=value lines):
    CREATED=yes|no|<count>    (varies by subcommand)
    REPO_URL=<url>            (init-repo only, on success)
    ERROR=<code>              (on failure)
    ERROR_DETAIL=<message>    (on failure, when detail is available)

Exit codes:
    0  success
    1  missing required args or I/O error
"""

import os
import subprocess
import sys
from pathlib import Path

from common import parse_args


STANDARD_DIRS = ["plans", "specs", "snapshots", "adr", "blog", "design"]

INDEX_SPECS: dict[str, str] = {
    "snapshots": (
        "# Snapshots Index\n"
        "\n"
        "| File | Date | Topic |\n"
        "|------|------|-------|\n"
    ),
    "adr": (
        "# ADR Index\n"
        "\n"
        "| ID | Title | Status | Date |\n"
        "|----|-------|--------|------|\n"
    ),
    "blog": (
        "# Blog Index\n"
        "\n"
        "| File | Date | Title |\n"
        "|------|------|-------|\n"
    ),
}

STUB_FILES: dict[str, str] = {
    "HANDOFF.md": "# Handoff\n\nNo sessions yet.\n",
    "IDEAS.md": "# Idea Log\n\nUndecided possibilities — things worth remembering but not yet decided.\nPromote to an ADR when ready to decide; discard when no longer relevant.\n",
}


def resolve_workspace(project: Path) -> Path | None:
    """Derive the canonical workspace path for a project.

    Discovery order:
    1. Follow project's wksp/ symlink if it points to a valid workspace
    2. Check ~/claude/public/<parent>/<project>/
    3. Check ~/claude/private/<parent>/<project>/
    Returns None if no workspace found at any canonical location.
    """
    wksp = project / "wksp"
    if wksp.is_symlink() and wksp.is_dir():
        resolved = wksp.resolve()
        loc_err = validate_workspace_location(resolved)
        marker_err = validate_workspace_marker(resolved, project)
        if not loc_err and not marker_err:
            return resolved

    parent_name = project.resolve().parent.name
    project_name = project.resolve().name
    home = Path.home()
    for privacy in ("public", "private"):
        candidate = home / "claude" / privacy / parent_name / project_name
        if candidate.is_dir():
            loc_err = validate_workspace_location(candidate)
            if not loc_err:
                return candidate

    return None


def ensure_workspace(project: Path) -> Path:
    """Find or create the canonical workspace for a project.

    If a valid workspace exists, returns it. If not, creates one at
    ~/claude/public/<parent>/<project>/ with git init, standard dirs,
    .workspace marker, and bidirectional symlinks.
    """
    existing = resolve_workspace(project)
    if existing:
        marker = existing / ".workspace"
        if not marker.exists():
            write_workspace_marker(existing, project)
        return existing

    parent_name = project.resolve().parent.name
    project_name = project.resolve().name
    workspace = Path.home() / "claude" / "public" / parent_name / project_name
    workspace.mkdir(parents=True, exist_ok=True)

    cmd_create_dirs(workspace)
    write_workspace_marker(workspace, project)

    git_dir = workspace / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init"], cwd=str(workspace), capture_output=True)
        gitignore = workspace / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(".DS_Store\n*.swp\n")
        subprocess.run(["git", "add", "-A"], cwd=str(workspace), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init: workspace setup"],
                       cwd=str(workspace), capture_output=True)

    proj_link = workspace / "proj"
    if not proj_link.exists():
        rel_to_project = os.path.relpath(project.resolve(), workspace.resolve())
        proj_link.symlink_to(rel_to_project)
    wksp_link = project / "wksp"
    if wksp_link.is_symlink():
        wksp_link.unlink()
    rel_to_workspace = os.path.relpath(workspace.resolve(), project.resolve())
    wksp_link.symlink_to(rel_to_workspace)

    return workspace


def write_workspace_marker(workspace: Path, project: Path) -> None:
    """Write .workspace marker identifying this as a valid workspace."""
    marker = workspace / ".workspace"
    marker.write_text(
        f"project: {project.resolve()}\n"
        f"created: {__import__('datetime').date.today().isoformat()}\n"
    )


def validate_workspace_location(workspace: Path) -> str | None:
    """Check that workspace is an independent git root, not nested inside another repo.
    Returns None if valid, error message if invalid."""
    if not workspace.is_dir():
        return f"workspace path does not exist: {workspace}"
    result = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    toplevel = Path(result.stdout.strip()).resolve()
    ws_resolved = workspace.resolve()
    if toplevel != ws_resolved:
        return (f"workspace is nested inside another git repo: "
                f"{workspace} is inside {toplevel} — "
                f"commits will go to the wrong repo")
    return None


def validate_workspace_marker(workspace: Path, project: Path | None = None) -> str | None:
    """Check that .workspace marker exists and matches the expected project.
    Returns None if valid, error message if invalid."""
    marker = workspace / ".workspace"
    if not marker.exists():
        return f"no .workspace marker at {workspace} — not a valid workspace"
    if project is None:
        return None
    for line in marker.read_text().splitlines():
        if line.startswith("project:"):
            marker_project = Path(line.split(":", 1)[1].strip()).resolve()
            if marker_project != project.resolve():
                return (f".workspace marker points to {marker_project}, "
                        f"but expected {project.resolve()}")
            return None
    return ".workspace marker has no project field"


# -- Subcommands -------------------------------------------------------------

def cmd_create_dirs(workspace: Path) -> int:
    if not workspace.is_dir():
        print("ERROR=workspace_not_found")
        print(f"ERROR_DETAIL=Path does not exist: {workspace}", flush=True)
        return 1

    all_existed = True
    for d in STANDARD_DIRS:
        target = workspace / d
        if not target.is_dir():
            all_existed = False
        target.mkdir(parents=True, exist_ok=True)

    print("CREATED=no" if all_existed else "CREATED=yes")
    return 0


def cmd_create_indexes(workspace: Path) -> int:
    if not workspace.is_dir():
        print("ERROR=workspace_not_found")
        print(f"ERROR_DETAIL=Path does not exist: {workspace}", flush=True)
        return 1

    created = 0
    for dirname, content in INDEX_SPECS.items():
        target = workspace / dirname / "INDEX.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text(content)
            created += 1

    print(f"CREATED={created}")
    return 0


def cmd_create_stubs(workspace: Path) -> int:
    if not workspace.is_dir():
        print("ERROR=workspace_not_found")
        print(f"ERROR_DETAIL=Path does not exist: {workspace}", flush=True)
        return 1

    created = 0
    for filename, content in STUB_FILES.items():
        target = workspace / filename
        if not target.exists():
            target.write_text(content)
            created += 1

    print(f"CREATED={created}")
    return 0


def cmd_init_repo(workspace: Path, params: dict[str, str]) -> int:
    if not workspace.is_dir():
        print("ERROR=workspace_not_found")
        print(f"ERROR_DETAIL=Path does not exist: {workspace}", flush=True)
        return 1

    git_dir = workspace / ".git"
    if git_dir.exists():
        print("ERROR=already_initialized")
        return 1

    name = params.get("name", "")
    if name and "/" not in name:
        print("ERROR=invalid_name")
        print("ERROR_DETAIL=name must be owner/repo format", flush=True)
        return 1

    visibility = params.get("visibility", "")

    # Initialise git
    gitignore = workspace / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("# Auto-generated by workspace init\n.DS_Store\n*.swp\n")

    try:
        subprocess.run(
            ["git", "init"],
            cwd=str(workspace), capture_output=True, text=True, check=True,
        )
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(workspace), capture_output=True, text=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init: workspace setup"],
            cwd=str(workspace), capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        print("ERROR=git_failed")
        print(f"ERROR_DETAIL={e.stderr.strip()}", flush=True)
        return 1

    # If name and visibility provided, create GitHub remote
    if name and visibility:
        flag = f"--{visibility}" if visibility in ("public", "private") else "--private"
        try:
            result = subprocess.run(
                ["gh", "repo", "create", name, flag,
                 "--description", f"Workspace for {name}"],
                cwd=str(workspace), capture_output=True, text=True, check=True,
            )
            # Extract URL from gh output
            repo_url = result.stdout.strip()
            if not repo_url:
                repo_url = f"https://github.com/{name}"

            subprocess.run(
                ["git", "remote", "add", "origin", f"git@github.com:{name}.git"],
                cwd=str(workspace), capture_output=True, text=True, check=True,
            )
            subprocess.run(
                ["git", "push", "-u", "origin", "main"],
                cwd=str(workspace), capture_output=True, text=True, check=True,
            )
            print(f"REPO_URL={repo_url}")
        except subprocess.CalledProcessError as e:
            print("ERROR=gh_failed")
            print(f"ERROR_DETAIL={e.stderr.strip()}")
            return 1
    else:
        # Git init succeeded, no remote requested
        print("REPO_URL=")

    return 0


# -- Dispatcher --------------------------------------------------------------

def cmd_write_marker(workspace: Path, params: dict[str, str]) -> int:
    project_str = params.get("project", "")
    if not project_str:
        print("ERROR=missing_project")
        print("ERROR_DETAIL=project= is required")
        return 1
    project = Path(project_str)
    if not project.is_dir():
        print("ERROR=project_not_found")
        print(f"ERROR_DETAIL={project}")
        return 1
    err = validate_workspace_location(workspace)
    if err:
        print(f"ERROR=nested_workspace")
        print(f"ERROR_DETAIL={err}")
        return 1
    write_workspace_marker(workspace, project)
    print(f"MARKER={workspace / '.workspace'}")
    return 0


SUBCOMMANDS = {
    "create-dirs": lambda ws, _p: cmd_create_dirs(ws),
    "create-indexes": lambda ws, _p: cmd_create_indexes(ws),
    "create-stubs": lambda ws, _p: cmd_create_stubs(ws),
    "init-repo": cmd_init_repo,
    "write-marker": cmd_write_marker,
}


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1

    subcmd = sys.argv[1]
    if subcmd not in SUBCOMMANDS:
        print("ERROR=unknown_subcommand")
        print(f"ERROR_DETAIL=Unknown subcommand: {subcmd}. "
              f"Valid: {', '.join(sorted(SUBCOMMANDS))}", flush=True)
        return 1

    workspace = Path(sys.argv[2]).resolve()
    params = parse_args(sys.argv[3:])

    return SUBCOMMANDS[subcmd](workspace, params)


if __name__ == "__main__":
    sys.exit(main())
