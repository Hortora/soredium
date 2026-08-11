#!/usr/bin/env python3
"""
Pause stack manager for soredium workspace lifecycle.

The pause stack is a YAML file (.pause-stack) on workspace main that tracks
branches paused mid-work. Shared across work-pause, work-resume, the work
router, and handover hygiene.

Usage:
    python3 ~/.claude/skills/project/stack.py depth <stack_file>
    python3 ~/.claude/skills/project/stack.py list  <stack_file>
    python3 ~/.claude/skills/project/stack.py push  <stack_file> branch=X issue=N paused=ISO wip_project=yes|no wip_workspace=yes|no
    python3 ~/.claude/skills/project/stack.py pop   <stack_file> <branch_name>

Output:
    depth → single integer on stdout
    list  → KEY=value lines, one ENTRY_N_KEY=value block per entry (N=1-based index)
              ENTRY_COUNT=N
              ENTRY_1_BRANCH=...  ENTRY_1_ISSUE=...  ENTRY_1_PAUSED=...
              ENTRY_1_WIP_PROJECT=...  ENTRY_1_WIP_WORKSPACE=...
              ENTRY_2_BRANCH=...  etc.
    push  → STACK_DEPTH=N  (new depth after push)
    pop   → REMOVED=yes|no  STACK_DEPTH=N  (depth after pop)

Exit codes:
    0  success
    1  bad arguments or I/O error
"""

import sys
import re
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Stack file parsing
# ---------------------------------------------------------------------------

def _parse_entries(text: str) -> list[dict]:
    """Parse YAML-block entries from stack file text. Returns list of dicts."""
    entries = []
    current: dict | None = None
    for line in text.splitlines():
        if line.startswith("- branch:"):
            if current is not None:
                entries.append(current)
            current = {"branch": line[len("- branch:"):].strip()}
        elif current is not None and line.startswith("  ") and ":" in line:
            key, _, val = line.strip().partition(": ")
            current[key.strip()] = val.strip()
    if current is not None:
        entries.append(current)
    return entries


def _entries_to_text(entries: list[dict]) -> str:
    """Serialise entries back to YAML-block format."""
    known_order = ("issue", "paused", "wip_project", "wip_workspace", "slot",
                   "epic_batch", "epic_active_issue",
                   "plan_active_issue", "plan_position")
    lines = []
    for e in entries:
        lines.append(f"- branch: {e.get('branch', '')}")
        written: set[str] = set()
        for key in known_order:
            if key in e:
                lines.append(f"  {key}: {e[key]}")
                written.add(key)
        for key in sorted(e.keys()):
            if key not in written and key != "branch":
                lines.append(f"  {key}: {e[key]}")
    return "\n".join(lines) + ("\n" if lines else "")


def _read_entries(stack_file: Path) -> list[dict]:
    if not stack_file.exists():
        return []
    return _parse_entries(stack_file.read_text())


# ---------------------------------------------------------------------------
# Library API — typed dataclass interface for command layer
# ---------------------------------------------------------------------------

@dataclass
class StackEntry:
    branch: str
    issue: int
    paused: str
    wip_project: bool
    wip_workspace: bool


def _entry_to_dict(entry: StackEntry) -> dict:
    return {
        "branch": entry.branch,
        "issue": str(entry.issue),
        "paused": entry.paused,
        "wip_project": "yes" if entry.wip_project else "no",
        "wip_workspace": "yes" if entry.wip_workspace else "no",
    }


def _dict_to_entry(d: dict) -> StackEntry:
    return StackEntry(
        branch=d.get("branch", ""),
        issue=int(d.get("issue", 0)),
        paused=d.get("paused", ""),
        wip_project=d.get("wip_project", "no") == "yes",
        wip_workspace=d.get("wip_workspace", "no") == "yes",
    )


def read_entries(stack_path: Path) -> list[StackEntry]:
    """Read pause stack entries. Returns empty list if file missing."""
    return [_dict_to_entry(d) for d in _read_entries(stack_path)]


def push_entry(stack_path: Path, entry: StackEntry) -> int:
    """Push entry onto stack (appends — most recent is last). Returns new depth."""
    raw = _read_entries(stack_path)
    raw = [e for e in raw if e.get("branch") != entry.branch]
    raw.append(_entry_to_dict(entry))
    stack_path.parent.mkdir(parents=True, exist_ok=True)
    stack_path.write_text(_entries_to_text(raw))
    return len(raw)


def pop_entry(stack_path: Path, branch: str) -> tuple[bool, int]:
    """Remove entry by branch name. Returns (removed, new_depth)."""
    raw = _read_entries(stack_path)
    before = len(raw)
    raw = [e for e in raw if e.get("branch") != branch]
    if len(raw) < before:
        stack_path.write_text(_entries_to_text(raw))
    return before != len(raw), len(raw)


# ---------------------------------------------------------------------------
# Commands (CLI entry points — print KEY=value output)
# ---------------------------------------------------------------------------

def cmd_depth(stack_file: Path) -> int:
    entries = _read_entries(stack_file)
    print(len(entries))
    return 0


def cmd_list(stack_file: Path) -> int:
    entries = _read_entries(stack_file)
    print(f"ENTRY_COUNT={len(entries)}")
    known_keys = ("BRANCH", "ISSUE", "PAUSED", "WIP_PROJECT", "WIP_WORKSPACE",
                  "SLOT", "EPIC_BATCH", "EPIC_ACTIVE_ISSUE",
                  "PLAN_ACTIVE_ISSUE", "PLAN_POSITION")
    defaults = {"wip_project": "no", "wip_workspace": "no"}
    for i, e in enumerate(entries, 1):
        for display_key in known_keys:
            dict_key = display_key.lower()
            print(f"ENTRY_{i}_{display_key}={e.get(dict_key, defaults.get(dict_key, ''))}")
    return 0


def cmd_push(stack_file: Path, args: list[str]) -> int:
    """Push a new entry onto the stack. args = key=value pairs."""
    entry: dict = {}
    for arg in args:
        if "=" in arg:
            k, _, v = arg.partition("=")
            entry[k.strip()] = v.strip()

    if "branch" not in entry or not entry["branch"]:
        print("ERROR: branch=<name> is required for push", file=sys.stderr)
        return 1

    if "paused" not in entry:
        entry["paused"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entries = _read_entries(stack_file)
    # Remove existing entry for same branch (idempotent push)
    entries = [e for e in entries if e.get("branch") != entry["branch"]]
    entries.append(entry)

    stack_file.parent.mkdir(parents=True, exist_ok=True)
    stack_file.write_text(_entries_to_text(entries))
    print(f"STACK_DEPTH={len(entries)}")
    return 0


def cmd_pop(stack_file: Path, branch_name: str) -> int:
    """Remove the named branch from the stack."""
    entries = _read_entries(stack_file)
    before = len(entries)
    entries = [e for e in entries if e.get("branch") != branch_name]
    removed = len(entries) < before

    if removed:
        stack_file.write_text(_entries_to_text(entries))

    print(f"REMOVED={'yes' if removed else 'no'}")
    print(f"STACK_DEPTH={len(entries)}")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1

    command = sys.argv[1]
    stack_file = Path(sys.argv[2])

    if command == "depth":
        return cmd_depth(stack_file)
    elif command == "list":
        return cmd_list(stack_file)
    elif command == "push":
        return cmd_push(stack_file, sys.argv[3:])
    elif command == "pop":
        if len(sys.argv) < 4:
            print("ERROR: pop requires <stack_file> <branch_name>", file=sys.stderr)
            return 1
        return cmd_pop(stack_file, sys.argv[3])
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
