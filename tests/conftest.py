"""Test configuration — makes skill directories importable as Python packages."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

SOREDIUM_ROOT = Path(__file__).parent.parent

# Git in tests never sees this machine's configuration (#565). A developer's
# global config can route every commit through hooks that have nothing to do
# with the code under test: on a machine with a managed secret scanner that
# more than doubled the time of every test that commits. It also made results
# depend on the machine (default branch name, identity, signing).
# Each pytest process, and each xdist worker, gets its own generated config.
# A test that needs a different one sets GIT_CONFIG_GLOBAL itself.
import tempfile  # noqa: E402

_GIT_CONFIG = Path(tempfile.mkdtemp(prefix="soredium-test-git-")) / "gitconfig"
_GIT_CONFIG.write_text(
    "[init]\n\tdefaultBranch = main\n"
    "[user]\n\tname = Soredium Tests\n\temail = tests@soredium.invalid\n"
    "[commit]\n\tgpgsign = false\n"
    "[tag]\n\tgpgsign = false\n"
    "[advice]\n\tdetachedHead = false\n"
)
os.environ["GIT_CONFIG_GLOBAL"] = str(_GIT_CONFIG)
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
for _name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
              "GIT_COMMITTER_EMAIL", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
    os.environ.pop(_name, None)

# Pin the repo's own directories at the front of sys.path so that
# imports always resolve to the code under test, not to the installed
# copies under ~/.claude/skills/.
_REPO_DIRS = ("project", "work-end", "work-slot", "verification", "scripts")
for _dir_name in _REPO_DIRS:
    _dir = str(SOREDIUM_ROOT / _dir_name)
    if _dir in sys.path:
        sys.path.remove(_dir)
    sys.path.insert(0, _dir)

# Preload worklog from the repo's scripts/ directory.  Thirteen production
# modules insert ~/.claude/lib onto sys.path and then `import worklog`.
# The installed worklog.py's fallback adds ~/.claude/skills/project/ to
# sys.path (its sibling project/ does not exist).  By loading the repo's
# copy first, it caches in sys.modules; the later ~/.claude/lib inserts
# become harmless because worklog is already resolved — and the repo's
# copy finds its sibling project/ on the first try, so the installed
# skills path is never added.
# scripts/ is already at the front of sys.path from the pin above.
import worklog as _worklog  # noqa: E402
_worklog_expected = str(SOREDIUM_ROOT / "scripts" / "worklog.py")
assert _worklog.__file__ == _worklog_expected, (
    f"worklog loaded from {_worklog.__file__}, expected {_worklog_expected}"
)

_FORBIDDEN_PREFIXES = (
    str(Path.home() / ".claude" / "skills") + os.sep,
    str(Path.home() / ".claude" / "lib") + os.sep,
)


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


@pytest.fixture(autouse=True)
def _guard_installed_imports(request: pytest.FixtureRequest) -> None:
    """Fail loudly if any module was loaded from the installed skills or
    lib directory instead of the repo under test."""
    yield
    for name, mod in sys.modules.items():
        f = getattr(mod, "__file__", None) or ""
        if any(f.startswith(p) for p in _FORBIDDEN_PREFIXES):
            pytest.fail(
                f"Module {name!r} loaded from installed copy {f} "
                f"instead of the repo under test (during {request.node.nodeid})"
            )
