#!/usr/bin/env python3
"""
Land a branch onto its base — replaces the mechanical parts of Step 8j.

Three subcommands that bracket the LLM squash analysis:

  rebase    — detect topology, fetch, rebase branch onto base
  push      — verify artifact stamp, push to fork remote
  stamp     — verify content landed, write branch-closed stamp

The squash analysis (LLM) and blessed repo delivery (interactive prompt)
happen between these calls and stay in the skill.

Usage:
    python3 land_branch.py rebase <project> branch=<name> base_branch=<base>
    python3 land_branch.py push   <project> base_branch=<base>
    python3 land_branch.py stamp  <project> branch=<name> base_branch=<base>

Output: KEY=value lines (stdout). Errors on stderr, exit code 1.
"""

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import parse_args, detect_topology


# ---------------------------------------------------------------------------
# Library API — typed interface for command layer
# ---------------------------------------------------------------------------

@dataclass
class StampResult:
    success: bool
    landed_sha: str | None = None
    already_stamped: bool = False
    error: str | None = None

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))
try:
    import worklog as _wl
except ImportError:
    _wl = None


def git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True,
    )


def cmd_rebase(project: str, opts: dict[str, str]) -> int:
    branch = opts.get("branch", "")
    base_branch = opts.get("base_branch", "main")

    if not branch:
        print("ERROR=MISSING_ARGS")
        print("ERROR_DETAIL=branch= is required")
        return 1

    fork_remote, blessed_remote = detect_topology(project)
    print(f"FORK_REMOTE={fork_remote}")
    print(f"BLESSED_REMOTE={blessed_remote}")

    if not fork_remote:
        print("ERROR=NO_REMOTE")
        print("ERROR_DETAIL=no origin remote configured")
        return 1

    result = git(project, "fetch", fork_remote, base_branch)
    if result.returncode != 0:
        print(f"FETCH_WARNING=no network — using local {base_branch}", file=sys.stderr)

    result = git(project, "checkout", base_branch)
    if result.returncode != 0:
        print("ERROR=CHECKOUT_FAILED")
        print(f"ERROR_DETAIL=cannot checkout {base_branch}: {result.stderr.strip()}")
        return 1

    result = git(project, "rebase", branch)
    if result.returncode != 0:
        conflict_detail = result.stderr.strip()
        git(project, "rebase", "--abort")
        print("ERROR=REBASE_CONFLICT")
        print(f"ERROR_DETAIL={conflict_detail}")
        print("FALLBACK=yes")
        return 1

    print("REBASE=ok")
    return 0


def cmd_push(project: str, opts: dict[str, str]) -> int:
    base_branch = opts.get("base_branch", "main")
    workspace = opts.get("workspace", "")

    if workspace:
        stamp_path = Path(workspace) / "design" / ".artifacts-promoted"
        if not stamp_path.exists():
            print("ERROR=MISSING_STAMP")
            print("ERROR_DETAIL=.artifacts-promoted stamp not found — return to Step 8a")
            return 1
        stamp_text = stamp_path.read_text()
        branch_in_stamp = ""
        for line in stamp_text.splitlines():
            if line.startswith("branch="):
                branch_in_stamp = line.split("=", 1)[1].strip()
        if branch_in_stamp and branch_in_stamp != opts.get("branch", ""):
            print("ERROR=STAMP_MISMATCH")
            print(f"ERROR_DETAIL=stamp branch={branch_in_stamp} does not match current branch")
            return 1

    fork_remote, _ = detect_topology(project)
    if not fork_remote:
        print("ERROR=NO_REMOTE")
        print("ERROR_DETAIL=no origin remote configured")
        return 1

    result = git(project, "push", fork_remote, base_branch)
    if result.returncode != 0:
        print("ERROR=PUSH_FAILED")
        print(f"ERROR_DETAIL={result.stderr.strip()}")
        return 1

    print("PUSH=ok")
    print(f"PUSHED_TO={fork_remote}/{base_branch}")
    return 0


