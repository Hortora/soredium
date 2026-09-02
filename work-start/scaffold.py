#!/usr/bin/env python3
"""
Create the workspace branch scaffold: .plan (unified) and JOURNAL.md at workspace root.

Called by work-start Step 9 after branch creation. The unified .plan file
contains both ## State (identity/lifecycle) and ## Queue (work items).
No separate .meta file is created.

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
        [plan-content=<raw content>] \\
        [force=yes]

Output (KEY=value lines):
    PLAN_PATH=/abs/path/to/.plan
    JOURNAL_PATH=/abs/path/to/JOURNAL.md
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

_slot_dir = str(Path(__file__).resolve().parent.parent / "work-slot")
if _slot_dir not in sys.path:
    sys.path.insert(0, _slot_dir)


REQUIRED = {"branch", "project-sha"}


@dataclass
class ScaffoldResult:
    plan_path: str
    journal_path: str
    created: bool


def scaffold(workspace: Path, branch: str, project_sha: str,
             issue: str = "", issue_repo: str = "", covers: str = "",
             today: str | None = None, flyway_next_v: str = "unknown",
             design_repo: str = "project",
             design_section_hashes: str = "",
             plan_content: str = "",
             force: bool = False) -> ScaffoldResult:
    """Create workspace branch scaffold: .plan and JOURNAL.md at workspace root."""
    plan_path = workspace / ".plan"
    journal_path = workspace / "JOURNAL.md"

    if not force and plan_path.exists() and journal_path.exists():
        content = plan_path.read_text()
        if "## State" in content and "\nstate:" not in content:
            lines = content.splitlines()
            patched = []
            for line in lines:
                patched.append(line)
                if line.strip() == "## State":
                    patched.append("state: active")
            plan_path.write_text("\n".join(patched) + "\n")
        return ScaffoldResult(
            plan_path=str(plan_path),
            journal_path=str(journal_path),
            created=False,
        )

    if today is None:
        today = date.today().isoformat()

    if not covers:
        covers = issue

    if plan_content:
        plan_path.write_text(plan_content)
    else:
        from plan_manager import build_plan_content, QueueItem, IssueRef

        state = {
            "branch": branch,
            "state": "scaffolded",
            "project-sha": project_sha,
            "date": today,
            "issue-repo": issue_repo,
            "covers": covers,
            "design-repo": design_repo,
            "design-section-hashes": design_section_hashes,
            "flyway-next-v": flyway_next_v,
        }

        if issue:
            items = [QueueItem(ref=IssueRef(repo=issue_repo, number=int(issue)),
                               title=f"Issue #{issue}", active=True)]
        else:
            items = []
        plan_path.write_text(build_plan_content(branch, items, today, state=state))

    journal_path.write_text(f"# Design Journal — {branch}\n")

    return ScaffoldResult(
        plan_path=str(plan_path),
        journal_path=str(journal_path),
        created=True,
    )


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

    covers = params.get("covers", "") or params.get("issue", "")
    issue_repo = params.get("issue-repo", "")
    if covers and issue_repo and _wl and params.get("skip-duplicate-check") != "yes":
        try:
            import os as _os
            _db = _os.environ.get("WORKLOG_DB")
            _conn = _wl.connect(_db) if _db else _wl.connect()
            for n in covers.split(","):
                n = n.strip()
                if n.isdigit():
                    active = _wl.check_active_work(_conn, int(n), issue_repo)
                    if active:
                        for item in active:
                            print(f"DUPLICATE_CONFLICT=#{n} active on {item['branch']} ({item['location']}) at {item['repo_path']}")
                        print("DUPLICATE=yes")
                        print(f"HINT=pass skip-duplicate-check=yes to override")
                        _conn.close()
                        return 1
            _conn.close()
        except Exception:
            pass

    try:
        result = scaffold(
            workspace=workspace,
            branch=params["branch"],
            project_sha=params["project-sha"],
            issue=params.get("issue", ""),
            issue_repo=issue_repo,
            covers=params.get("covers", ""),
            today=params.get("date"),
            flyway_next_v=params.get("flyway-next-v", "unknown"),
            design_repo=params.get("design-repo", "project"),
            design_section_hashes=params.get("design-section-hashes", ""),
            plan_content=params.get("plan-content", ""),
            force=params.get("force", "") == "yes",
        )
    except OSError as e:
        print(f"ERROR=Failed to write scaffold: {e}", file=sys.stderr)
        return 1

    print(f"PLAN_PATH={result.plan_path}")
    print(f"JOURNAL_PATH={result.journal_path}")
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
