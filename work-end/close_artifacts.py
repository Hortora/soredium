#!/usr/bin/env python3
"""
Unified artifact promotion, archival, issue close, and blog publish.

Replaces work-end Steps 8a-8c, 8f, 8g with a single mechanical call.
Scans workspace for artifacts, resolves routing, promotes/publishes,
writes a stamp file proving completion.

Usage:
    python3 close_artifacts.py <workspace> <project> <branch> \
      [issue-repo=<owner/repo>] [covers=<csv>]

Output (KEY=value lines):
    WORKSPACE_PROMOTED=<count>
    PROJECT_PROMOTED=<count>
    SPECS_CLEANED=<count>
    ISSUES_CLOSED=<count>
    BLOG_PUBLISHED=<count>
    BLOG_DEST=<path>
    PLANS_ARCHIVED=<count>
    STAMP=<path>

Error output:
    ERROR=<code>
    ERROR_DETAIL=<message>

Exit codes:
    0  all succeeded, stamp written
    1  fatal error (stamp NOT written)
    2  partial success (stamp NOT written)
"""

import datetime
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SKILL_ROOT = SCRIPT_DIR.parent
ROUTING_DIR = SKILL_ROOT / "project"

sys.path.insert(0, str(ROUTING_DIR))
from routing import parse_layer2, parse_layer3, resolve  # noqa: E402

sys.path.insert(0, str(SCRIPT_DIR))
from common import parse_args  # noqa: E402


def run_script(script: str, args: list[str]) -> tuple[int, dict[str, str]]:
    """Run a sibling script and parse KEY=VALUE output."""
    cmd = [sys.executable, str(SCRIPT_DIR / script)] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    output: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            output[k.strip()] = v.strip()
    if result.returncode != 0:
        for line in result.stderr.splitlines():
            print(line, file=sys.stderr)
    return result.returncode, output


def scan_artifacts(workspace: Path, branch: str) -> dict[str, list[str]]:
    """Scan workspace for promotable artifacts. Returns category → list of relative paths."""
    found: dict[str, list[str]] = {
        "specs": [],
        "adr": [],
        "blog": [],
        "snapshots": [],
        "plans": [],
    }

    specs_dir = workspace / "specs" / branch
    if specs_dir.is_dir():
        for f in specs_dir.iterdir():
            if f.suffix == ".md":
                found["specs"].append(str(f.relative_to(workspace)))

    adr_dir = workspace / "adr"
    if adr_dir.is_dir():
        for f in adr_dir.iterdir():
            if f.suffix == ".md" and f.name != "INDEX.md":
                found["adr"].append(str(f.relative_to(workspace)))

    blog_dir = workspace / "blog"
    if blog_dir.is_dir():
        for f in blog_dir.iterdir():
            if f.suffix == ".md" and f.name != "INDEX.md":
                found["blog"].append(str(f.relative_to(workspace)))

    snap_dir = workspace / "snapshots"
    if snap_dir.is_dir():
        for f in snap_dir.iterdir():
            if f.name != "INDEX.md":
                found["snapshots"].append(str(f.relative_to(workspace)))

    plans_dir = workspace / "plans"
    if plans_dir.is_dir():
        for f in plans_dir.iterdir():
            if f.is_file() and f.suffix == ".md" and f.name != "INDEX.md":
                found["plans"].append(str(f.relative_to(workspace)))

    return found


def resolve_routing(workspace: Path) -> dict[str, str]:
    """Resolve artifact routing from CLAUDE.md files."""
    global_md = Path.home() / ".claude" / "CLAUDE.md"
    workspace_md = workspace / "CLAUDE.md"

    global_text = global_md.read_text() if global_md.exists() else ""
    workspace_text = workspace_md.read_text() if workspace_md.exists() else ""

    layer2 = parse_layer2(global_text)
    layer3 = parse_layer3(workspace_text)

    routing: dict[str, str] = {}
    for artifact in ("specs", "adr", "blog", "snapshots", "plans"):
        dest, _ = resolve(artifact, layer2, layer3)
        routing[artifact] = dest
    return routing


