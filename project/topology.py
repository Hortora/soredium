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
    git_root: Path
    workspace: Path
    workspace_root: Path
    slot_dir: Path | None
    primary_repo: str | None
    in_worktree: bool
    main_worktree_root: Path | None

    @property
    def is_scoped(self) -> bool:
        return self.project != self.git_root

    @property
    def scope_rel(self) -> str:
        if not self.is_scoped:
            return ""
        return str(self.project.relative_to(self.git_root))


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


def _find_symlink_up(start: Path, git_root: Path, name: str) -> Path | None:
    """Walk from start toward git_root looking for a symlink named 'name'."""
    check = start.resolve()
    root = git_root.resolve()
    while True:
        candidate = check / name
        if candidate.is_symlink():
            return candidate
        if check == root:
            break
        parent = check.parent
        if parent == check:
            break
        check = parent
    return None


def resolve(cwd: str | None = None) -> Topology:
    if cwd is None:
        cwd = os.getcwd()

    cwd_root = _run("git", "rev-parse", "--show-toplevel", cwd=cwd)
    if not cwd_root:
        raise RuntimeError("Not in a git repository")

    cwd_path = Path(cwd).resolve()
    cwd_git_root = Path(cwd_root).resolve()

    wt_output = _run("git", "worktree", "list", "--porcelain", cwd=cwd)
    main_wt_root = None
    if wt_output:
        for line in wt_output.splitlines():
            if line.startswith("worktree "):
                main_wt_root = line[len("worktree "):]
                break

    in_worktree = bool(
        main_wt_root
        and Path(main_wt_root).resolve() != cwd_git_root
    )
    main_worktree_path = Path(main_wt_root) if in_worktree and main_wt_root else None

    project_str = str(cwd_git_root)
    workspace_str = str(cwd_git_root)

    if in_worktree:
        # Worktree: check worktree root first, then main worktree
        cwd_wksp = cwd_git_root / "wksp"
        symlink_root = cwd_git_root if (cwd_wksp.is_symlink() and cwd_wksp.is_dir()) else main_worktree_path
        proj_symlink = symlink_root / "proj"
        wksp_symlink = symlink_root / "wksp"

        if proj_symlink.exists() or proj_symlink.is_symlink():
            resolved = _resolve_symlink_target(proj_symlink)
            if resolved and Path(resolved).resolve() != Path(str(symlink_root)).resolve():
                workspace_str = str(symlink_root)
                project_str = resolved
            elif wksp_symlink.exists() or wksp_symlink.is_symlink():
                resolved = _resolve_symlink_target(wksp_symlink)
                if resolved:
                    project_str = str(symlink_root)
                    workspace_str = resolved
        elif wksp_symlink.exists() or wksp_symlink.is_symlink():
            resolved = _resolve_symlink_target(wksp_symlink)
            if resolved:
                project_str = str(symlink_root)
                workspace_str = resolved
    else:
        # Non-worktree: walk up from CWD toward git root looking for symlinks
        wksp_sym = _find_symlink_up(cwd_path, cwd_git_root, "wksp")
        proj_sym = _find_symlink_up(cwd_path, cwd_git_root, "proj")

        if wksp_sym:
            resolved = _resolve_symlink_target(wksp_sym)
            if resolved:
                project_str = str(wksp_sym.parent.resolve())
                workspace_str = resolved
        elif proj_sym:
            resolved = _resolve_symlink_target(proj_sym)
            if resolved and Path(resolved).resolve() != cwd_path:
                workspace_str = str(proj_sym.parent.resolve())
                project_str = resolved
            elif not resolved:
                pass  # broken symlink — fall through to defaults

    project = Path(project_str).resolve()
    workspace = Path(workspace_str).resolve()

    if workspace == project:
        workspace_root = project
    else:
        ws_root_str = _git_root(workspace)
        workspace_root = Path(ws_root_str).resolve() if ws_root_str else workspace

    # Derive git_root from the resolved project path
    proj_git_root_str = _git_root(project)
    git_root = Path(proj_git_root_str).resolve() if proj_git_root_str else cwd_git_root

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
        git_root=git_root,
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
