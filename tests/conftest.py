"""Test configuration — makes skill directories importable as Python packages."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

SOREDIUM_ROOT = Path(__file__).parent.parent


def _register_skill_package(dir_name: str, module_name: str) -> None:
    skill_dir = SOREDIUM_ROOT / dir_name
    if skill_dir.is_dir() and module_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            module_name,
            skill_dir / "__init__.py",
            submodule_search_locations=[str(skill_dir)],
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)


_register_skill_package("design-review", "adversarial_design_review")


@pytest.fixture(autouse=True)
def _isolate_worklog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Route all worklog DB access to a temp file so tests never pollute
    the production database at ~/.hortora/worklog.db."""
    db_path = str(tmp_path / "test_worklog.db")
    monkeypatch.setenv("HORTORA_WORKLOG_DB", db_path)
