#!/usr/bin/env python3
"""
Context resolver for soredium workspace-aware skills.
Prints KEY=value lines consumed by work-start, work-end, work-pause, work-resume, handover etc.
Works whether Claude opened in the workspace or the project repo.

  project repo  has wksp/ → workspace
  workspace     has proj/ → project
  single-repo   has neither (no separate workspace)

Importable: call resolve(cwd=None) to get a dict instead of printed output.
"""
import os, subprocess, re, sys
from pathlib import Path

def run(*cmd, cwd=None):
    return subprocess.run(list(cmd), capture_output=True, text=True, cwd=cwd).stdout.strip()

def check_file(*paths):
    return "yes" if any(p.exists() for p in paths) else "no"

def check_dir(*paths):
    return "yes" if any(p.is_dir() for p in paths) else "no"

def _resolve_symlink_target(symlink: Path) -> str | None:
    """Resolve a symlink to a path inside a git repository.

    When the target exists: returns the target path itself (even if it is
    a subdirectory, not the git root).  This preserves correct artifact
    paths — e.g. slot workspace clones where wksp → ../work/engine and
    .meta lives at work/engine/design/.meta, not work/design/.meta.

    When the target is dangling: walks up to find the nearest git root
    (the target path does not exist, so the git root is the best we can
    return).

    Returns None when the path is not inside any git repository.
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
        if candidate.is_dir() and ((candidate / ".git").exists() or (candidate / ".git").is_file()):
            return str(candidate)
        candidate = candidate.parent
    return None


def resolve(cwd=None) -> dict[str, str]:
    """Resolve all workspace context. Returns a dict of KEY -> value strings."""
    if cwd is None:
        cwd = os.getcwd()

    cwd_root = run("git", "rev-parse", "--show-toplevel", cwd=cwd)
    if not cwd_root:
        raise RuntimeError("Not in a git repository")

    _wt_output = run("git", "worktree", "list", "--porcelain", cwd=cwd)
    _main_wt_root = None
    if _wt_output:
        for _line in _wt_output.splitlines():
            if _line.startswith("worktree "):
                _main_wt_root = _line[len("worktree "):]
                break

    in_worktree = bool(
        _main_wt_root
        and Path(_main_wt_root).resolve() != Path(cwd_root).resolve()
    )
    main_worktree_root = _main_wt_root if in_worktree else None

    symlink_root = Path(main_worktree_root) if in_worktree else Path(cwd_root)
    proj_symlink = symlink_root / "proj"
    wksp_symlink = symlink_root / "wksp"

    if proj_symlink.exists() or proj_symlink.is_symlink():
        resolved = _resolve_symlink_target(proj_symlink)
        if resolved:
            workspace = cwd_root
            project = resolved
        else:
            workspace = cwd_root
            project = cwd_root
    elif wksp_symlink.exists() or wksp_symlink.is_symlink():
        resolved = _resolve_symlink_target(wksp_symlink)
        if resolved:
            project = cwd_root
            workspace = resolved
        else:
            workspace = cwd_root
            project = cwd_root
    else:
        workspace = cwd_root
        project = cwd_root

    single_repo = workspace == project

    claude_md = Path(project) / "CLAUDE.md"
    claude_text = claude_md.read_text() if claude_md.exists() else ""
    claude_text_clean = claude_text.replace("**", "")

    m = re.search(r"GitHub repo:\s*(\S+)", claude_text_clean)
    owner_repo = m.group(1) if m else ""

    m = re.search(r"Project base branch:\s*`([^`]+)`", claude_text_clean)
    base_branch = m.group(1) if m else "main"

    meta_path = Path(workspace) / "design" / ".meta"
    meta = {}
    if meta_path.exists():
        for line in meta_path.read_text().splitlines():
            if ": " in line:
                k, _, v = line.partition(": ")
                meta[k.strip()] = v.strip()

    workspace_branch = run("git", "-C", workspace, "branch", "--show-current")
    project_branch = run("git", "-C", project, "branch", "--show-current") if not single_repo else workspace_branch
    current_branch = workspace_branch

    from lifecycle import read_state as _read_state, is_transient as _is_transient
    _meta_state_raw = _read_state(meta_path)
    _meta_state = _meta_state_raw or ""
    _meta_is_transient = "yes" if (_meta_state and _is_transient(_meta_state)) else "no"

    branch_name = meta.get("branch", "")
    project_sha = meta.get("project-sha", "")
    issue_n = meta.get("issue", "")
    issue_repo = meta.get("issue-repo", owner_repo)
    covers = meta.get("covers", issue_n)

    branch_mismatch = "no"
    mismatch_detail = ""
    if not single_repo and workspace_branch != project_branch:
        branch_mismatch = "yes"
        mismatch_detail = f"workspace={workspace_branch} project={project_branch}"
    if branch_name and workspace_branch != branch_name and workspace_branch != base_branch:
        if branch_mismatch == "no":
            branch_mismatch = "yes"
            mismatch_detail = f"meta={branch_name} actual={workspace_branch}"

    inferred_issue = ""
    if not issue_n and current_branch:
        m_issue = re.search(r'issue-(\d+)', current_branch)
        if m_issue:
            inferred_issue = m_issue.group(1)

    cwd_path = Path(cwd)
    claude_md_cwd = cwd_path / "CLAUDE.md"
    cwd_claude_text = claude_md_cwd.read_text() if claude_md_cwd.exists() else ""

    claude_ok = "yes" if "## Project Type" in cwd_claude_text else "no"

    wksp_ok_symlink = (cwd_path / "wksp").is_symlink() and (cwd_path / "wksp").is_dir()
    proj_ok_symlink = (cwd_path / "proj").is_symlink() and (cwd_path / "proj").is_dir()
    if in_worktree and main_worktree_root:
        _main = Path(main_worktree_root)
        wksp_ok_symlink = wksp_ok_symlink or ((_main / "wksp").is_symlink() and (_main / "wksp").is_dir())
        proj_ok_symlink = proj_ok_symlink or ((_main / "proj").is_symlink() and (_main / "proj").is_dir())
    wksp_declined = "workspace: declined" in cwd_claude_text
    workspace_ok = "yes" if (wksp_ok_symlink or proj_ok_symlink or wksp_declined) else "no"

    clean_claude_text = cwd_claude_text.replace("**", "")
    if "Issue tracking: enabled" in clean_claude_text:
        issues_status = "enabled"
    elif "Issue tracking: declined" in clean_claude_text:
        issues_status = "declined"
    else:
        issues_status = "absent"

    github_project = ""
    m = re.search(r"GitHub project:\s*(\S+)", clean_claude_text)
    if m:
        github_project = m.group(1)

    project_type = ""
    maturity_stage = "pre-release"
    if "## Project Type" in cwd_claude_text:
        m = re.search(r"(?:^type:\s*|^\*\*Type:\*\*\s*)(.+)", cwd_claude_text, re.MULTILINE)
        if m:
            project_type = re.sub(r'\s*,\s*', ',', m.group(1).strip())
        m = re.search(r"(?:^stage:\s*|^\*\*Stage:\*\*\s*)(\S+)", cwd_claude_text, re.MULTILINE)
        if m:
            maturity_stage = m.group(1).lower()

    _epic_dir = Path(__file__).parent.parent / "work-slot"
    if str(_epic_dir) not in sys.path:
        sys.path.insert(0, str(_epic_dir))
    from epic_manager import detect as _epic_detect
    from slot_manager import is_slot_path as _is_slot_path
    from plan_manager import detect as _plan_detect

    _plan_info = _plan_detect(Path(workspace))
    if _plan_info is None and _is_slot_path(str(project)):
        _plan_info = _plan_detect(Path(project))

    _has_plan = _plan_info is not None
    _plan_path = _plan_info["plan_path"] if _plan_info else ""
    _plan_active_issue = str(_plan_info["active_issue"]) if _plan_info and _plan_info["active_issue"] else ""
    _plan_position = ""
    _plan_batch = ""
    if _plan_info:
        completed = _plan_info.get("completed_count", 0)
        total = _plan_info.get("total_count", 0)
        _plan_position = f"{completed}/{total}" if total else ""
        _plan_batch = _plan_info.get("current_batch") or ""

    _epic_info = _epic_detect(Path(workspace))
    if _epic_info is None and _is_slot_path(str(project)):
        _epic_info = _epic_detect(Path(project))

    is_epic = _epic_info is not None
    epic_path = _epic_info["epic_path"] if _epic_info else Path("")
    _epic_batch = ""
    _epic_active_issue = ""
    if _epic_info:
        _cur = _epic_info.get("current_batch", 0)
        _tot = len(_epic_info.get("batches", []))
        _epic_batch = f"{_cur} of {_tot}" if _tot else ""
        _epic_active_issue = str(_epic_info.get("current_issue", ""))

    has_meta = "yes" if meta_path.exists() and meta else "no"
    design_repo_key = meta.get("design-repo", "")
    has_arc42stories = "yes" if (Path(project) / "ARC42STORIES.MD").exists() else "no"
    has_project_artifacts = "yes" if "## Project Artifacts" in cwd_claude_text else "no"
    workspace_declined_flag = "yes" if "workspace: declined" in cwd_claude_text else "no"

    has_platform_doc = check_file(
        Path(project) / "docs" / "PLATFORM.md",
        Path(workspace) / "docs" / "PLATFORM.md",
        Path(workspace) / "workspace" / "docs" / "PLATFORM.md",
    )

    has_protocols_dir = check_dir(
        Path(project) / "docs" / "protocols",
        Path(workspace) / "docs" / "protocols",
        Path(workspace) / "workspace" / "docs" / "protocols",
    )

    sources_path_obj = Path(project) / "SOURCES.md"
    has_sources = "yes" if sources_path_obj.exists() else "no"
    sources_path = str(sources_path_obj) if sources_path_obj.exists() else ""

    m = re.search(r"\*\*Blog directory:\*\*\s*`([^`]+)`", cwd_claude_text)
    blog_dir = m.group(1) if m else ""

    has_blog_routing = check_file(
        Path.home() / ".claude" / "blog-routing.yaml",
        Path(project) / "blog-routing.yaml",
        Path(workspace) / "blog-routing.yaml",
    )

    m = re.search(r"\*\*Name:\*\*\s*(\S+)", cwd_claude_text)
    project_name = m.group(1) if m else ""

    has_writing_style_ref = "yes" if (
        re.search(r"writing[\s_-]?style.*\.md", cwd_claude_text, re.IGNORECASE)
        or "blog-technical" in cwd_claude_text.lower()
    ) else "no"

    flyway_next_v = meta.get("flyway-next-v", "")
    meta_section_hashes = meta.get("design-section-hashes", "")

    return {
        "WORKSPACE": workspace,
        "PROJECT": project,
        "SINGLE_REPO": "yes" if single_repo else "no",
        "IN_WORKTREE": "yes" if in_worktree else "no",
        "MAIN_WORKTREE_ROOT": main_worktree_root or "",
        "OWNER_REPO": owner_repo,
        "BASE_BRANCH": base_branch,
        "CURRENT_BRANCH": current_branch,
        "PROJECT_BRANCH": project_branch,
        "BRANCH_NAME": branch_name,
        "BRANCH_MISMATCH": branch_mismatch,
        "MISMATCH_DETAIL": mismatch_detail,
        "PROJECT_SHA": project_sha,
        "ISSUE_N": issue_n,
        "ISSUE_REPO": issue_repo,
        "COVERS": covers,
        "INFERRED_ISSUE": inferred_issue,
        "CLAUDE_OK": claude_ok,
        "WORKSPACE_OK": workspace_ok,
        "ISSUES_STATUS": issues_status,
        "GITHUB_PROJECT": github_project,
        "PROJECT_TYPE": project_type,
        "MATURITY_STAGE": maturity_stage,
        "HAS_META": has_meta,
        "DESIGN_REPO_KEY": design_repo_key,
        "HAS_ARC42STORIES": has_arc42stories,
        "HAS_PROJECT_ARTIFACTS": has_project_artifacts,
        "WORKSPACE_DECLINED": workspace_declined_flag,
        "HAS_PLATFORM_DOC": has_platform_doc,
        "HAS_PROTOCOLS_DIR": has_protocols_dir,
        "HAS_SOURCES": has_sources,
        "SOURCES_PATH": sources_path,
        "BLOG_DIR": blog_dir,
        "HAS_BLOG_ROUTING": has_blog_routing,
        "PROJECT_NAME": project_name,
        "HAS_WRITING_STYLE_REF": has_writing_style_ref,
        "IS_EPIC": "yes" if is_epic else "no",
        "EPIC_PATH": str(epic_path) if is_epic else "",
        "EPIC_BATCH": _epic_batch,
        "EPIC_ACTIVE_ISSUE": _epic_active_issue,
        "FLYWAY_NEXT_V": flyway_next_v,
        "META_SECTION_HASHES": meta_section_hashes,
        "HAS_PLAN": "yes" if _has_plan else "no",
        "PLAN_PATH": _plan_path,
        "PLAN_ACTIVE_ISSUE": _plan_active_issue,
        "PLAN_POSITION": _plan_position,
        "PLAN_BATCH": _plan_batch,
        "META_STATE": _meta_state,
        "META_IS_TRANSIENT": _meta_is_transient,
    }


if __name__ == '__main__':
    try:
        result = resolve()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    for key, value in result.items():
        print(f"{key}={value}")
