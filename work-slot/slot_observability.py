"""Worklog recording wrapper for slot operations.

Centralizes the inline try/connect/record/close pattern that appears
throughout the lifecycle orchestrators.
"""

import sys
from pathlib import Path

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))
try:
    import worklog as _wl
except ImportError:
    _wl = None


def get_worklog():
    """Return the worklog module or None if unavailable."""
    return _wl


def record_worklog(func_name: str, *args, **kwargs) -> bool:
    """Call a worklog function by name. Returns True on success, False otherwise.

    Usage: record_worklog("record_slot_merge", conn, slot_num, str(family_root), ...)
    """
    if _wl is None:
        return False
    try:
        fn = getattr(_wl, func_name, None)
        if fn is None:
            return False
        fn(*args, **kwargs)
        return True
    except Exception:
        return False
