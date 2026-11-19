"""Git in tests does not see the machine's configuration (#565)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd).stdout.strip()


def test_global_config_is_the_generated_one():
    path = Path(os.environ["GIT_CONFIG_GLOBAL"])
    assert path.is_file() and "soredium-test-git-" in str(path)
    assert os.environ["GIT_CONFIG_NOSYSTEM"] == "1"


def test_no_hooks_path_is_inherited(tmp_path):
    _git("init", "-q", str(tmp_path))
    assert _git("-C", str(tmp_path), "config", "--get", "core.hooksPath") == ""


def test_default_branch_and_identity_do_not_depend_on_the_machine(tmp_path):
    _git("init", "-q", str(tmp_path))
    assert _git("-C", str(tmp_path), "symbolic-ref", "--short", "HEAD") == "main"
    assert _git("-C", str(tmp_path), "config", "user.email") == "tests@soredium.invalid"


def test_a_commit_runs_only_the_repo_s_own_hooks(tmp_path):
    _git("init", "-q", str(tmp_path))
    marker = tmp_path / "ran"
    hook = tmp_path / ".git" / "hooks" / "post-commit"
    hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    hook.chmod(0o755)
    done = subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "--allow-empty", "-m", "x"],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert marker.exists()
    assert "Block Secrets" not in done.stderr + done.stdout
