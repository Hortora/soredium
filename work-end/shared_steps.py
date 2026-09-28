#!/usr/bin/env python3
"""Re-export from project/ for backward compat (#384)."""
import importlib.util
import sys
from pathlib import Path

_target = Path(__file__).resolve().parent.parent / "project" / "shared_steps.py"
_spec = importlib.util.spec_from_file_location("_project_shared_steps", str(_target))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

for _name in dir(_mod):
    if not _name.startswith('__'):
        globals()[_name] = getattr(_mod, _name)
