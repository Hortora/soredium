#!/usr/bin/env python3
"""Re-export from project/work_progress.py for backward compat (#384)."""
import importlib.util
from pathlib import Path

_target = Path(__file__).resolve().parent.parent / "project" / "work_progress.py"
_spec = importlib.util.spec_from_file_location("_project_work_progress", str(_target))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

for _name in dir(_mod):
    if not _name.startswith('__'):
        globals()[_name] = getattr(_mod, _name)