def write_stamp(workspace: Path, branch: str, results: dict[str, str]) -> Path:
    """Write .artifacts-promoted stamp to workspace design/ on the branch."""
    stamp_path = workspace / "design" / ".artifacts-promoted"
    stamp_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"timestamp={datetime.datetime.now(datetime.timezone.utc).isoformat()}",
        f"branch={branch}",
    ]
    for key in ("workspace_promoted", "project_promoted", "specs_cleaned",
                "issues_closed", "blog_published", "plans_archived"):
        lines.append(f"{key}={results.get(key, '0')}")

    stamp_path.write_text("\n".join(lines) + "\n")

    subprocess.run(
        ["git", "-C", str(workspace), "add", str(stamp_path.relative_to(workspace))],
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(workspace), "commit", "-m",
         f"chore(work-end): artifact promotion stamp for {branch}"],
        capture_output=True,
    )

    return stamp_path


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 1

    workspace = Path(sys.argv[1])
    project = Path(sys.argv[2])
    branch = sys.argv[3]
    params = parse_args(sys.argv[4:])
    issue_repo = params.get("issue-repo", "")
    covers = params.get("covers", "")

    if not workspace.is_dir():
        print(f"ERROR=workspace_not_found")
        print(f"ERROR_DETAIL={workspace}")
        return 1
    if not project.is_dir():
        print(f"ERROR=project_not_found")
        print(f"ERROR_DETAIL={project}")
        return 1

    artifacts = scan_artifacts(workspace, branch)
    routing = resolve_routing(workspace)

    results: dict[str, str] = {}
    failures: list[str] = []

    # Batch by destination
    ws_artifacts: list[str] = []
    proj_artifacts: list[str] = []

    for category, paths in artifacts.items():
        if category == "plans":
            continue  # handled separately via archive-plans
        if not paths:
            continue
        dest = routing.get(category, "project")
        if dest == "workspace":
            ws_artifacts.extend(paths)
        else:
            proj_artifacts.extend(paths)

    # Promote to workspace main
    if ws_artifacts:
        rc, out = run_script("artifact_promote.py", [
            "to-workspace-main", str(workspace),
            f"branch={branch}",
            f"artifacts={','.join(ws_artifacts)}",
        ])
        results["workspace_promoted"] = out.get("PROMOTED", "0")
        if rc != 0:
            failures.append(f"workspace promotion: {out.get('ERROR', 'unknown')}")
    else:
        results["workspace_promoted"] = "0"

    # Promote to project
    if proj_artifacts:
        rc, out = run_script("artifact_promote.py", [
            "to-project", str(project), str(workspace),
            f"artifacts={','.join(proj_artifacts)}",
        ])
        results["project_promoted"] = out.get("PROMOTED", "0")
        project_pushed = out.get("PUSHED", "no") == "yes"
        if rc != 0:
            failures.append(f"project promotion: {out.get('ERROR', 'unknown')}")
    else:
        results["project_promoted"] = "0"
        project_pushed = True

    # Cleanup specs (only if project push succeeded and specs were promoted)
    if artifacts["specs"] and routing.get("specs", "project") == "project" and project_pushed:
        rc, out = run_script("artifact_promote.py", [
            "cleanup-specs", str(workspace), f"branch={branch}",
        ])
        results["specs_cleaned"] = out.get("CLEANED", "0")
        if rc != 0:
            failures.append(f"spec cleanup: {out.get('ERROR', 'unknown')}")
    else:
        results["specs_cleaned"] = "0"

    # Archive plans
    if artifacts["plans"]:
        rc, out = run_script("artifact_promote.py", [
            "archive-plans", str(workspace), f"branch={branch}",
        ])
        results["plans_archived"] = out.get("ARCHIVED", "0")
        if rc != 0:
            failures.append(f"plan archival: {out.get('ERROR', 'unknown')}")
    else:
        results["plans_archived"] = "0"

    # Close issues
    if issue_repo and covers:
        rc, out = run_script("artifact_promote.py", [
            "close-issues", issue_repo, f"covers={covers}",
        ])
        results["issues_closed"] = out.get("CLOSED", "0")
        if rc != 0:
            failures.append(f"issue close: {out.get('ERROR', 'unknown')}")
    else:
        results["issues_closed"] = "0"

    # Publish blog
    blog_dir = workspace / "blog"
    blog_entries = [f for f in blog_dir.glob("*.md") if f.name != "INDEX.md"] if blog_dir.is_dir() else []
    if blog_entries:
        rc, out = run_script("blog_dest.py", [str(blog_dir), branch])
        results["blog_published"] = str(len(out.get("UNPUBLISHED", "").split(",")) if out.get("UNPUBLISHED") else 0)
        results["blog_dest"] = out.get("BLOG_DEST", "")
        blog_repo = out.get("BLOG_REPO", "")
        blog_subdir = out.get("BLOG_SUBDIR", "")

        if out.get("UNPUBLISHED"):
            subprocess.run(
                ["git", "-C", blog_repo, "add", f"{blog_subdir}/"],
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", blog_repo, "commit", "-m",
                 f"chore: publish blog entries from {branch}"],
                capture_output=True,
            )
            push_result = subprocess.run(
                ["git", "-C", blog_repo, "push"],
                capture_output=True,
            )
            if push_result.returncode != 0:
                failures.append("blog push failed")

        if rc != 0:
            failures.append(f"blog publish: {out.get('ERROR', 'unknown')}")
    else:
        results["blog_published"] = "0"
        results["blog_dest"] = ""

    # Print results
    for key, value in results.items():
        print(f"{key.upper()}={value}")

    # Write stamp (only on full success)
    if failures:
        print(f"FAILURES={';'.join(failures)}")
        return 2

    stamp_path = write_stamp(workspace, branch, results)
    print(f"STAMP={stamp_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
