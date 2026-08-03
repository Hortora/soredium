#!/usr/bin/env python3
"""
Post-promotion verification: evidence-based check that artifacts landed
at their expected destination.

Run after close_artifacts.py to verify specs, ADRs, blogs, and other
artifacts actually exist where routing says they should. The LLM cannot
rationalize past files that aren't on disk.

Usage:
    python3 verify_promotion.py <workspace> <project> [scan-workspace=<path>]

Output (KEY=value lines):
    VERIFIED=yes|no
    TOTAL=N
    LANDED=N
    MISSING=N
    MISSING_LIST=<comma-separated workspace-relative paths>

Exit codes:
    0  verification ran (check VERIFIED for result)
    1  operational error (bad args, missing dirs)
"""

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SKILL_ROOT = SCRIPT_DIR.parent
ROUTING_DIR = SKILL_ROOT / "project"

sys.path.insert(0, str(ROUTING_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from workspace_artifacts import scan  # noqa: E402
from close_artifacts import resolve_routing  # noqa: E402

_DOCS_CATEGORIES = {"specs", "adr"}


def _parse_args(args):
    params = {}
    for arg in args:
        if "=" in arg:
            k, _, v = arg.partition("=")
            params[k.strip()] = v.strip()
    return params


def _expected_project_path(category: str, artifact: str) -> str:
    if category in _DOCS_CATEGORIES:
        return f"docs/{artifact}"
    return artifact


def _check_on_workspace_main(workspace: str, artifact: str) -> bool:
    r = subprocess.run(
        ["git", "-C", workspace, "cat-file", "-e", f"main:{artifact}"],
        capture_output=True,
    )
    return r.returncode == 0


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 1

    workspace = Path(sys.argv[1])
    project = Path(sys.argv[2])
    params = _parse_args(sys.argv[3:])
    scan_workspace = params.get("scan-workspace", "")

    scan_source = Path(scan_workspace) if scan_workspace else workspace

    if not workspace.is_dir():
        print(f"ERROR=workspace_not_found")
        return 1
    if not project.is_dir():
        print(f"ERROR=project_not_found")
        return 1
    if scan_workspace and not scan_source.is_dir():
        print(f"ERROR=scan_workspace_not_found")
        return 1

    artifacts = scan(scan_source)
    routing = resolve_routing(scan_source)

    total = 0
    landed = 0
    missing = []

    for category, paths in artifacts.items():
        if category == "plans":
            continue
        if not paths:
            continue

        dest = routing.get(category, "project")

        for artifact in paths:
            total += 1

            if dest == "workspace":
                if _check_on_workspace_main(str(workspace), artifact):
                    landed += 1
                else:
                    missing.append(artifact)
            else:
                expected = _expected_project_path(category, artifact)
                if (project / expected).exists():
                    landed += 1
                else:
                    missing.append(artifact)

    verified = "yes" if not missing else "no"
    print(f"VERIFIED={verified}")
    print(f"TOTAL={total}")
    print(f"LANDED={landed}")
    print(f"MISSING={len(missing)}")
    if missing:
        print(f"MISSING_LIST={','.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
