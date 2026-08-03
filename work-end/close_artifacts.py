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
from workspace_artifacts import scan as _scan_workspace  # noqa: E402


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


def scan_artifacts(workspace: Path) -> dict[str, list[str]]:
    """Scan workspace for promotable artifacts. Returns category -> list of relative paths."""
    return _scan_workspace(workspace)


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
    for key in ("workspace_promoted", "project_promoted",
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
    scan_workspace_path = params.get("scan-workspace", "")

    if scan_workspace_path:
        scan_source = Path(scan_workspace_path)
        if not scan_source.is_dir():
            print("ERROR=scan_workspace_not_found")
            print(f"ERROR_DETAIL={scan_workspace_path}")
            return 1
    else:
        scan_source = workspace

    if not workspace.is_dir():
        print(f"ERROR=workspace_not_found")
        print(f"ERROR_DETAIL={workspace}")
        return 1
    if not project.is_dir():
        print(f"ERROR=project_not_found")
        print(f"ERROR_DETAIL={project}")
        return 1

    artifacts = scan_artifacts(scan_source)
    routing = resolve_routing(scan_source)

    results: dict[str, str] = {}
    failures: list[str] = []

    # Batch by destination — specs/adr need docs/ prefix when routed to project
    ws_artifacts: list[str] = []
    proj_artifacts: list[str] = []
    proj_docs_artifacts: list[str] = []

    _docs_categories = {"specs", "adr"}

    for category, paths in artifacts.items():
        if category == "plans":
            continue  # handled separately via archive-plans
        if not paths:
            continue
        dest = routing.get(category, "project")
        if dest == "workspace":
            ws_artifacts.extend(paths)
        elif category in _docs_categories:
            proj_docs_artifacts.extend(paths)
        else:
            proj_artifacts.extend(paths)

    # Promote to workspace main
    if ws_artifacts:
        ws_args = [
            "to-workspace-main", str(workspace),
            f"branch={branch}",
            f"artifacts={','.join(ws_artifacts)}",
        ]
        if scan_source != workspace:
            ws_args.append(f"source-dir={scan_source}")
        rc, out = run_script("artifact_promote.py", ws_args)
        results["workspace_promoted"] = out.get("PROMOTED", "0")
        if rc != 0:
            failures.append(f"workspace promotion: {out.get('ERROR', 'unknown')}")
        elif out.get("PROMOTED", "0") == "0":
            skipped = out.get("SKIPPED_PATHS", ",".join(ws_artifacts))
            failures.append(f"workspace promotion: all artifacts skipped ({skipped})")
        if out.get("PUSHED") == "failed":
            failures.append(f"workspace push failed: {out.get('PUSH_ERROR', 'unknown')}")
        if out.get("PUSH_VERIFIED") == "failed":
            missing = out.get("PUSH_VERIFY_MISSING", "unknown")
            failures.append(f"workspace push verification failed: artifacts not on origin/main ({missing})")
    else:
        results["workspace_promoted"] = "0"

    # Promote to project (no prefix — blog, snapshots, etc.)
    project_promoted_total = 0
    read_source = str(scan_source) if scan_source != workspace else str(workspace)

    if proj_artifacts:
        rc, out = run_script("artifact_promote.py", [
            "to-project", str(project), read_source,
            f"artifacts={','.join(proj_artifacts)}",
        ])
        project_promoted_total += int(out.get("PROMOTED", "0"))
        if rc != 0:
            failures.append(f"project promotion: {out.get('ERROR', 'unknown')}")
        elif out.get("PROMOTED", "0") == "0":
            skipped = out.get("SKIPPED_PATHS", ",".join(proj_artifacts))
            failures.append(f"project promotion: all artifacts skipped ({skipped})")
        if out.get("PUSHED") == "failed":
            failures.append(f"project push failed: {out.get('PUSH_ERROR', 'unknown')}")
        if out.get("PUSH_VERIFIED") == "failed":
            missing = out.get("PUSH_VERIFY_MISSING", "unknown")
            failures.append(f"project push verification failed: artifacts not on origin/main ({missing})")

    # Promote specs/adr to project with docs/ prefix
    if proj_docs_artifacts:
        rc, out = run_script("artifact_promote.py", [
            "to-project", str(project), read_source,
            f"artifacts={','.join(proj_docs_artifacts)}",
            "dest-prefix=docs/",
        ])
        project_promoted_total += int(out.get("PROMOTED", "0"))
        if rc != 0:
            failures.append(f"project docs promotion: {out.get('ERROR', 'unknown')}")
        elif out.get("PROMOTED", "0") == "0":
            skipped = out.get("SKIPPED_PATHS", ",".join(proj_docs_artifacts))
            failures.append(f"project docs promotion: all artifacts skipped ({skipped})")
        if out.get("PUSHED") == "failed":
            failures.append(f"project push failed: {out.get('PUSH_ERROR', 'unknown')}")
        if out.get("PUSH_VERIFIED") == "failed":
            missing = out.get("PUSH_VERIFY_MISSING", "unknown")
            failures.append(f"project push verification failed: artifacts not on origin/main ({missing})")

    results["project_promoted"] = str(project_promoted_total)

    # Archive plans
    if artifacts["plans"]:
        plan_args = ["archive-plans", str(workspace), f"branch={branch}"]
        if scan_source != workspace:
            plan_args.append(f"source-dir={scan_source}")
        rc, out = run_script("artifact_promote.py", plan_args)
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
    if artifacts["blog"]:
        blog_dir = scan_source / "blog"
        rc, out = run_script("blog_dest.py", [str(blog_dir), branch])
        unpublished = [x for x in out.get("UNPUBLISHED", "").split(",") if x.strip()]
        results["blog_published"] = str(len(unpublished))
        results["blog_dest"] = out.get("BLOG_DEST", "")
        blog_repo = out.get("BLOG_REPO", "")
        blog_subdir = out.get("BLOG_SUBDIR", "")

        if unpublished and blog_repo:
            blog_branch_rc = subprocess.run(
                ["git", "-C", blog_repo, "branch", "--show-current"],
                capture_output=True, text=True,
            )
            blog_branch = blog_branch_rc.stdout.strip() if blog_branch_rc.returncode == 0 else ""
            if blog_branch and blog_branch != "main":
                switch_rc = subprocess.run(
                    ["git", "-C", blog_repo, "checkout", "main"],
                    capture_output=True,
                )
                if switch_rc.returncode != 0:
                    failures.append(f"blog dest not on main ({blog_branch}), checkout failed")

            add_rc = subprocess.run(
                ["git", "-C", blog_repo, "add", f"{blog_subdir}/"],
                capture_output=True,
            )
            if add_rc.returncode != 0:
                failures.append("blog git add failed")
            else:
                commit_rc = subprocess.run(
                    ["git", "-C", blog_repo, "commit", "-m",
                     f"chore: publish blog entries from {branch}"],
                    capture_output=True,
                )
                if commit_rc.returncode != 0 and b"nothing to commit" not in commit_rc.stderr and b"nothing to commit" not in commit_rc.stdout:
                    failures.append("blog commit failed")
                else:
                    push_rc = subprocess.run(
                        ["git", "-C", blog_repo, "push"],
                        capture_output=True,
                    )
                    if push_rc.returncode != 0:
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
