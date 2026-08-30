#!/usr/bin/env python3
"""
check_duplicate_work.py — Detect active work on the same issue before starting new work.

Called by work-start, plan_manager append, and slot creation. Queries the
worklog for active or paused work items covering the given issue. Output
is KEY=VALUE lines for the caller to parse.

Usage:
    python3 scripts/check_duplicate_work.py <issue_repo> issues=<N[,M,...]>

Output:
    DUPLICATE=yes|no
    ACTIVE_BRANCHES=branch1,branch2      (only when DUPLICATE=yes)
    CONFLICTS=N:branch:location:path,... (only when DUPLICATE=yes)

Exit codes:
    0  always (caller decides whether to block or warn)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import worklog


def main() -> None:
    if len(sys.argv) < 3:
        print("DUPLICATE=no")
        return

    issue_repo = sys.argv[1]
    issues_raw = ""
    for arg in sys.argv[2:]:
        if arg.startswith("issues="):
            issues_raw = arg.split("=", 1)[1]

    if not issues_raw:
        print("DUPLICATE=no")
        return

    issue_numbers = []
    for n in issues_raw.split(","):
        n = n.strip()
        if n.isdigit():
            issue_numbers.append(int(n))

    if not issue_numbers:
        print("DUPLICATE=no")
        return

    import os
    db_path = os.environ.get("WORKLOG_DB")
    try:
        conn = worklog.connect(db_path)
    except Exception:
        print("DUPLICATE=no")
        print("WARN=worklog_unavailable")
        return

    conflicts = []
    seen_branches = set()
    for issue_n in issue_numbers:
        active = worklog.check_active_work(conn, issue_n, issue_repo)
        if active is None:
            continue
        for item in active:
            branch = item["branch"]
            if branch not in seen_branches:
                seen_branches.add(branch)
                loc = item.get("location", "primary")
                path = item.get("repo_path", "")
                slot = item.get("slot_id", "")
                slot_str = f" (slot {slot})" if slot else ""
                conflicts.append(
                    f"{issue_n}:{branch}:{loc}{slot_str}:{path}"
                )

    conn.close()

    if conflicts:
        branches = sorted(seen_branches)
        print("DUPLICATE=yes")
        print(f"ACTIVE_BRANCHES={','.join(branches)}")
        for c in conflicts:
            print(f"CONFLICT={c}")
    else:
        print("DUPLICATE=no")


if __name__ == "__main__":
    main()
