#!/usr/bin/env python3
"""
Create the workspace branch scaffold: design/.meta and design/JOURNAL.md.

Called by work-start Step 9 after branch creation. Replaces mkdir + heredoc
blocks that trigger Claude Code permission prompts.

Usage:
    python3 ~/.claude/skills/work-start/scaffold.py \\
        <workspace_path> \\
        branch=<name> \\
        project-sha=<sha> \\
        date=<YYYY-MM-DD> \\
        [issue=<N>] \\
        [issue-repo=<owner/repo>] \\
        [covers=<N,M,...>] \\
        [flyway-next-v=<N|none|unknown>] \\
        [design-repo=<workspace|project|cross-repo:name>] \\
        [design-section-hashes=<pipe-sep-pairs>] \\
        [force=yes]

Output (KEY=value lines):
    META_PATH=/abs/path/to/design/.meta
    JOURNAL_PATH=/abs/path/to/design/JOURNAL.md
    CREATED=yes|no   (no = files already existed and were left unchanged)

Exit codes:
    0  success
    1  missing required args or I/O error
"""

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))
try:
    import worklog as _wl
except ImportError:
    _wl = None


REQUIRED = {"branch", "project-sha"}


# ---------------------------------------------------------------------------
# Library API — typed interface for command layer
# ---------------------------------------------------------------------------

@dataclass
class ScaffoldResult:
    meta_path: str
    journal_path: str
    plan_path: str | None
    created: bool


def scaffold(workspace: Path, branch: str, project_sha: str,
             issue: str = "", issue_repo: str = "", covers: str = "",
             today: str | None = None, flyway_next_v: str = "unknown",
             design_repo: str = "project",
             design_section_hashes: str = "",
             plan: bool = False, plan_content: str = "",
             force: bool = False) -> ScaffoldResult:
    """Create workspace branch scaffold: design/.meta and design/JOURNAL.md."""
    design_dir = workspace / "design"
    design_dir.mkdir(parents=True, exist_ok=True)

    meta_path = design_dir / ".meta"
    journal_path = design_dir / "JOURNAL.md"

    if not force and meta_path.exists() and journal_path.exists():
        return ScaffoldResult(
            meta_path=str(meta_path),
            journal_path=str(journal_path),
            plan_path=str(design_dir / ".plan") if (design_dir / ".plan").exists() else None,
            created=False,
        )

    if today is None:
        today = date.today().isoformat()

    if not covers:
        covers = issue

    meta_lines = [
        f"branch: {branch}",
        f"state: scaffolded",
        f"project-sha: {project_sha}",
        f"date: {today}",
        f"issue: {issue}",
        f"issue-repo: {issue_repo}",
        f"covers: {covers}",
        f"flyway-next-v: {flyway_next_v}",
        f"design-repo: {design_repo}",
        f"design-section-hashes: {design_section_hashes}",
    ]
    if plan:
        meta_lines.append("plan: yes")

    meta_path.write_text("\n".join(meta_lines) + "\n")
    journal_path.write_text(f"# Design Journal — {branch}\n")

    result_plan_path: str | None = None
    if plan:
        plan_file = design_dir / ".plan"
        if plan_content:
            plan_file.write_text(plan_content)
        elif not plan_file.exists():
            plan_file.write_text(
                f"# Work Plan — {branch}\n\n"
                f"## Queue\n"
                f"(empty — issues created during design)\n\n"
                f"## Session State\n"
                f"Started: {today}\n"
            )
        result_plan_path = str(plan_file)

    return ScaffoldResult(
        meta_path=str(meta_path),
        journal_path=str(journal_path),
        plan_path=result_plan_path,
        created=True,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def parse_args(args: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for arg in args:
        if "=" in arg:
            k, _, v = arg.partition("=")
            result[k.strip()] = v.strip()
    return result


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1

    workspace = Path(sys.argv[1]).resolve()
    params = parse_args(sys.argv[2:])

    missing = REQUIRED - params.keys()
    if missing:
        print(f"ERROR=Missing required params: {', '.join(sorted(missing))}", file=sys.stderr)
        return 1

    if not workspace.is_dir():
        print(f"ERROR=Workspace path does not exist: {workspace}", file=sys.stderr)
        return 1

    try:
        result = scaffold(
            workspace=workspace,
            branch=params["branch"],
            project_sha=params["project-sha"],
            issue=params.get("issue", ""),
            issue_repo=params.get("issue-repo", ""),
            covers=params.get("covers", ""),
            today=params.get("date"),
            flyway_next_v=params.get("flyway-next-v", "unknown"),
            design_repo=params.get("design-repo", "project"),
            design_section_hashes=params.get("design-section-hashes", ""),
            plan=params.get("plan", "") == "yes",
            plan_content=params.get("plan-content", ""),
            force=params.get("force", "") == "yes",
        )
    except OSError as e:
        print(f"ERROR=Failed to write scaffold: {e}", file=sys.stderr)
        return 1

    print(f"META_PATH={result.meta_path}")
    print(f"JOURNAL_PATH={result.journal_path}")
    if result.plan_path:
        print(f"PLAN_PATH={result.plan_path}")
    print(f"CREATED={'yes' if result.created else 'no'}")

    if _wl and result.created:
        try:
            import os as _os
            _db_path = _os.environ.get("WORKLOG_DB")
            _conn = _wl.connect(_db_path) if _db_path else _wl.connect()
            issue_num = int(params.get("issue", "0") or "0")
            issue_repo_str = params.get("issue-repo", "")
            _wl.record_work_start(
                _conn, params["branch"], str(workspace),
                issue_number=issue_num,
                issue_repo=issue_repo_str,
                covers=params.get("covers", ""),
            )
            if issue_num > 0:
                _wl.record_issue_activate(
                    _conn, params["branch"], str(workspace),
                    issue_number=issue_num,
                    issue_repo=issue_repo_str,
                )
            _conn.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
