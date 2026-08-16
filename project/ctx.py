#!/usr/bin/env python3
"""
Context resolver for soredium workspace-aware skills.
Prints KEY=value lines consumed by work-start, work-end, work-pause,
work-resume, handover, brief, and all lifecycle skills.

Importable: call resolve(cwd=None) to get a dict instead of printed output.

Architecture (post-#220 rewrite):
  topology.py  — resolves paths (Topology dataclass)
  work_state.py — detects lifecycle state (WorkState dataclass)
  ctx.py (this) — collects all fields from topology + work_state + CLAUDE.md
"""
import re
import sys
from pathlib import Path

_project_dir = Path(__file__).parent
if str(_project_dir) not in sys.path:
    sys.path.insert(0, str(_project_dir))

_slot_dir = Path(__file__).parent.parent / "work-slot"
if str(_slot_dir) not in sys.path:
    sys.path.insert(0, str(_slot_dir))

from topology import resolve as topo_resolve, find_design_file, _run
from work_state import detect as ws_detect


def _parse_meta(meta_path: Path) -> dict[str, str]:
    """Parse .meta file. Handles both ': ' and ':' separators."""
    meta: dict[str, str] = {}
    if not meta_path.exists():
        return meta
    for line in meta_path.read_text().splitlines():
        if ': ' in line:
            k, _, v = line.partition(': ')
            meta[k.strip()] = v.strip()
        elif ':' in line:
            k, _, v = line.partition(':')
            meta[k.strip()] = v.strip()
    return meta


def _check_file(*paths: Path) -> str:
    return "yes" if any(p.exists() for p in paths) else "no"


def _check_dir(*paths: Path) -> str:
    return "yes" if any(p.is_dir() for p in paths) else "no"


