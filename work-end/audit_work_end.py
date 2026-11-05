#!/usr/bin/env python3
"""Audit tool for work-end close ceremony.

Verifies close.py exists, tests resolve() with current workspace state,
and reports what would be closed.

Usage:
    python3 work-end/audit_work_end.py workspace=<path>
    python3 work-end/audit_work_end.py mode=check
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from close import resolve, preflight, CloseTarget
from queue_io import read_queue


def audit_workspace(workspace: Path) -> dict:
    queue = read_queue(workspace)
    if not queue:
        return {"RESULT": "SKIP", "REASON": "no queue found"}

    targets = resolve(workspace)
    if not targets:
        return {
            "RESULT": "WARN",
            "REASON": "no close targets — branch may not exist",
            "QUEUE_STATUS": queue.state.status,
            "QUEUE_BRANCH": queue.state.branch,
        }

    pre = preflight(targets)

    return {
        "RESULT": "PASS" if not pre["errors"] else "FAIL",
        "TARGETS": len(targets),
        "TARGET_LIST": ", ".join(f"{t.repo.name}:{t.branch}" for t in targets),
        "QUEUE_STATUS": queue.state.status,
        "QUEUE_BRANCH": queue.state.branch,
        "PREFLIGHT_ERRORS": "; ".join(pre["errors"]) if pre["errors"] else "none",
        "RESCUED": len(pre.get("rescued", {})),
    }


def audit_module() -> dict:
    close_py = Path(__file__).parent / "close.py"
    queue_io = Path(__file__).parent.parent / "project" / "queue_io.py"

    checks = {
        "close.py_exists": close_py.exists(),
        "queue_io.py_exists": queue_io.exists(),
    }

    try:
        from close import close, resolve, preflight, stamp, advance, land
        checks["close_importable"] = True
        checks["has_resolve"] = callable(resolve)
        checks["has_preflight"] = callable(preflight)
        checks["has_land"] = callable(land)
        checks["has_stamp"] = callable(stamp)
        checks["has_advance"] = callable(advance)
        checks["has_close"] = callable(close)
    except ImportError as e:
        checks["close_importable"] = False
        checks["import_error"] = str(e)

    all_pass = all(v for k, v in checks.items() if not k.endswith("_error"))
    return {"RESULT": "PASS" if all_pass else "FAIL", **{k: str(v) for k, v in checks.items()}}


def main():
    args = {}
    for arg in sys.argv[1:]:
        if "=" in arg:
            k, _, v = arg.partition("=")
            args[k] = v

    mode = args.get("mode", "")
    workspace = args.get("workspace", "")

    if mode == "check":
        result = audit_module()
    elif workspace:
        result = audit_workspace(Path(workspace))
    else:
        result = audit_module()

    for k, v in result.items():
        print(f"{k}={v}")


if __name__ == "__main__":
    main()
