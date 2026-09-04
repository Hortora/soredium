"""
Topology resolver — determines project layout from CWD.

One function, one code path. Returns a Topology dataclass consumed by
ctx.py and work_state.py. No fallback chains — the Topology object
contains all resolved paths.

Layouts:
  single — no workspace (workspace == project)
  dual   — project + workspace via wksp/proj symlinks
  slot   — multi-repo clone-based workspace with .slot file
"""
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


def _run(*cmd: str, cwd: str | None = None) -> str:
    return subprocess.run(
        list(cmd), capture_output=True, text=True, cwd=cwd
    ).stdout.strip()


def _git_root(path: str | Path) -> str | None:
    result = _run("git", "-C", str(path), "rev-parse", "--show-toplevel")
    return result or None


@dataclass
class Topology:
    layout: Literal["single", "dual", "slot"]
    project: Path
    workspace: Path
    workspace_root: Path
    slot_dir: Path | None
    primary_repo: str | None
    in_worktree: bool
    main_worktree_root: Path | None


def _resolve_symlink_target(symlink: Path) -> str | None:
    """Resolve a symlink to a path inside a git repository.

    Existing target: returns the target path (even subdirectories).
    Dangling target: walks up to the nearest git root.
    Outside any git repo: returns None.
    """
    if symlink.exists():
        resolved = symlink.resolve()
        if (resolved / ".git").exists() or (resolved / ".git").is_file():
            return str(resolved)
        candidate = resolved.parent
        while candidate != candidate.parent:
            if (candidate / ".git").exists() or (candidate / ".git").is_file():
                return str(resolved)
            candidate = candidate.parent
        return None
    if not symlink.is_symlink():
        return None
    raw_target = Path(os.readlink(symlink))
    if not raw_target.is_absolute():
        raw_target = (symlink.parent / raw_target).resolve()
    candidate = raw_target
    while candidate != candidate.parent:
        if candidate.is_dir() and (
            (candidate / ".git").exists() or (candidate / ".git").is_file()
        ):
            return str(candidate)
        candidate = candidate.parent
    return None


def _detect_slot(project: Path) -> tuple[Path | None, str | None]:
    """Structural slot detection — requires .slot file in parent."""
    slot_dir = project.parent
    slot_file = slot_dir / ".slot"
    if not slot_file.exists():
        return None, None
    _slot_mod_dir = Path(__file__).parent.parent / "work-slot"
    if str(_slot_mod_dir) not in sys.path:
        sys.path.insert(0, str(_slot_mod_dir))
    from slot_metadata import parse_slot_md
    info = parse_slot_md(slot_dir)
    repos = info.get("repos", [])
    primary = repos[0] if repos else None
    return slot_dir, primary


def resolve(cwd: str | None = None) -> Topology:
    if cwd is None:
        cwd = os.getcwd()

    cwd_root = _run("git", "rev-parse", "--show-toplevel", cwd=cwd)
    if not cwd_root:
        raise RuntimeError("Not in a git repository")

    wt_output = _run("git", "worktree", "list", "--porcelain", cwd=cwd)
    main_wt_root = None
    if wt_output:
        for line in wt_output.splitlines():
            if line.startswith("worktree "):
                main_wt_root = line[len("worktree "):]
                break

    in_worktree = bool(
        main_wt_root
        and Path(main_wt_root).resolve() != Path(cwd_root).resolve()
    )
    main_worktree_path = Path(main_wt_root) if in_worktree and main_wt_root else None

    # In a worktree, check CWD first — slot worktrees have their own wksp
    if in_worktree:
        cwd_wksp = Path(cwd_root) / "wksp"
        symlink_root = Path(cwd_root) if (cwd_wksp.is_symlink() and cwd_wksp.is_dir()) else main_worktree_path
    else:
        symlink_root = Path(cwd_root)
    proj_symlink = symlink_root / "proj"
    wksp_symlink = symlink_root / "wksp"

    project_str = cwd_root
    workspace_str = cwd_root
    _cwd_resolved = Path(cwd_root).resolve()
    if proj_symlink.exists() or proj_symlink.is_symlink():
        resolved = _resolve_symlink_target(proj_symlink)
        if resolved and Path(resolved).resolve() != _cwd_resolved:
            workspace_str = cwd_root
            project_str = resolved
        elif (wksp_symlink.exists() or wksp_symlink.is_symlink()):
            resolved = _resolve_symlink_target(wksp_symlink)
            if resolved:
                project_str = cwd_root
                workspace_str = resolved
    elif wksp_symlink.exists() or wksp_symlink.is_symlink():
        resolved = _resolve_symlink_target(wksp_symlink)
        if resolved:
            project_str = cwd_root
            workspace_str = resolved

    project = Path(project_str).resolve()
    workspace = Path(workspace_str).resolve()

    if workspace == project:
        workspace_root = project
    else:
        ws_root_str = _git_root(workspace)
        workspace_root = Path(ws_root_str).resolve() if ws_root_str else workspace

    slot_dir, primary_repo = _detect_slot(project)
    if slot_dir:
        layout: Literal["single", "dual", "slot"] = "slot"
    elif workspace != project:
        layout = "dual"
    else:
        layout = "single"

    return Topology(
        layout=layout,
        project=project,
        workspace=workspace,
        workspace_root=workspace_root,
        slot_dir=slot_dir,
        primary_repo=primary_repo,
        in_worktree=in_worktree,
        main_worktree_root=main_worktree_path,
    )


def find_design_file(name: str, topo: Topology) -> Path | None:
    """Search all relevant locations for a design file (.plan, .meta).

    Order: workspace, workspace_root, slot_dir — checking root <name>
    then design/<name> at each level. Falls back to primary repo's workspace
    in multi-repo slots.
    """
    candidates = [topo.workspace, topo.workspace_root]
    if topo.slot_dir:
        candidates.append(topo.slot_dir)

    for base in candidates:
        if base is None:
            continue
        for sub in [base / name, base / "design" / name]:
            if sub.exists():
                return sub

    if topo.slot_dir and topo.primary_repo:
        primary_wksp = topo.slot_dir / topo.primary_repo / "wksp"
        if primary_wksp.is_symlink():
            target = primary_wksp.resolve()
            for path in [target / name, target / "design" / name]:
                if path.exists():
                    return path
            root = _git_root(target)
            if root and str(Path(root).resolve()) != str(target.resolve()):
                root_p = Path(root)
                for path in [root_p / name, root_p / "design" / name]:
                    if path.exists():
                        return path
    return None