def resolve(cwd=None) -> dict[str, str]:
    """Resolve all workspace context. Returns a dict of KEY -> value strings."""
    topo = topo_resolve(cwd)

    from plan_migrate import migrate_to_root
    if topo.workspace and topo.workspace.is_dir():
        migrate_to_root(topo.workspace)

    workspace_valid = "yes"
    workspace_error = ""
    if topo.workspace and topo.workspace.is_dir() and str(topo.workspace) != str(topo.project):
        _ws_init = Path(__file__).parent.parent / "workspace-init"
        if str(_ws_init) not in sys.path:
            sys.path.insert(0, str(_ws_init))
        try:
            from workspace_create import (validate_workspace_location,
                                          validate_workspace_marker,
                                          write_workspace_marker,
                                          resolve_workspace, ensure_workspace)
            loc_err = validate_workspace_location(topo.workspace)
            if loc_err:
                correct_ws = resolve_workspace(topo.project)
                if correct_ws:
                    topo.workspace = correct_ws
                    workspace_valid = "repaired"
                    workspace_error = f"was nested — switched to {correct_ws}"
                else:
                    workspace_valid = "nested"
                    workspace_error = loc_err
            else:
                marker_err = validate_workspace_marker(topo.workspace, topo.project)
                if marker_err:
                    write_workspace_marker(topo.workspace, topo.project)
                    import subprocess as _sp2
                    _sp2.run(["git", "-C", str(topo.workspace), "add", ".workspace"],
                             capture_output=True)
                    _sp2.run(["git", "-C", str(topo.workspace), "commit", "-m",
                              "chore: add .workspace marker"],
                             capture_output=True)
                    workspace_valid = "yes"
        except ImportError:
            pass

    state = ws_detect(topo)

    # CLAUDE.md — ALL fields from topo.project (F2/F5 fix)
    claude_md = topo.project / "CLAUDE.md"
    claude_text = claude_md.read_text() if claude_md.exists() else ""
    claude_text_clean = claude_text.replace("**", "")

    m = re.search(r"GitHub repo:\s*(\S+)", claude_text_clean)
    owner_repo = m.group(1) if m else ""

    m = re.search(r"Project base branch:\s*`([^`]+)`", claude_text_clean)
    base_branch = m.group(1) if m else "main"

    claude_ok = "yes" if "## Project Type" in claude_text else "no"

    project_type = ""
    maturity_stage = "pre-release"
    if "## Project Type" in claude_text:
        m = re.search(r"(?:^type:\s*|^\*\*Type:\*\*\s*)(.+)", claude_text, re.MULTILINE)
        if m:
            project_type = re.sub(r'\s*,\s*', ',', m.group(1).strip())
        m = re.search(r"(?:^stage:\s*|^\*\*Stage:\*\*\s*)(\S+)", claude_text, re.MULTILINE)
        if m:
            maturity_stage = m.group(1).lower()

    issues_status = "absent"
    if "Issue tracking: enabled" in claude_text_clean:
        issues_status = "enabled"
    elif "Issue tracking: declined" in claude_text_clean:
        issues_status = "declined"

    github_project = ""
    m = re.search(r"GitHub project:\s*(\S+)", claude_text_clean)
    if m:
        github_project = m.group(1)

    # Workspace setup checks — symlinks at CWD (not project)
    cwd_path = Path(cwd) if cwd else Path.cwd()
    wksp_ok = (cwd_path / "wksp").is_symlink() and (cwd_path / "wksp").is_dir()
    proj_ok = (cwd_path / "proj").is_symlink() and (cwd_path / "proj").is_dir()
    if topo.in_worktree and topo.main_worktree_root:
        _main = topo.main_worktree_root
        wksp_ok = wksp_ok or ((_main / "wksp").is_symlink() and (_main / "wksp").is_dir())
        proj_ok = proj_ok or ((_main / "proj").is_symlink() and (_main / "proj").is_dir())
    wksp_declined = "workspace: declined" in claude_text
    workspace_ok = "yes" if (wksp_ok or proj_ok or wksp_declined) else "no"

    # Identity — from .plan's ## State section (via plan_manager.detect)
    plan_state: dict[str, str] = {}
    if state.has_plan and state.plan_path:
        from plan_manager import detect as _plan_detect_full
        plan_p = Path(state.plan_path)
        detect_base = plan_p.parent.parent if plan_p.parent.name == "design" else plan_p.parent
        plan_info_full = _plan_detect_full(detect_base)
        if plan_info_full:
            plan_state = plan_info_full.get("state", {})

    # Fallback to .meta if still exists (pre-migration branch)
    if not plan_state:
        meta_path = find_design_file(".meta", topo)
        if meta_path:
            meta_fallback = _parse_meta(meta_path)
            plan_state = meta_fallback

    branch_name = plan_state.get("branch", "")
    project_sha = plan_state.get("project-sha", "")
    covers = plan_state.get("covers", "")
    issue_n = covers.split(",")[0].strip() if covers else ""
    issue_repo = plan_state.get("issue-repo", owner_repo)
    design_repo_key = plan_state.get("design-repo", "")
    flyway_next_v = plan_state.get("flyway-next-v", "")
    meta_section_hashes = plan_state.get("design-section-hashes", "")

    has_meta = "yes" if plan_state else "no"

    # Branch detection
    workspace = str(topo.workspace)
    project = str(topo.project)
    single_repo = topo.workspace == topo.project

    workspace_branch = _run("git", "-C", workspace, "branch", "--show-current")
    project_branch = _run("git", "-C", project, "branch", "--show-current") if not single_repo else workspace_branch
    current_branch = workspace_branch

    # Branch mismatch — guard against empty strings from git failure (F6)
    branch_mismatch = "no"
    mismatch_detail = ""
    if not single_repo and workspace_branch and project_branch and workspace_branch != project_branch:
        branch_mismatch = "yes"
        mismatch_detail = f"workspace={workspace_branch} project={project_branch}"
    if branch_name and workspace_branch and workspace_branch != branch_name and workspace_branch != base_branch:
        if branch_mismatch == "no":
            branch_mismatch = "yes"
            mismatch_detail = f"meta={branch_name} actual={workspace_branch}"

    inferred_issue = ""
    if not issue_n and current_branch:
        m_issue = re.search(r'issue-(\d+)', current_branch)
        if m_issue:
            inferred_issue = m_issue.group(1)

    # File existence — check project, workspace, AND workspace_root (F5)
    has_arc42stories = "yes" if (topo.project / "ARC42STORIES.MD").exists() else "no"
    has_project_artifacts = "yes" if "## Project Artifacts" in claude_text else "no"
    workspace_declined_flag = "yes" if "workspace: declined" in claude_text else "no"

    has_platform_doc = _check_file(
        topo.project / "docs" / "PLATFORM.md",
        topo.workspace / "docs" / "PLATFORM.md",
        topo.workspace_root / "docs" / "PLATFORM.md",
    )

    has_protocols_dir = _check_dir(
        topo.project / "docs" / "protocols",
        topo.workspace / "docs" / "protocols",
        topo.workspace_root / "docs" / "protocols",
    )

    sources_path_obj = topo.project / "SOURCES.md"
    has_sources = "yes" if sources_path_obj.exists() else "no"
    sources_path = str(sources_path_obj) if sources_path_obj.exists() else ""

    m = re.search(r"\*\*Blog directory:\*\*\s*`([^`]+)`", claude_text)
    blog_dir = m.group(1) if m else ""

    has_blog_routing = _check_file(
        Path.home() / ".claude" / "blog-routing.yaml",
        topo.project / "blog-routing.yaml",
        topo.workspace / "blog-routing.yaml",
        topo.workspace_root / "blog-routing.yaml",
    )

    m = re.search(r"\*\*Name:\*\*\s*(\S+)", claude_text)
    project_name = m.group(1) if m else ""

    has_writing_style_ref = "yes" if (
        re.search(r"writing[\s_-]?style.*\.md", claude_text, re.IGNORECASE)
        or "blog-technical" in claude_text.lower()
    ) else "no"

    return {
        # Topology fields
        "WORKSPACE": workspace,
        "PROJECT": project,
        "SINGLE_REPO": "yes" if single_repo else "no",
        "IN_WORKTREE": "yes" if topo.in_worktree else "no",
        "MAIN_WORKTREE_ROOT": str(topo.main_worktree_root) if topo.main_worktree_root else "",
        "IN_SLOT": "yes" if topo.layout == "slot" else "no",
        "SLOT_PATH": str(topo.slot_dir / ".slot") if topo.slot_dir else "",
        # WorkState fields (F1/F3 — work/SKILL.md reads these)
        "ROUTE": state.route,
        "ON_MAIN": "yes" if state.on_main else "no",
        "STACK_DEPTH": str(state.stack_depth),
        "HAS_HANDOFF": "yes" if state.has_handoff else "no",
        "HANDOFF_PATH": state.handoff_path,
        "HAS_PLAN": "yes" if state.has_plan else "no",
        "PLAN_PATH": state.plan_path,
        "ACTIVE_ISSUE": state.active_issue,
        "PLAN_POSITION": state.plan_position,
        "PLAN_BATCH": state.plan_batch,
        "META_STATE": state.meta_state,
        "META_IS_TRANSIENT": "yes" if state.meta_is_transient else "no",
        # CLAUDE.md fields (all from topo.project)
        "OWNER_REPO": owner_repo,
        "BASE_BRANCH": base_branch,
        "CLAUDE_OK": claude_ok,
        "WORKSPACE_OK": workspace_ok,
        "ISSUES_STATUS": issues_status,
        "GITHUB_PROJECT": github_project,
        "PROJECT_TYPE": project_type,
        "MATURITY_STAGE": maturity_stage,
        "PROJECT_NAME": project_name,
        "BLOG_DIR": blog_dir,
        "HAS_BLOG_ROUTING": has_blog_routing,
        "HAS_WRITING_STYLE_REF": has_writing_style_ref,
        "HAS_PROJECT_ARTIFACTS": has_project_artifacts,
        "WORKSPACE_DECLINED": workspace_declined_flag,
        "WORKSPACE_VALID": workspace_valid,
        "WORKSPACE_ERROR": workspace_error,
        # Branch state
        "CURRENT_BRANCH": current_branch,
        "PROJECT_BRANCH": project_branch,
        "BRANCH_NAME": branch_name,
        "BRANCH_MISMATCH": branch_mismatch,
        "MISMATCH_DETAIL": mismatch_detail,
        # .meta fields
        "PROJECT_SHA": project_sha,
        "ISSUE_N": issue_n,
        "ISSUE_REPO": issue_repo,
        "COVERS": covers,
        "INFERRED_ISSUE": inferred_issue,
        "HAS_META": has_meta,
        "DESIGN_REPO_KEY": design_repo_key,
        "FLYWAY_NEXT_V": flyway_next_v,
        "META_SECTION_HASHES": meta_section_hashes,
        # File existence
        "HAS_ARC42STORIES": has_arc42stories,
        "HAS_PLATFORM_DOC": has_platform_doc,
        "HAS_PROTOCOLS_DIR": has_protocols_dir,
        "HAS_SOURCES": has_sources,
        "SOURCES_PATH": sources_path,
    }


if __name__ == '__main__':
    try:
        result = resolve()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    for key, value in result.items():
        print(f"{key}={value}")
