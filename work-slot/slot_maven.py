"""slot_maven.py — Maven CLRM wrapper and slot repo setup.

Uses Maven's Chained Local Repository Manager (3.9.0+) to layer a
slot-specific .m2 over the host ~/.m2. The slot .m2 is the head
(read-write), the host .m2 is the tail (read-only). No duplication
of third-party deps, no staleness of org artifacts.
"""

import os
import stat
from pathlib import Path


def generate_mvn_wrapper(slot_dir: Path) -> Path:
    """Generate a slot-level mvn wrapper that configures CLRM.

    The wrapper passes -Dmaven.repo.local (head) and
    -Dmaven.repo.local.tail (tail) to every mvn invocation.
    All repos in the slot use this wrapper instead of /opt/homebrew/bin/mvn.
    """
    wrapper = slot_dir / "mvn"
    m2_path = slot_dir / ".m2" / "repository"
    m2_path.mkdir(parents=True, exist_ok=True)
    host_m2 = Path.home() / ".m2" / "repository"

    wrapper.write_text(f"""\
#!/bin/bash
# Slot Maven wrapper — CLRM (Chained Local Repository Manager)
# Head (read-write): slot .m2 — receives installed and cached artifacts
# Tail (read-only):  host .m2 — shared deps, never modified by slot builds
SLOT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec /opt/homebrew/bin/mvn \\
  -Dmaven.repo.local="${{SLOT_DIR}}/.m2/repository" \\
  -Dmaven.repo.local.tail="{host_m2}" \\
  "$@"
""")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return wrapper


def setup_slot_repo(repo_worktree: Path, m2_path: Path) -> bool:
    """Set up .gitignore for a slot repo. Returns True if .gitignore was modified."""
    BASELINE_PATTERNS = [
        ".mvn/maven.config",
        ".mvn/slot-settings.xml",
        ".worktrees",
        ".worktrees/",
        ".claude",
        ".claude/",
    ]
    gitignore = repo_worktree / ".gitignore"
    if gitignore.exists():
        existing_lines = {line.strip() for line in gitignore.read_text().splitlines()}
        to_add = [p for p in BASELINE_PATTERNS if p not in existing_lines]
        if to_add:
            content = gitignore.read_text().rstrip()
            gitignore.write_text(content + "\n" + "\n".join(to_add) + "\n")
            return True
        return False
    else:
        gitignore.write_text("\n".join(BASELINE_PATTERNS) + "\n")
        return True
