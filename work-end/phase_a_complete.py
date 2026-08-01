#!/usr/bin/env python3
"""
Write .phase-a-complete marker and record the event in the worklog.

Usage:
    python3 phase_a_complete.py <slot-root> branch=<name> repos=<csv> family-root=<path>

Output (KEY=value lines):
    MARKER=<path>
    WORKLOG=yes|skipped

Exit codes:
    0  success
    1  missing required args
"""

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import parse_args  # noqa: E402

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))
try:
    import worklog as _wl
except ImportError:
    _wl = None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    slot_root = Path(sys.argv[1])
    params = parse_args(sys.argv[2:])
    branch = params.get("branch", "")
    repos = params.get("repos", "")
    family_root = params.get("family-root", "")

    if not branch:
        print("ERROR=missing_branch")
        return 1
    if not repos:
        print("ERROR=missing_repos")
        return 1

    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    marker = slot_root / ".phase-a-complete"
    marker.write_text(
        f"branch={branch}\n"
        f"repos={repos}\n"
        f"timestamp={timestamp}\n"
    )
    print(f"MARKER={marker}")

    if _wl and family_root:
        try:
            slot_num = int(slot_root.name)
            conn = _wl.connect()
            _wl.record_slot_phase_a(conn, slot_num, family_root)
            conn.close()
            print("WORKLOG=yes")
        except Exception:
            print("WORKLOG=skipped")
    else:
        print("WORKLOG=skipped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