def cmd_stamp(project: str, opts: dict[str, str]) -> int:
    branch = opts.get("branch", "")
    base_branch = opts.get("base_branch", "main")

    if not branch:
        print("ERROR=MISSING_ARGS")
        print("ERROR_DETAIL=branch= is required")
        return 1

    verify_script = Path(__file__).parent / "verify_stamp.py"
    result = subprocess.run(
        [sys.executable, str(verify_script), project, branch, base_branch],
        capture_output=True, text=True,
    )

    verified = False
    for line in result.stdout.strip().split("\n"):
        if line == "VERIFIED=yes":
            verified = True

    if not verified:
        print("ERROR=VERIFICATION_FAILED")
        print(f"ERROR_DETAIL=content on {branch} not reflected on {base_branch}")
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        return 1

    landed_sha_result = git(project, "rev-parse", "HEAD")
    if landed_sha_result.returncode != 0:
        print("ERROR=SHA_FAILED")
        print("ERROR_DETAIL=cannot determine HEAD sha")
        return 1

    landed_sha = landed_sha_result.stdout.strip()

    tip_msg = git(project, "log", "-1", "--format=%s", branch)
    already_stamped = tip_msg.returncode == 0 and tip_msg.stdout.strip().startswith("chore: branch closed")

    if already_stamped:
        print("STAMP=ok")
        print("STAMP_SKIPPED=already_stamped")
        print(f"LANDED_SHA={landed_sha}")
    else:
        result = git(project, "checkout", branch)
        if result.returncode != 0:
            print("ERROR=CHECKOUT_FAILED")
            print(f"ERROR_DETAIL=cannot checkout {branch}: {result.stderr.strip()}")
            return 1

        issue_match = re.match(r"issue-(\d+)", branch)
        issue_ref = f"  Refs #{issue_match.group(1)}" if issue_match else ""
        result = git(project, "commit", "--allow-empty",
                     "-m", f"chore: branch closed — landed as {landed_sha} on {base_branch}{issue_ref}")
        if result.returncode != 0:
            print("ERROR=STAMP_FAILED")
            print(f"ERROR_DETAIL={result.stderr.strip()}")
            return 1

        result = git(project, "checkout", base_branch)
        if result.returncode != 0:
            print(f"CHECKOUT_WARNING=could not return to {base_branch}", file=sys.stderr)

        print("STAMP=ok")
        print(f"LANDED_SHA={landed_sha}")

    fork_remote, _ = detect_topology(project)
    if fork_remote:
        push_result = git(project, "push", fork_remote, branch, "--force-with-lease")
        if push_result.returncode != 0:
            print(f"STAMP_PUSH_WARNING=push failed: {push_result.stderr.strip()}", file=sys.stderr)

    if _wl:
        try:
            _conn = _wl.connect()
            _wl.record_work_end(_conn, branch, project, landed_sha=landed_sha)
            _conn.close()
        except Exception:
            pass

    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: land_branch.py <rebase|push|stamp> <project> key=value ...", file=sys.stderr)
        return 1

    command = sys.argv[1]
    project = sys.argv[2]
    opts = parse_args(sys.argv[3:])

    result = git(project, "rev-parse", "--git-dir")
    if result.returncode != 0:
        print("ERROR=NOT_A_REPO")
        print(f"ERROR_DETAIL={project} is not a git repository")
        return 1

    if command == "rebase":
        return cmd_rebase(project, opts)
    elif command == "push":
        return cmd_push(project, opts)
    elif command == "stamp":
        return cmd_stamp(project, opts)
    else:
        print(f"ERROR=UNKNOWN_COMMAND")
        print(f"ERROR_DETAIL=unknown command '{command}' — use rebase, push, or stamp")
        return 1


if __name__ == "__main__":
    sys.exit(main())
