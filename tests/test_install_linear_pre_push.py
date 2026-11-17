"""scripts/install_linear_pre_push.py: replace the old pre-push hooks, touch nothing else."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import install_linear_pre_push as installer  # noqa: E402

OLD_SQUASH = "#!/bin/bash\nSQUASH_PATTERNS='(^chore: pin )'\nexit 1\n"
OLD_PROMPT = "#!/bin/bash\n# pre-push hook: always prompt for /git-squash review before pushing.\nexit 1\n"
CUSTOM = "#!/bin/sh\n# Block Secrets dispatcher\nexit 0\n"


def g(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def repo_with_hook(root: Path, name: str, content: str | None, hooks_path: bool = False) -> Path:
    repo = root / name
    repo.mkdir(parents=True)
    g(repo, "init", "-q", "-b", "main")
    g(repo, "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
    if content is None:
        return repo
    if hooks_path:
        (repo / ".githooks").mkdir()
        hook = repo / ".githooks" / "pre-push"
        g(repo, "config", "core.hooksPath", ".githooks")
    else:
        hook = repo / ".git" / "hooks" / "pre-push"
        hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(content)
    hook.chmod(0o755)
    if hooks_path:
        g(repo, "add", ".githooks")
        g(repo, "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-q", "-m", "hooks")
    return repo


def lines(capsys) -> list[str]:
    return capsys.readouterr().out.splitlines()


def test_dry_run_reports_and_changes_nothing(tmp_path, capsys):
    repo = repo_with_hook(tmp_path, "a", OLD_SQUASH)

    assert installer.main([str(tmp_path)]) == 0

    out = lines(capsys)
    assert out[0] == "MODE=dry-run"
    assert any(l.startswith(f"REPLACE={repo} ") and "kind=squash-candidates" in l
               and "tracked=no" in l for l in out)
    assert (repo / ".git" / "hooks" / "pre-push").read_text() == OLD_SQUASH


def test_apply_replaces_both_old_kinds_and_leaves_the_rest(tmp_path, capsys):
    squash = repo_with_hook(tmp_path, "a-squash", OLD_SQUASH)
    prompt = repo_with_hook(tmp_path, "b-prompt", OLD_PROMPT, hooks_path=True)
    custom = repo_with_hook(tmp_path, "c-custom", CUSTOM)
    bare = repo_with_hook(tmp_path, "d-none", None)

    assert installer.main([str(tmp_path), "--apply"]) == 0

    out = lines(capsys)
    new = installer.SOURCE.read_text()
    assert (squash / ".git" / "hooks" / "pre-push").read_text() == new
    assert (prompt / ".githooks" / "pre-push").read_text() == new
    assert (custom / ".git" / "hooks" / "pre-push").read_text() == CUSTOM
    assert not (bare / ".git" / "hooks" / "pre-push").exists()
    assert any(l.startswith(f"REPLACED={prompt} ") and "tracked=yes" in l for l in out)
    assert f"OTHER_LEFT={custom}" in out
    assert out[-1] == "SUMMARY=NONE:1, OTHER_LEFT:1, REPLACED:2"
    assert g(prompt, "status", "--porcelain").strip() == "M .githooks/pre-push"   # left to commit
    assert g(prompt, "log", "--oneline").count("\n") == 1                          # never commits


def test_running_again_finds_nothing_to_do(tmp_path, capsys):
    repo_with_hook(tmp_path, "a", OLD_PROMPT)
    installer.main([str(tmp_path), "--apply"])
    capsys.readouterr()

    installer.main([str(tmp_path), "--apply"])

    assert lines(capsys)[-1] == "SUMMARY=OK:1"


def test_replaced_hook_is_executable_and_lets_a_plain_push_through(tmp_path):
    repo = repo_with_hook(tmp_path, "a", OLD_PROMPT, hooks_path=True)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)],
                   capture_output=True, check=True)
    g(repo, "remote", "add", "origin", str(remote))
    blocked = subprocess.run(["git", "-C", str(repo), "push", "origin", "main"], capture_output=True)
    assert blocked.returncode != 0                      # the old hook refused every push

    installer.main([str(tmp_path), "--apply"])

    pushed = subprocess.run(["git", "-C", str(repo), "push", "origin", "main"],
                            capture_output=True, text=True)
    assert pushed.returncode == 0, pushed.stderr
    assert g(remote, "rev-parse", "main") == g(repo, "rev-parse", "main")


def test_usage_error():
    assert installer.main([]) == 2
