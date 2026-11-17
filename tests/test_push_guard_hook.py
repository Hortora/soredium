"""hooks/push-guard.py, run the way Claude Code runs a PreToolUse hook.

A hook blocks only by exiting 2 with the reason on stderr. An earlier guard in
this project printed BLOCK on stdout and exited 0 for months and blocked
nothing, so every blocking test here checks the exit code, checks stderr, and
then actually attempts the push to show what the guard stood in front of.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / "hooks" / "push-guard.py"


def g(repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=check).stdout.strip()


def hook(command: str, cwd: Path) -> subprocess.CompletedProcess:
    """Invoke the hook exactly as the harness does: JSON on stdin, verdict in the exit code."""
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": command}, "cwd": str(cwd)}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True)


def run_if_allowed(command: str, cwd: Path) -> tuple[subprocess.CompletedProcess, bool]:
    """What the harness does: run the command only when the hook did not exit 2."""
    verdict = hook(command, cwd)
    if verdict.returncode == 2:
        return verdict, False
    subprocess.run(command, shell=True, cwd=str(cwd), capture_output=True, text=True)
    return verdict, True


@pytest.fixture
def world(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)],
                   capture_output=True, check=True)
    canon = tmp_path / "family" / "engine"
    canon.mkdir(parents=True)
    g(canon, "init", "-q", "-b", "main")
    g(canon, "config", "user.name", "T")
    g(canon, "config", "user.email", "t@t")
    (canon / "a.txt").write_text("a\n")
    g(canon, "add", ".")
    g(canon, "commit", "-q", "-m", "init")
    g(canon, "remote", "add", "origin", str(remote))
    g(canon, "push", "-q", "-u", "origin", "main")

    slot = tmp_path / "family" / "slots" / "3"
    slot.mkdir(parents=True)
    (slot / ".slot").write_text("# Slot 3\n")
    clone = slot / "engine"
    subprocess.run(["git", "clone", "-q", str(canon), str(clone)], capture_output=True, check=True)
    g(clone, "config", "user.name", "T")
    g(clone, "config", "user.email", "t@t")
    g(clone, "remote", "rename", "origin", "local")
    g(clone, "remote", "add", "origin", str(remote))
    g(clone, "checkout", "-q", "-b", "issue-1-feat")
    (clone / "b.txt").write_text("b\n")
    g(clone, "add", ".")
    g(clone, "commit", "-q", "-m", "feat: b")
    return canon, clone, remote


def remote_refs(remote: Path) -> list[str]:
    return g(remote, "for-each-ref", "--format=%(refname)").split()


class TestBlocks:
    def test_push_from_a_slot_clone_is_blocked_and_does_not_happen(self, world):
        canon, clone, remote = world

        verdict, ran = run_if_allowed("git push -u origin HEAD", clone)

        assert verdict.returncode == 2
        assert "BLOCK" in verdict.stderr and "slot" in verdict.stderr
        assert "canonical_sync.py publish" in verdict.stderr
        assert verdict.stdout == ""
        assert ran is False
        assert remote_refs(remote) == ["refs/heads/main"]

    def test_the_same_push_does_reach_the_remote_without_the_guard(self, world):
        """Shows the fixture is real: the blocked command would have published the branch."""
        canon, clone, remote = world
        subprocess.run("git push -u origin HEAD", shell=True, cwd=str(clone), capture_output=True)
        assert "refs/heads/issue-1-feat" in remote_refs(remote)

    def test_slot_clone_named_with_dash_c_from_elsewhere(self, world, tmp_path):
        canon, clone, remote = world
        verdict, ran = run_if_allowed(f"git -C {clone} push origin issue-1-feat", tmp_path)
        assert verdict.returncode == 2 and ran is False
        assert remote_refs(remote) == ["refs/heads/main"]

    def test_slot_clone_reached_with_cd_in_a_chain(self, world, tmp_path):
        canon, clone, remote = world
        verdict, ran = run_if_allowed(f"cd {clone} && git add -A && git push", tmp_path)
        assert verdict.returncode == 2 and ran is False

    def test_even_the_base_branch_is_not_pushed_from_a_slot(self, world):
        canon, clone, remote = world
        verdict, _ = run_if_allowed("git push origin main", clone)
        assert verdict.returncode == 2

    def test_slot_clone_recognised_by_its_local_remote_alone(self, world):
        canon, clone, remote = world
        (clone.parent / ".slot").unlink()
        verdict, _ = run_if_allowed("git push origin HEAD", clone)
        assert verdict.returncode == 2

    def test_working_branch_from_a_canonical_repo_is_blocked(self, world):
        canon, clone, remote = world
        g(canon, "checkout", "-q", "-b", "issue-9-fix")
        (canon / "c.txt").write_text("c\n")
        g(canon, "add", ".")
        g(canon, "commit", "-q", "-m", "fix: c")

        verdict, ran = run_if_allowed("git push -u origin issue-9-fix", canon)

        assert verdict.returncode == 2 and ran is False
        assert "working branch" in verdict.stderr
        assert remote_refs(remote) == ["refs/heads/main"]

    def test_bare_push_while_on_a_working_branch_is_blocked(self, world):
        canon, clone, remote = world
        g(canon, "checkout", "-q", "-b", "issue-9-fix")
        verdict, _ = run_if_allowed("git push", canon)
        assert verdict.returncode == 2

    @pytest.mark.parametrize("command", [
        "git push --force-with-lease origin issue-9-fix",
        "git push origin HEAD:refs/heads/issue-9-fix",
        "git push origin main issue-9-fix",
        "git push --all origin",
        "git push --mirror",
        "FOO=1 git push origin issue-9-fix",
        "/usr/bin/git push origin issue-9-fix",
        "git -c push.default=current push origin issue-9-fix",
        "echo start; git push origin issue-9-fix | tail -1",
    ])
    def test_other_ways_of_pushing_a_working_branch(self, world, command):
        canon, clone, remote = world
        g(canon, "branch", "issue-9-fix")
        assert hook(command, canon).returncode == 2


class TestAllows:
    def test_base_branch_from_a_canonical_repo_is_allowed_and_happens(self, world):
        canon, clone, remote = world
        (canon / "c.txt").write_text("c\n")
        g(canon, "add", ".")
        g(canon, "commit", "-q", "-m", "feat: c")

        verdict, ran = run_if_allowed("git push origin main", canon)

        assert verdict.returncode == 0 and ran is True
        assert g(remote, "rev-parse", "main") == g(canon, "rev-parse", "main")

    @pytest.mark.parametrize("command", [
        "git push",
        "git push origin",
        "git push origin HEAD",
        "git push origin main:main",
        "git push --dry-run origin issue-9-fix",
        "git push --help",
        "git push origin --tags",
        "git push origin :old-branch",
        "git push origin --delete old-branch",
        "git status && git log --oneline -3",
        "echo 'git push origin feature' > notes.txt",
        "python3 ~/.claude/skills/project/canonical_sync.py publish .",
        "grep -n push README.md",
    ])
    def test_harmless_or_legitimate_commands_on_canonical_main(self, world, command):
        canon, clone, remote = world
        assert hook(command, canon).returncode == 0

    def test_a_tag_is_allowed(self, world):
        canon, clone, remote = world
        g(canon, "tag", "v1.0")
        assert hook("git push origin v1.0", canon).returncode == 0
        assert hook("git push origin refs/tags/v1.0", canon).returncode == 0

    def test_outside_any_repo_it_stays_out_of_the_way(self, tmp_path):
        assert hook("git push origin feature", tmp_path).returncode == 0

    def test_non_bash_tools_and_malformed_input_never_block(self, world):
        canon, clone, remote = world
        other = subprocess.run([sys.executable, str(HOOK)],
                               input=json.dumps({"tool_name": "Edit", "tool_input": {}}),
                               capture_output=True, text=True)
        assert other.returncode == 0
        garbage = subprocess.run([sys.executable, str(HOOK)], input="not json",
                                 capture_output=True, text=True)
        assert garbage.returncode == 0

    def test_unbalanced_quotes_do_not_crash_the_hook(self, world):
        canon, clone, remote = world
        assert hook("git push origin 'unterminated", canon).returncode == 0


def test_hook_is_executable_and_registered_for_installation():
    assert os.access(HOOK, os.X_OK)
    installer = (Path(__file__).parent.parent / "scripts" / "claude-skill").read_text()
    assert '"source": "push-guard.py"' in installer
    assert '"command": "~/.claude/hooks/push-guard.py"' in installer
